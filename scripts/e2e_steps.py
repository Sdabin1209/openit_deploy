#!/usr/bin/env python3
"""합격 시나리오(docs/E2E.md) 1~8단계. 영역 사이는 실제 서비스의 HTTP(boundary_contracts.clients)로 잇는다(D49).
모든 레코드는 boundary_contracts.validator(또는 문진 스키마)와 해시로 검증한다. 9단계(인프라)는 scripts/e2e.sh.

상태: REAL(실제 서비스·잡) / TEST-SUB(시험 대역으로 대신함) / BLOCKED(지금 구현으로는 이어지지 않음) / FAIL(검증 실패)
"""
import argparse, hashlib, json, os, pathlib, subprocess, sys, tempfile, time, urllib.request, urllib.error

import boundary_contracts as bc
from boundary_contracts import canonical
from boundary_contracts.clients import (HttpFailureStore, HttpGateService, HttpModelRegistry, HttpQuestionReader,
                                         HttpReleaseReader, HttpTraceIngest)
import survey_schema, jsonschema

ap = argparse.ArgumentParser()
ap.add_argument("--project", required=True); ap.add_argument("--secrets", required=True)
ap.add_argument("--ports", required=True); ap.add_argument("--images", required=True)
ap.add_argument("--docker", default="docker"); ap.add_argument("--root", required=True)
ap.add_argument("--work", required=True, help="이번 실행의 임시 작업 폴더")
ap.add_argument("--run-id", default="e2e-test")
ap.add_argument("--demo-stop", action="store_true", help="demo4: 승인 대기까지만 만든다(사람이 /admin/ 에서 승인)")
ap.add_argument("--only", default="", help="쉼표로 구분한 단계(예: 1,2). 비우면 전부")
ap.add_argument("--ms-url", default="", help="추론 서버를 다른 곳에 둔 경우 그 주소(예: http://gpu-host:8080). 비우면 이 프로젝트의 model-serving 컨테이너")
ap.add_argument("--ms-container", default="", help="추론 서버 컨테이너 이름(멈춤·재시작 시험용). 기본 <프로젝트>-model-serving-1")
ap.add_argument("--ms-token-file", default="", help="외부 추론 서버의 호출자 토큰 파일(EXTERNAL_INFERENCE_TOKEN=... 한 줄). 비우면 이 구성이 만든 토큰")
ap.add_argument("--llm-package", default="", help="실제 LLM 데모: make_neutral_package.py 가 만든 폴더(LORA_A, LORA_B). 단계 3이 시험용 fake 어댑터 대신 이 중립 LoRA 패키지(vllm 서빙 설정)를 게시한다")
ap.add_argument("--turn-engine-version", default=os.environ.get("DEPLOY_TE_TAG", "v0.3.0").lstrip("v"), help="매니페스트 lineage 의 turn-engine 버전(게이트 기준과 문자열이 같아야 한다, D80). e2e.sh 가 lib.sh 의 값을 넘긴다")
ap.add_argument("--skip-ms-restart", action="store_true", help="5단계의 추론 서버 중단·복구를 건너뛴다(서버 호스트 포트가 Docker 배정이라 재시작 뒤 주소가 바뀌는 별도 프로젝트 시험용)")
a = ap.parse_args()
PORTS = json.loads(a.ports); IMAGES = json.loads(a.images); ROOT = pathlib.Path(a.root); WORK = pathlib.Path(a.work)
WORK.mkdir(parents=True, exist_ok=True)
RID = a.run_id
TOK = lambda n: (pathlib.Path(a.secrets) / "tokens" / n).read_text().strip()
def INF_TOK():   # 추론 서버가 호출자(survey-service)에게 기대하는 토큰
    if a.ms_token_file:
        for ln in pathlib.Path(a.ms_token_file).read_text().splitlines():
            if ln.startswith("EXTERNAL_INFERENCE_TOKEN="): return ln.split("=", 1)[1].strip()
        raise SystemExit("--ms-token-file 에 EXTERNAL_INFERENCE_TOKEN= 줄이 없다")
    return TOK("inference-survey-service")
MS_CONTAINER = a.ms_container or f"{a.project}-model-serving-1"
def _ms_port():   # 추론 서버는 멈췄다 다시 뜨면 호스트 포트가 바뀔 수 있어 매번 Docker에게 묻는다
    out = subprocess.run([a.docker, "port", MS_CONTAINER, "8080/tcp"], capture_output=True, text=True).stdout
    return out.splitlines()[0].strip().rsplit(":", 1)[1] if out.strip() else PORTS["ms"]
URL = lambda k: a.ms_url.rstrip("/") if (k == "ms" and a.ms_url) else f"http://127.0.0.1:{_ms_port() if k == 'ms' else PORTS[k]}"
RESULTS = []; STATE_FILE = WORK / "state.json"
STATE = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
def save(): STATE_FILE.write_text(json.dumps(STATE, ensure_ascii=False, indent=1))
def rec(step, status, detail):
    RESULTS.append((step, status, detail)); print(f"  [{status}] {detail}", flush=True)
def title(n, t): print(f"\n== 단계 {n}: {t}", flush=True)
def validate(name, obj):
    errs = list(bc.validator(name).iter_errors(obj)); assert not errs, f"{name} 스키마 위반: {errs[0].message}"
def validate_survey(name, obj):
    from referencing import Registry, Resource
    d = pathlib.Path(survey_schema.schema_dir()); reg = Registry()
    for f in d.glob("*.json"): reg = reg.with_resource(f.name, Resource.from_contents(json.loads(f.read_text())))
    schema = survey_schema.load_schema(name)
    errs = list(jsonschema.validators.validator_for(schema)(schema, registry=reg).iter_errors(obj))
    assert not errs, f"문진 스키마 {name} 위반: {errs[0].message}"
def http(method, k, path, token=None, body=None, raw=None, ctype="application/json", basic=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(URL(k) + path, data=data, method=method)
    if token: req.add_header("Authorization", f"Bearer {token}")
    if basic: req.add_header("Authorization", "Basic " + __import__("base64").b64encode(f"{basic[0]}:{basic[1]}".encode()).decode())
    if data is not None: req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        b = e.read()
        try: return e.code, json.loads(b)
        except Exception: return e.code, b.decode(errors="replace")
def sh(cmd, env=None, inp=None, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True, input=inp, env={**os.environ, **(env or {})})
    if check: assert r.returncode == 0, f"{cmd[:3]} 실패({r.returncode}): {(r.stderr or r.stdout)[-600:]}"
    return r
def docker_py(image, code, mounts=()):
    cmd = [a.docker, "run", "--rm", "-i"] + [x for s, d in mounts for x in ("-v", f"{s}:{d}:ro")] + [image, "python", "-"]
    r = sh(cmd, inp=code); return r.stdout
def wait(fn, timeout, what, every=2):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v: return v
        time.sleep(every)
    raise AssertionError(f"시간 초과({timeout}s): {what}")

def decision_text(dec):
    """GateDecision 요약: 결과, reject_codes, checks 각 항목(kind, result, detail), reject_reasons. 토큰·비밀은 없다."""
    out = [f"결과 {dec.get('result')} reject_codes={dec.get('reject_codes')}"]
    for c in dec.get("checks", []):
        d = c.get("detail"); out.append(f"  - {c.get('kind')}: {c.get('result')}" + (f" -- {str(d)[:400]}" if d else ""))
    for r in dec.get("reject_reasons") or []: out.append(f"  * 사유: {str(r)[:400]}")
    return "\n".join(out)

def gate_diag_clients():   # 읽기 전용(승인자 읽기 토큰, 게이트 읽기 토큰)
    return HttpGateService(URL("gate"), TOK("gate-read-release-approver")), HttpReleaseReader(URL("gate"), TOK("gate-read-survey-service"))

def explain_submission(sid):
    """(상태, 설명 문자열). 상태를 못 읽으면 (None, 이유)."""
    try:
        gs, rd = gate_diag_clients(); v = dict(gs.get_submission(sid)); st = v.get("status"); txt = f"제출 {sid} 상태 {st}"
        if v.get("decision_id"):
            txt += "\n" + decision_text(dict(rd.get_decision(v["decision_id"])))
        return st, txt
    except Exception as e:
        return None, f"제출 {sid} 상태를 읽지 못했다: {type(e).__name__}: {str(e)[:120]}"

def wait_review_report(get_report, sid, label, timeout=60):
    """자동 검사 후 승인 요청 보고서를 기다린다. 제출이 반려(REJECTED_*)되면 시간 초과를 기다리지 않고 바로 GateDecision의 checks 를 보여 주며 실패한다."""
    t = time.time(); st = None
    while time.time() - t < timeout:
        r = get_report(sid)
        if r: return r
        st, txt = explain_submission(sid)
        if st in ("REJECTED_AUTO", "REJECTED_HUMAN"):
            raise AssertionError(f"제출 {label} 이(가) 반려되어 승인 요청 보고서가 생기지 않는다.\n{txt}")
        time.sleep(2)
    raise AssertionError(f"시간 초과({timeout}s): 자동 검사 후 승인 요청 보고서 {label}.\n{explain_submission(sid)[1]}")

qa_reader = lambda role="synthetic-data": HttpQuestionReader(URL("qa"), TOK(f"qa-read-{role}"))
SD = {"venv": ROOT / "build/venv-sd/bin/python", "src": ROOT / "build/ctx/synthetic-data", "schema": ROOT / "build/ctx/survey-service/schema"}
QS, QSU = f"qs-{RID}", f"qs-{RID}-unseen"

def upload(set_id, text, fname):
    raw = text.encode(); t = TOK("qa-author-e2e")
    c, d = http("POST", "qa", f"/v1/materials?question_set_id={set_id}&filename={fname}", t, raw=raw, ctype="text/plain")
    assert c in (200, 201), f"자료 등록 {c} {d}"
    c, pv = http("GET", "qa", f"/v1/drafts/{d['draft_id']}/preview", t); assert c == 200 and pv["ready_to_confirm"], pv
    c, ref = http("POST", "qa", f"/v1/drafts/{d['draft_id']}/confirm", t, body={"preview_hash": pv["preview_hash"]}); assert c == 200, ref
    return ref, raw

def step1():
    title(1, "저자가 문항 자료를 올리고 미리보기를 확인한다 (question-authoring, I1 HTTP 읽기)")
    form = (ROOT / "test/fixtures/question-form-v2.txt").read_text()   # 학습 데이터셋 v2 의 문항 ID 31개(survey-service 의 QuestionFlow 와 같은 순서). 값은 모두 시험용
    r1, raw1 = upload(QS, form, "form1.txt")
    r2, _ = upload(QS, form.replace("시험 문항 Q1.D01입니다. 알려 주세요.", "시험 문항 Q1.D01입니다. 말씀해 주세요."), "form2.txt")
    ru, _ = upload(QSU, form.replace("알려 주세요.", "들려 주세요."), "unseen.txt")
    assert http("GET", "qa", "/v1/drafts")[0] == 403
    rd = qa_reader()   # HTTP I1, 읽기 토큰(synthetic-data 역할)
    assert http("GET", "qa", "/v1/drafts", TOK("qa-read-synthetic-data"))[0] == 403, "읽기 토큰으로 저작 경로가 열리면 안 된다"
    assert http("POST", "qa", f"/v1/materials?question_set_id=x&filename=x.txt", TOK("qa-read-synthetic-data"), raw=b"x", ctype="text/plain")[0] == 403
    vers = rd.list_versions(QS)[0]; assert [v["version"] for v in vers] == ["1", "2"], vers
    assert dict(rd.latest(QS, reviewed_only=True))["version"] == "2"
    for v in vers + [dict(rd.latest(QSU, reviewed_only=True))]:
        bank = rd.get_question_bank(v)
        assert canonical.content_hash(bank) == v["content_hash"]; assert str(bank["version"]) == v["version"]
        validate_survey("QuestionBank", bank)
        (rv,) = rd.get_reviews(v); validate("ReviewRecord", rv)
        assert rv["decision"] == "APPROVED" and rv["clinical_basis_approved"] is True and rv["question_set"] == v
    assert rd.get_reviews(vers[0])[0]["ext"]["question-authoring"]["source"]["source_hash"] == "sha256:" + hashlib.sha256(raw1).hexdigest()
    cc = rd.get_change(vers[1]); validate("ChangeClassification", cc); assert rd.get_change(vers[0]) is None
    STATE["qs"] = [dict(v) for v in vers]; STATE["qsu"] = dict(rd.latest(QSU, reviewed_only=True)); save()
    rec(1, "REAL", f"등록→미리보기→확인 x3, I1 HTTP 읽기(읽기 토큰; 읽기 토큰은 저작 경로 403): QuestionBank 3건(해시·문진 스키마), ReviewRecord(clinical_basis_approved), ChangeClassification {cc['change_kinds']} {cc['affected_slots']}, 원본 해시 출처 일치")

def sd_config(name, seeds, failure=False, version=None):
    cfg = {"dataset_id": f"ds-{RID}", "seed": 20261015, "created_at": "2026-10-15T00:00:00Z", "style_guide_version": "1",
           "turn_engine_version": "0.2.0", "survey_schema_dir": str(SD["schema"]),
           "adapters": {"question_reader": {"factory": "synthetic_data.adapters:http_question_reader", "kwargs": {"base_url": URL("qa"), "token_env": "SD_QA_TOKEN"}}},
           "question_sets": [{"id": QS, "version": STATE["qs"][-1]["version"], "usage": "TRAIN_POOL"}, {"id": QSU, "usage": "HELD_OUT_EVAL"}],
           "reviewed_only": True, "scenarios": {"variants": 3, "noise_variants": 2}, "seeds": {"enabled": seeds},
           "generators": {"utterance": "rule", "response": "rule"}, "split": {"ratios": {"TRAIN": 0.8, "VALIDATION": 0.1, "EVAL": 0.1}},
           "review": {"per_kind": 2}, "regeneration": {"mode": "full"},
           "output": {"work_dir": str(WORK / f"sd-work-{name}"), "store": {"kind": "file", "root": str(WORK / "datasets")}}}
    if failure:
        cfg["adapters"]["failure_store"] = {"factory": "synthetic_data.adapters:http_failure_store", "kwargs": {"base_url": URL("ops"), "token_env": "SD_OPS_TOKEN"}}
        cfg["seeds"]["question_set_id"] = QS
    p = WORK / f"sd-{name}.job.json"; p.write_text(json.dumps(cfg, ensure_ascii=False, indent=1)); return p

def run_sd(name, seeds, failure=False):
    p = sd_config(name, seeds, failure)
    r = sh([str(SD["venv"]), "-m", "synthetic_data", "run", "--config", str(p)], env={"SD_QA_TOKEN": TOK("qa-read-synthetic-data"), "SD_OPS_TOKEN": TOK("ops-read-synthetic-data"), "PYTHONPATH": str(SD["src"])}, check=False) if False else \
        subprocess.run([str(SD["venv"]), "-m", "synthetic_data", "run", "--config", str(p)], cwd=str(SD["src"]), capture_output=True, text=True,
                       env={**os.environ, "SD_QA_TOKEN": TOK("qa-read-synthetic-data"), "SD_OPS_TOKEN": TOK("ops-read-synthetic-data"), "PYTHONDONTWRITEBYTECODE": "1"})
    assert r.returncode == 0, f"synthetic-data 종료 {r.returncode}: {(r.stderr + r.stdout)[-800:]}"
    return json.loads(r.stdout.strip().splitlines()[-1])

def read_manifest(out):
    root = WORK / "datasets" / f"ds-{RID}" / out["version"]
    m = json.loads((root / "manifest.json").read_text()); validate("DatasetManifest", m); return m, root

def step2():
    title(2, "문항을 읽어 학습·평가 데이터를 만든다 (synthetic-data run-once를 호스트에서, 문항은 I1 HTTP)")
    out = run_sd("1", seeds=False)
    if out.get("status") == "NOTHING_TO_DO":
        # OPEN_GAPS G02: synthetic-data 의 생성 파이프라인이 아직 v1 내용을 만들어 v2 스키마 검사에서 전부 빠진다(영역의 역할이 정해지기 전). 데이터셋이 게시되지 않는다.
        rep_ = json.loads((WORK / "sd-work-1" / "report.json").read_text())
        assert any("v2 스키마 위반" in n for n in rep_.get("notes", [])) and rep_.get("dropped", {}).get("schema_sample", 0) > 0, f"예상한 G02 상태가 아니다: {rep_}"
        out2 = run_sd("1b", seeds=False); assert out2.get("status") == "NOTHING_TO_DO", f"재실행이 같은 결과가 아니다: {out2}"
        # 이후 단계의 계보(lineage.dataset)에 쓸 자리표시 참조(TEST-SUB): 게시된 데이터셋이 아니다
        STATE["dataset"] = {"id": f"ds-{RID}", "version": "0-test-sub", "content_hash": canonical.sha256_hash({"test-sub": "no dataset published (OPEN_GAPS G02)"})}; save()
        rec(2, "BLOCKED", f"synthetic-data run-once(호스트, 문항은 I1 HTTP)는 돌았으나 데이터셋이 게시되지 않았다(status NOTHING_TO_DO, 합성 샘플 {rep_['dropped']['schema_sample']}건이 v2 스키마 위반으로 제외, 재실행도 같은 결과). 원인은 OPEN_GAPS G02(생성기가 v1 내용을 만든다, 영역 역할 미정)이며 deploy가 고칠 수 없다. 이후 단계의 lineage.dataset 은 자리표시 참조(TEST-SUB)로 대신한다"); return
    assert out.get("status") in ("PUBLISHED", "ALREADY_PUBLISHED"), out
    m, root = read_manifest(out)
    files = {f["path"]: f for f in m["files"]}
    for f in m["files"]:
        assert canonical.file_hash(root / "files" / f["path"]) == f["content_hash"], f"파일 해시 불일치 {f['path']}"
    ids = lambda f: {q["id"] for q in f.get("question_sets", [])}
    unseen = [f for f in m["files"] if QSU in ids(f)]
    assert unseen, "보지 못한 문항 세트 평가 파일이 없다"
    assert all(f["split"] == "EVAL" for f in unseen) and all(QSU not in ids(f) for f in m["files"] if f["split"] in ("TRAIN", "VALIDATION")), "평가용 문항이 학습에 섞였다"
    out2 = run_sd("1b", seeds=False)
    assert out2["status"] == "ALREADY_PUBLISHED" and out2["version"] == out["version"], f"같은 입력 재실행이 같은 결과가 아니다: {out2}"
    STATE["dataset"] = {"id": m["dataset_id"], "version": m["version"], "content_hash": m["content_hash"]}; save()
    rec(2, "REAL", f"synthetic-data run-once(호스트): DatasetManifest {m['dataset_id']}@{m['version']} 스키마·파일 해시 통과, 평가 파일 {len(unseen)}개가 보지 못한 문항 세트({QSU})를 사용, 학습과 겹치지 않음, 재실행은 ALREADY_PUBLISHED(멱등). 생성기는 규칙 기반(LLM 생성은 GPU 서버 몫)")

def make_packages():
    """시험용 어댑터 + model-runtime FakeBackend 적재 + ModelPackageManifest 2건을 만든다."""
    if a.llm_package:
        # 실제 LLM(vllm) 데모: 서빙 설정은 fake 기대값이 아니라 패키지(model-runtime make_neutral_package.py, 태그는 lib.sh 의 DEPLOY_MR_TAG)의 vllm 설정을 쓴다.
        # 서버가 적재할 때 같은 설정인지 스스로 검사한다(ServingConfigMismatch). 여기서는 서버 /v1/info 와 대조해 STATE 에 남기기만 한다(적재 중일 수 있어 실패해도 계속).
        root = pathlib.Path(a.llm_package); gm = {r: json.loads((root / r / "manifest.json").read_text()) for r in ("LORA_A", "LORA_B")}
        adir = {r: root / r / "adapter" for r in gm}
        for r in gm: assert canonical.directory_hash(adir[r]) == gm[r]["adapter_hash"], f"{r} 어댑터 해시가 패키지 매니페스트와 다르다"
        try:
            c, info = http("GET", "ms", "/v1/info", INF_TOK()); ex = info.get("serving_config_expectation") or {}
            sc = gm["LORA_A"]["serving_config"]
            STATE["llm_cfg_vs_server"] = {"backend": info.get("backend"), "constraint_backend": [sc["constraint"].get("backend"), (ex.get("constraint") or {}).get("backend")],
                                          "template_ok": sc["prompt_template_version"] in ex.get("prompt_template_versions", [sc["prompt_template_version"]])}
        except Exception as e:
            STATE["llm_cfg_vs_server"] = "서버 대조 건너뜀(적재 중일 수 있다): " + str(e)[:80]
        d = {"cfgs": {r: gm[r]["serving_config"] for r in gm}, "hashes": {r: gm[r]["serving_config_hash"] for r in gm},
             "adapter_hash": {r: gm[r]["adapter_hash"] for r in gm}, "runtime": gm["LORA_A"]["lineage"]["model_runtime_version"],
             "system_prompt": {r: gm[r]["system_prompt"] for r in gm}}
        for r in gm: assert canonical.file_hash(adir[r] / gm[r]["system_prompt"]["path"]) == gm[r]["system_prompt"]["sha256"], f"{r} 시스템 프롬프트 해시가 패키지와 다르다"
        for r in gm: assert canonical.sha256_hash(d["cfgs"][r]) == d["hashes"][r], f"{r} 서빙 설정 해시가 패키지와 다르다"
    else:
        fx = ROOT / "test/fixtures/e2e-test-adapter"
        # 추론 서버가 알려 주는 기대값(/v1/info의 serving_config_expectation)으로 fake용 serving_config를 만든다
        c, info = http("GET", "ms", "/v1/info", INF_TOK()); assert c == 200, (c, info)
        ex = info["serving_config_expectation"]
        # LORA_A 는 제약 디코딩(ActionExtraction JSON), LORA_B 는 문장이라 제약 없음(model-runtime make_neutral_package.py 와 같은 규칙)
        mkcfg = lambda mode: {"prompt_template_version": ex["prompt_template_version_default"],
               "decoding": {"constraint_mode": mode, "temperature": 0, "retry_temperature": 0.7, "seed": 1000, "max_tokens": 512}, "max_attempts": 3,
               "constraint": ex["constraint"], "output_contract": ex["output_contract"], "protection_policy_version": ex["protection_policy_versions"][-1]}
        cfgs = {"LORA_A": mkcfg("constrained"), "LORA_B": mkcfg("none")}
        # 대조: survey 이미지(model-runtime)의 fake_serving_configs 와 일치하는지
        probe = "import json, model_runtime as m\nprint(json.dumps(m.fake_serving_configs()['LORA_A']))\n"
        try:
            ref = json.loads(docker_py(IMAGES["survey-service"], probe))
            STATE["fake_cfg_vs_survey_image"] = sorted(k for k in cfgs["LORA_A"] if ref.get(k) != cfgs["LORA_A"][k])
        except Exception as e:
            STATE["fake_cfg_vs_survey_image"] = "대조 불가(survey 이미지에 fake_serving_configs 가 없을 수 있다) " + str(e)[-80:]
        sp = {r: {"path": "system_prompt.txt", "sha256": canonical.file_hash(fx / r / "system_prompt.txt")} for r in ("LORA_A", "LORA_B")}
        d = {"cfgs": cfgs, "hashes": {r: canonical.sha256_hash(cfgs[r]) for r in cfgs},
             "adapter_hash": {r: canonical.directory_hash(fx / r) for r in ("LORA_A", "LORA_B")}, "runtime": info["runtime_version"], "system_prompt": sp}
        adir = {r: fx / r for r in ("LORA_A", "LORA_B")}
    pk = {}
    for role in ("LORA_A", "LORA_B"):
        mf = {"pipeline_schema_version": bc.PIPELINE_SCHEMA_VERSION, "package_id": f"pkg-{RID}-{role.lower().replace('_', '-')}", "version": "1", "role": role,
              "created_at": "2026-10-15T00:00:00Z", "runtime_contract_version": 1,
              "base_model": (gm[role]["base_model"] if a.llm_package else {"id": "Qwen/Qwen2.5-1.5B-Instruct", "revision": "main"}),   # 실제 LLM 데모는 패키지(프로파일)의 기반 모델(gpu-12g = Qwen3-1.7B)
              "adapter_hash": d["adapter_hash"][role], "serving_config": d["cfgs"][role], "serving_config_hash": d["hashes"][role],
              "lineage": {"dataset": STATE["dataset"], "training_run_id": f"run-{RID}-1", "turn_engine_version": a.turn_engine_version,
                          "model_runtime_version": d["runtime"], "question_sets": STATE["qs"][-1:]},
              "eval_report_ref": f"eval-{RID}-{role.lower().replace('_', '-')}"}
        mf["system_prompt"] = d["system_prompt"][role]   # 모델 패키지의 일부(D75): 어댑터 디렉터리 안 파일의 {path, sha256}
        if a.llm_package: mf["ext"] = gm[role].get("ext", {})   # 중립(학습하지 않은) 패키지 표시
        mf["content_hash"] = canonical.content_hash(mf); validate("ModelPackageManifest", mf)
        ref = {"id": mf["package_id"], "version": mf["version"], "content_hash": mf["content_hash"]}
        # 시험용 EvaluationReport: 지표 값은 고정된 시험 값이다(실제 평가가 아니다). METRICS.md의 이름을 쓴다
        A = [("risk_signal_recall", "SAFETY", 0.97, True), ("risk_signal_false_alarm", "SAFETY", 0.02, False), ("item_recall", "ACCURACY", 0.91, True),
             ("schema_valid_raw", "PROTECTION", 0.99, True)]
        B = [("forbidden_expression_rate", "SAFETY", 0.0, False), ("risk_notice_verbatim_rate", "SAFETY", 1.0, True), ("slot_coverage", "ACCURACY", 0.95, True),
             ("fallback_rate", "PROTECTION", 0.01, False)]
        rep = {"pipeline_schema_version": bc.PIPELINE_SCHEMA_VERSION, "report_id": mf["eval_report_ref"], "created_at": "2026-10-15T00:00:00Z", "role": role,
               "package": ref, "dataset": STATE["dataset"], "question_sets": STATE["qs"][-1:],
               "evaluation_backend": {"name": "test-fixed-metrics", "version": "1", "constrained_decoding": False}, "decoding": {"temperature": 0, "seed": 1},
               "metrics": [{"name": n, "group": g, "value": v, "n": 40, "higher_is_better": h, "unit": "ratio", "slice": {"kind": "ALL", "value": "ALL"}} for n, g, v, h in (A if role == "LORA_A" else B)],
               "notes": ["TEST: 시험용 고정 지표. 실제 평가가 아니다(E2E 단계 3 대역)"]}
        rep["content_hash"] = canonical.content_hash(rep); validate("EvaluationReport", rep)
        pk[role] = (mf, adir[role], rep)
    return pk

def step3():
    title(3, "설정 하나로 학습·평가·패키징·게시가 돈다 (model-lab, I3) -- 시험 대역")
    if os.environ.get("E2E_GPU") == "1":
        r = subprocess.run(["bash", str(ROOT / "scripts/e2e_gpu.sh"), str(PORTS["mr"]), str(pathlib.Path(a.secrets) / "tokens" / "model-registry-write-model-lab")], capture_output=True, text=True)
        if r.returncode != 0:
            rec(3, "BLOCKED", f"E2E_GPU=1 경로(scripts/e2e_gpu.sh, 미검증) 실패 {r.returncode}: {(r.stderr or r.stdout)[-300:]}. 기본 경로(시험용 어댑터)로 계속하지 않았다"); return
        rec(3, "BLOCKED", "E2E_GPU=1 경로는 게시까지만 있고 이후 단계가 읽을 참조 해석이 미구현(CR-D12)"); return
    pk = make_packages(); reg = HttpModelRegistry(URL("mr"), TOK("model-registry-write-model-lab"))
    refs = {}
    for role, (mf, adir, rep) in pk.items():
        rb = json.dumps(rep, ensure_ascii=False, sort_keys=True).encode()
        got = reg.publish(mf, adir, rb)
        again = reg.publish(mf, adir, rb); assert dict(again) == dict(got), "게시가 멱등이 아니다"
        refs[role] = {"id": mf["package_id"], "version": mf["version"], "content_hash": mf["content_hash"]}
    rr = HttpModelRegistry(URL("mr"), TOK("model-registry-read-release-gate"))
    for role, (mf, adir, rep) in pk.items():
        g = rr.get_manifest(mf["package_id"], "1"); validate("ModelPackageManifest", g); assert g["content_hash"] == mf["content_hash"]
        got_rep = json.loads(rr.get_eval_report(g["eval_report_ref"])); validate("EvaluationReport", got_rep); assert got_rep["content_hash"] == rep["content_hash"] == canonical.content_hash({k: v for k, v in got_rep.items()})
        dest = WORK / f"adapter-{role}"; p = rr.open_adapter(mf["package_id"], "1", dest=dest)   # 해시 검증 포함
        assert canonical.directory_hash(p) == mf["adapter_hash"]
    try:
        reg_ro = HttpModelRegistry(URL("mr"), TOK("model-registry-read-release-gate")); reg_ro.publish(pk["LORA_A"][0], pk["LORA_A"][1], b"{}"); raise AssertionError("읽기 토큰으로 게시됨")
    except bc.BoundaryError as e: assert e.code == "PERMISSION_DENIED"
    STATE["lora"] = refs; STATE["system_prompt"] = {r: pk[r][0]["system_prompt"]["sha256"] for r in pk}; save()
    src_desc = ("학습하지 않은 중립 LoRA(model-runtime make_neutral_package.py + 학습 데이터 system 메시지 프롬프트, vllm 서빙 설정, lora_B=0이라 출력은 기반 모델과 같다)" if a.llm_package
                else "시험용 어댑터(test/fixtures/e2e-test-adapter, PEFT 형식 r=16, 기반 모델 Qwen/Qwen2.5-1.5B-Instruct; fake 백엔드는 기반 모델을 적재하지 않는다)")
    rec(3, "TEST-SUB", f"학습 대신 {src_desc}와 시험용 EvaluationReport(METRICS.md 이름의 고정 지표, 실제 평가 아님)를 model-registry에 HTTP로 게시. serving_config는 추론 서버 /v1/info의 serving_config_expectation으로 만들었다(survey 이미지 fake_serving_configs와 다른 키: {STATE.get('fake_cfg_vs_survey_image')}). 게시(REAL): 멱등, 읽기 토큰 게시 거부, 읽기로 매니페스트·어댑터 해시 검증 통과. 계보의 dataset은 단계 2가 게시한 실제 데이터셋(단계 2가 BLOCKED이면 자리표시 참조, TEST-SUB). 시스템 프롬프트는 어댑터 디렉터리의 system_prompt.txt와 ModelPackageManifest.system_prompt(path, sha256)로 패키지에 들어 있다(시험용 자리표시 문장). model-lab 파이프라인·패키징 코드는 실행하지 않음(이웃 코드를 가져오지 않는다)")

def decisions_for(gate_read, subj):
    return gate_read.find_decisions(question_set=subj["question_set"], lora_a=subj["lora_a"], lora_b=subj["lora_b"])[0]

ADMIN = lambda: ("trainer-e2e", TOK("admin-console-password"))
REVIEWER = lambda: ("reviewer-e2e", TOK("reviewer-console-password"))   # 실패 사례 검토 화면 계정(역할 reviewer)   # 승인 화면 기본 인증 시험 계정(운영 인증 방식은 미정)

def gw_raw(method, path, body=None, basic=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL("gw") + path, data=data, method=method)
    if basic: req.add_header("Authorization", "Basic " + __import__("base64").b64encode(f"{basic[0]}:{basic[1]}".encode()).decode())
    if data is not None: req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items(): req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, json.loads(r.read() or b"null"), dict(r.headers)
    except urllib.error.HTTPError as e:
        b = e.read()
        try: return e.code, json.loads(b), dict(e.headers)
        except Exception: return e.code, b.decode(errors="replace"), dict(e.headers)

def reject_via_gateway(sid):
    """승인 화면이 하는 경로를 게이트웨이를 거쳐 한 번 탄다: 목록(AWAITING_APPROVAL) -> review-report(헤더 해시) -> POST approvals(그 해시)."""
    c, _, _ = gw_raw("GET", "/v1/submissions?status=AWAITING_APPROVAL"); assert c == 401, f"인증 없이 /v1/submissions 가 열려 있다 {c}"
    assert gw_text("/admin/")[0] == 401, "인증 없이 /admin/ 이 열려 있다"
    c, page, _ = gw_raw("GET", "/v1/submissions?status=AWAITING_APPROVAL", basic=ADMIN()); assert c == 200, (c, page)
    assert any(x.get("submission_id") == sid for x in page["items"]), "대기 목록에 제출이 없다"
    c, one, _ = gw_raw("GET", f"/v1/submissions/{sid}", basic=ADMIN()); assert c == 200, (c, one)
    c, rep, hd = gw_raw("GET", f"/v1/submissions/{sid}/review-report", basic=ADMIN()); assert c == 200, (c, rep)
    h = {k.lower(): v for k, v in hd.items()}
    rh = h.get("x-openit-report-hash"); assert rh and rh.startswith("sha256:"), f"X-Openit-Report-Hash 헤더가 게이트웨이를 통과하지 않았다: {hd}"
    assert "no-store" in h.get("cache-control", ""), f"Cache-Control: no-store 가 유지되지 않았다: {h.get('cache-control')}"
    # 클라이언트가 보낸 X-Openit-User 와 본문 approver_id 는 무시되고 인증된 계정이 기록된다
    body = {"pipeline_schema_version": bc.PIPELINE_SCHEMA_VERSION, "submission_id": sid, "decision": "REJECT", "approver_id": "body-claimed-id",
            "approver_role": "release-approver", "reason": "시험: 게이트웨이 경유 반려", "report_hash": rh}
    c, ap_, _ = gw_raw("POST", "/v1/approvals", body, basic=ADMIN(), headers={"X-Openit-User": "spoofed-user"})
    assert c == 201, (c, ap_)
    ap_ = ap_.get("approval", ap_) if isinstance(ap_, dict) else ap_   # 응답은 {"approval": GateApproval, ...} 로 한 겹 싸여 있을 수 있다
    assert ap_["approver_id"] == ADMIN()[0], f"승인자 ID가 인증된 계정이 아니다: {ap_['approver_id']}"
    # 열지 않을 경로
    for m, pth in (("POST", "/v1/activate"), ("POST", "/v1/rollback"), ("POST", "/v1/submissions"), ("GET", "/v1/releases"), ("GET", "/v1/decisions")):
        cc = gw_raw(m, pth, {} if m == "POST" else None, basic=ADMIN())[0]; assert cc in (404, 403), f"{m} {pth} 가 게이트웨이에서 열려 있다 {cc}"
    c2, body2, hd2 = gw_text("/admin/", ADMIN()); assert c2 == 200 and "app.js" in body2, (c2, body2[:100])
    assert gw_text("/admin/app.js", ADMIN())[0] == 200
    STATE["admin_gateway"] = {"approver": ap_["approver_id"], "report_hash": rh}; save()
    rec("4g", "REAL", f"승인 화면 경로를 게이트웨이 경유로 한 번 탔다: 인증 없이 /admin/·/v1/submissions 401, 기본 인증(시험 계정 {ADMIN()[0]}) 뒤 목록(AWAITING_APPROVAL)·제출 조회·review-report(X-Openit-Report-Hash 헤더 통과, Cache-Control no-store 유지)·POST /v1/approvals(헤더 해시 사용) 201, 승인 기록의 approver_id가 인증 계정으로 찍힘(클라이언트가 보낸 X-Openit-User·본문 approver_id는 무시), /v1/activate·rollback·POST submissions·releases 는 게이트웨이에서 404. 화면 렌더링은 BLOCKED")
    rec("4x", "BLOCKED", "승인 화면(/admin/)의 브라우저 렌더링·조작은 E2E에서 볼 수 없다. /config.json 은 절대 경로라 /admin/ 아래에서는 kiosk-frontend로 가서 404가 된다(화면은 없는 것으로 처리하므로 영향 없음, admin-console CR-003 후보)")
    return ap_

def step4():
    title(4, "후보 수집기가 새 조합을 찾아 자동 검사하고, 사람 승인으로 릴리스·번들을 만든다 (release-gate, D53)")
    if "lora" not in STATE: rec(4, "BLOCKED", "단계 3의 패키지가 없다"); return
    print("  !! 승인자는 사람이 아니라 이 스크립트가 시험용 release-approver 토큰으로 대신한다(TEST-SUB). 시험용 정책·실행기는 없다 !!")
    r = subprocess.run(["bash", str(ROOT / "scripts/run-job.sh"), "job-release-gate-collect"], capture_output=True, text=True)
    assert r.returncode in (0, 75), f"collect 종료 {r.returncode}: {(r.stderr + r.stdout)[-500:]}"
    collected = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    gate_r = HttpReleaseReader(URL("gate"), TOK("gate-read-survey-service")); gate_op = HttpGateService(URL("gate"), TOK("gate-write-operator"))
    gate_rep = HttpGateService(URL("gate"), TOK("gate-read-ops-feedback")); gate_ap = HttpGateService(URL("gate"), TOK("gate-write-release-approver"))
    A, B = STATE["lora"]["LORA_A"], STATE["lora"]["LORA_B"]
    subj = {v["version"]: {"question_set": v, "lora_a": A, "lora_b": B} for v in STATE["qs"]}
    subj_u = {"question_set": STATE["qsu"], "lora_a": A, "lora_b": B}
    subs = {k: dict(gate_op.submit_candidate(sj, requested_by_role="operator")) for k, sj in subj.items()}
    sub_u = dict(gate_op.submit_candidate(subj_u, requested_by_role="operator"))
    for x in list(subs.values()) + [sub_u]: validate("GateSubmission", x)
    assert subs["1"]["submission_id"] == dict(gate_op.submit_candidate(subj["1"], requested_by_role="operator"))["submission_id"], "같은 조합이 같은 접수가 아니다"
    STATE["subs"] = {"by_version": subs, "unseen": sub_u}; save()
    rec("4a", "REAL", f"수집기 run-once(컨테이너): {collected[:100]}; 후보 접수 3건(GateSubmission 스키마 통과, 같은 조합은 같은 접수)")
    def report_of(sid):
        try: return dict(gate_rep.get_review_report(sid))
        except bc.BoundaryError: return None
    reps = {}
    for k, sub in list(subs.items()) + [("u", sub_u)]:
        reps[k] = wait_review_report(report_of, sub["submission_id"], k)
        validate("ReviewReport", reps[k])
    assert all(c["result"] in ("PASS", "SKIPPED") for c in reps["1"]["checks"]), reps["1"]["checks"]
    # 승인 전에는 PASS가 없다
    for k, sj in list(subj.items()) + [("u", subj_u)]:
        assert not any(d["result"] == "PASS" for d in decisions_for(gate_r, sj)), f"승인 전에 PASS 판정이 있다 {k}"
    rd = json.loads(urllib.request.urlopen(URL("gate") + "/readyz", timeout=10).read()); assert rd.get("awaiting_approval", 0) >= 3, rd
    # 권한: 승인은 release-approver만
    try: gate_op.decide(subs["1"]["submission_id"], "APPROVE", approver_id="op-test", approver_role="release-approver", reason="시험"); raise AssertionError("operator가 승인함")
    except bc.BoundaryError as e: assert e.code == "PERMISSION_DENIED", e.code
    try: gate_ap.decide(subs["1"]["submission_id"], "APPROVE", approver_id="trainer-test", approver_role="release-approver", reason="시험", report_hash="sha256:" + "0" * 64); raise AssertionError("낡은 보고서 해시로 승인됨")
    except bc.BoundaryError as e: assert e.code == "CONFLICT", e.code
    # 반려(REJECT) -> FAIL 판정
    ru = reject_via_gateway(sub_u["submission_id"]); validate("GateApproval", ru)
    du = wait(lambda: next(iter(decisions_for(gate_r, subj_u)), None), 30, "반려 판정"); validate("GateDecision", dict(du))
    hu = [c for c in du["checks"] if c["kind"] == "HUMAN_APPROVAL"]
    assert du["result"] == "REJECT" and hu and hu[0]["result"] == "FAIL" and "CHECK_FAILED" in du["reject_codes"], dict(du)
    # 승인(APPROVE) 멱등, 다른 결정 충돌
    sid1 = subs["1"]["submission_id"]
    a1 = dict(gate_ap.decide(sid1, "APPROVE", approver_id="trainer-test", approver_role="release-approver", reason="시험: 지표 검토함")); validate("GateApproval", a1)
    a1b = dict(gate_ap.decide(sid1, "APPROVE", approver_id="trainer-test", approver_role="release-approver", reason="시험: 지표 검토함"))
    assert a1b == a1, "같은 결정 재전송이 같은 결과가 아니다"
    try: gate_ap.decide(sid1, "REJECT", approver_id="trainer-test", approver_role="release-approver", reason="번복"); raise AssertionError("다른 결정이 받아들여짐")
    except bc.BoundaryError as e: assert e.code == "CONFLICT", e.code
    d1 = wait(lambda: next((d for d in decisions_for(gate_r, subj["1"]) if d["result"] == "PASS"), None), 30, "승인 뒤 PASS 판정")
    validate("GateDecision", dict(d1)); assert any(c["kind"] == "HUMAN_APPROVAL" and c["result"] == "PASS" for c in d1["checks"])
    rid1 = d1.get("release_id"); rel1 = dict(gate_r.get_release(rid1)); validate("ReleaseManifest", rel1); assert canonical.content_hash(rel1) == rel1["content_hash"]
    bd = WORK / "bundles"; gate_r.load_bundle(rid1, dest=bd)
    ap1 = dict(gate_op.activate(rid1, requested_by_role="operator")); validate("ActivePointer", ap1)
    # 둘째 후보: 활성 릴리스와 같은 지표끼리 맞댄 보고서(comparisons), 활성화로 보고서가 바뀌면 이전 해시는 낡은 것
    rep2 = report_of(subs["2"]["submission_id"]); validate("ReviewReport", rep2)
    assert rep2["comparisons"], "활성 릴리스와의 비교가 비어 있다"
    sid2 = subs["2"]["submission_id"]
    a2 = dict(gate_ap.decide(sid2, "APPROVE", approver_id="trainer-test", approver_role="release-approver", reason="시험: 둘째 후보 검토함")); validate("GateApproval", a2)
    d2 = wait(lambda: next((d for d in decisions_for(gate_r, subj["2"]) if d["result"] == "PASS"), None), 30, "둘째 PASS 판정"); validate("GateDecision", dict(d2))
    rid2 = d2.get("release_id"); rel2 = dict(gate_r.get_release(rid2)); validate("ReleaseManifest", rel2); gate_r.load_bundle(rid2, dest=bd)
    ap2 = dict(gate_op.activate(rid2, requested_by_role="operator")); validate("ActivePointer", ap2); assert ap2["pointer_version"] > ap1["pointer_version"]
    try: gate_op.activate(du.get("release_id") or "rel-none-x", requested_by_role="operator"); raise AssertionError("PASS가 아닌 릴리스가 활성화됨")
    except bc.BoundaryError as e: assert e.code in ("NOT_FOUND", "FAILED_PRECONDITION"), e.code
    STATE["releases"] = {"1": rid1, "2": rid2}; STATE["pointers"] = [ap1, ap2]; save()
    rec("4b", "TEST-SUB", f"승인자를 스크립트가 대신한다(TEST-SUB). REAL: 자동 검사 통과 후 승인 요청 보고서(ReviewReport, 활성 릴리스와 비교), 승인 전 PASS 없음, operator의 승인 403, 낡은 report_hash 409, REJECT -> REJECT 판정(HUMAN_APPROVAL FAIL, CHECK_FAILED), APPROVE 재전송 멱등·번복 409, 승인 뒤 PASS(HUMAN_APPROVAL PASS)·ReleaseManifest(해시)·번들(해시)·활성화 x2(포인터 {ap1['pointer_version']}->{ap2['pointer_version']})")

def survey_ready():
    c, r = http("GET", "survey", "/readyz"); return c, r

def kiosk(path, body):
    # 브라우저처럼 토큰 없이 같은 출처로 부른다: 게이트웨이가 kiosk 역할 토큰을 붙인다
    return http("POST", "gw", path, None, body)

STAFF = lambda: ("staff", TOK("staff-console-password"))   # 직원 콘솔 기본 인증(개발/E2E용)
def state_of(sid):
    """GET /v1/sessions/{id}/state. 서버가 0.5초보다 잦은 조회를 429(UNAVAILABLE)로 막으므로 간격을 두고 재시도한다(키오스크는 2초 간격 폴링)."""
    for _ in range(8):
        time.sleep(0.7)
        c, r = http("GET", "gw", f"/v1/sessions/{sid}/state")
        if c != 429: return c, r
    return c, r

def gws(method, path, body=None):
    return http(method, "gw", path, None, body, basic=STAFF())

def gw_text(path, basic=None):
    req = urllib.request.Request(URL("gw") + path)
    if basic: req.add_header("Authorization", "Basic " + __import__("base64").b64encode(f"{basic[0]}:{basic[1]}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return r.status, r.read().decode(errors="replace"), dict(r.headers)
    except urllib.error.HTTPError as e: return e.code, e.read().decode(errors="replace"), dict(e.headers)

def public_turn(sid, tid, text):
    c, r = kiosk(f"/v1/sessions/{sid}/turns", {"session_id": sid, "kind": "UTTERANCE", "utterance": text, "turn_id": tid}); return c, r

def ms_call(path, body, token):
    """추론 서버 직접 호출(v2): (상태, 본문 문자열, 소문자 헤더). 서비스를 거치지 않고 extract(JSON)·respond(text)의 계약을 확인하려는 것."""
    req = urllib.request.Request(URL("ms") + path, data=json.dumps(body, ensure_ascii=False).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {token}"); req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, r.read().decode(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e: return e.code, e.read().decode(errors="replace"), {k.lower(): v for k, v in e.headers.items()}

# 가짜 백엔드의 출력(표준 서버 + MODEL_RUNTIME_FAKE_FLOW_FILE=test/fake-model/question_flow.json): A 는 입력 문항의 다음 문항으로 가는 유효한 ActionExtraction(값 없음), B 는 문장.
# FLOW_FILE 이 없으면 기본 고정 출력(next_item=END)은 첫 문항에서도 END 라 서비스의 검증(validate_extraction)이 모든 턴을 반려한다. 문항 순서 사본이 survey-service 와 다르면 여기서 실패한다.
FAKE_EXTRACTION = {"action": "NEXT", "next_item": "Q1.D04", "values": []}   # 아래 직접 호출의 입력 question_id 가 Q1.D03 이다
FAKE_RESPONSE_TEXT = "(가짜 응답)"

def model_server_v2_check(new, tok):
    """PUT 적재(서비스가 이미 함) 뒤 extract(JSON) -> respond(text) 를 직접 한 번씩 부른다."""
    ein = {"question_id": "Q1.D03", "current_question": "다음은 고혈압입니다. 진단받은 적이 있으신지, 지금 약을 드시는지 알려 주세요.", "user_utterance": "십 년 전에 고혈압 진단을 받았어요.",
           "state": {"Q1.D02.diagnosed": {"value": False, "status": "ANSWERED"}}}
    validate("ActionExtractionInput", ein)
    c, body, h = ms_call(f"/v1/releases/{new}/extract", ein, tok); assert c == 200, (c, body[:200])
    out = json.loads(body); validate("ActionExtraction", out); assert out == FAKE_EXTRACTION, out
    assert h.get("content-type", "").startswith("application/json") and h.get("x-openit-outcome") == "ok", h
    rin = {"action": "START", "topic": "고혈압 진단과 복약", "next": {"type": "NEXT", "question_id": "Q1.D01", "text": "혹시 고혈압으로 진단받으셨나요?"}}
    validate("ResponseRequest", rin)
    c, body, h = ms_call(f"/v1/releases/{new}/respond", rin, tok); assert c == 200, (c, body[:200])
    assert body == FAKE_RESPONSE_TEXT and h.get("content-type", "").startswith("text/plain") and h.get("x-openit-outcome") == "ok", (body[:80], h)
    c, bad, _ = ms_call(f"/v1/releases/{new}/extract", {"question_id": "Q1"}, tok); assert c == 400, ("계약 위반 입력이 400이 아니다", c, bad[:100])
    c, nf, _ = ms_call("/v1/releases/rel-none-x/extract", ein, tok); assert c == 404, ("적재되지 않은 릴리스가 404가 아니다", c)
    c, info = http("GET", "ms", "/v1/info", tok)
    assert info.get("system_prompt_sha256") == STATE.get("system_prompt"), f"서버가 쓰는 시스템 프롬프트 해시가 패키지와 다르다: {info.get('system_prompt_sha256')} / {STATE.get('system_prompt')}"
    return "extract(JSON, ActionExtraction 스키마, X-Openit-Outcome ok) -> respond(text/plain 문장, ok), 계약 위반 입력 400, 미적재 릴리스 404, /v1/info 의 system_prompt_sha256 이 패키지(ModelPackageManifest.system_prompt)와 일치"

def step5():
    title(5, "서비스가 새 포인터를 보고 새 세션부터 새 릴리스로 한 턴 이상을 처리한다 (공개 API, 게이트웨이 경유)")
    if "pointers" not in STATE: rec(5, "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    new = STATE["releases"]["2"]
    r = wait(lambda: (lambda cr: cr[1] if cr[0] == 200 and cr[1].get("active_release") == new else None)(survey_ready()), 60, f"survey가 릴리스 {new} 적재")
    assert r["ready"] and not r["release_loader"]["rejections"], r
    sid = f"sess-{RID}-a"
    assert http("POST", "survey", "/v1/sessions", None, {"session_id": sid, "kind": "SESSION_START"})[0] == 401, "survey-service가 토큰 없는 요청을 받아들임"
    c, st = kiosk("/v1/sessions", {"session_id": sid, "kind": "SESSION_START"}); assert c == 200, (c, st)
    validate_survey("FrontendInput", st); assert st["response_text"], st
    c, t1 = public_turn(sid, "turn-1", "뇌졸중은 없고 약도 안 먹어요"); assert c == 200, (c, t1); validate_survey("FrontendInput", t1)
    c, t1b = public_turn(sid, "turn-1", "뇌졸중은 없고 약도 안 먹어요"); assert c == 200 and t1b == t1, "같은 turn_id 재시도가 같은 응답이 아니다"
    c, t2 = public_turn(sid, "turn-2", "약도 안 먹어요"); assert c == 200, (c, t2)
    # 한 턴이 추론 서버(model-serving)를 거쳤다: 서버의 가짜 백엔드는 출력이 고정이라 생성기 문장이 "(가짜 응답)" 이다
    texts = " ".join(str(x.get("response_text")) for x in (t1, t2))
    assert "(가짜 응답)" in texts, f"model-serving의 고정 출력이 아니다(서비스 내부 가짜?): {texts[:200]}"
    ms_tok = INF_TOK()
    c, info = http("GET", "ms", "/v1/info", ms_tok); assert c == 200 and new in info.get("loaded", []), (c, info)
    assert info["backend"] == "fake", info
    assert http("GET", "ms", "/v1/info", None)[0] in (401, 403), "토큰 없이 추론 서버 /v1/가 열림"
    c, st_ = http("GET", "ms", f"/v1/releases/{new}", ms_tok); assert c == 200 and st_["state"] == "LOADED", (c, st_)
    v2chk = model_server_v2_check(new, ms_tok)
    rd = survey_ready()[1]; inf = rd.get("inference") or {}
    if not a.skip_ms_restart:
        # 추론 서버를 멈췄다 다시 띄운다: 그 턴만 실패하고 서비스는 산다, 다시 띄우면 복구(404 -> PUT 재적재)
        mname = MS_CONTAINER
        sidc = f"sess-{RID}-c"; assert kiosk("/v1/sessions", {"session_id": sidc, "kind": "SESSION_START"})[0] == 200
        sh([a.docker, "stop", "-t", "3", mname])
        try:
            cd_, rd_ = public_turn(sidc, "turn-down", "뇌졸중은 없고 약도 안 먹어요")
            failed = cd_ != 200 or (isinstance(rd_, dict) and rd_.get("turn_failure_signal"))
            assert failed, f"추론 서버가 멈췄는데 턴이 성공했다: {cd_} {rd_}"
            assert http("GET", "survey", "/healthz")[0] == 200, "추론 서버 중단으로 서비스가 죽었다"
        finally:
            sh([a.docker, "start", mname])
        wait(lambda: sh([a.docker, "inspect", "-f", "{{.State.Health.Status}}", mname]).stdout.strip() == "healthy", 60, "추론 서버 복구")
        cu, ru = public_turn(sidc, "turn-up", "뇌졸중은 없고 약도 안 먹어요")
        assert cu == 200 and not (isinstance(ru, dict) and ru.get("turn_failure_signal")) and "(가짜 응답)" in str(ru.get("response_text")), (cu, ru)
        kiosk(f"/v1/sessions/{sidc}/end", {"session_id": sidc, "kind": "SESSION_END"})
    assert kiosk(f"/v1/sessions/{sid}/intervention", {"session_id": sid, "decision": "RESUME", "turn_id": "x"})[0] == 401, "직원 개입이 인증 없이 열려 있다"
    # 직원 개입은 서비스에 직접(내부 경로)만: 키오스크 토큰은 403, 직원 토큰은 멈추지 않은 세션에 409(PUBLIC_API.md)
    ib = {"session_id": sid, "decision": "RESUME", "turn_id": "i1"}
    assert http("POST", "survey", f"/v1/sessions/{sid}/intervention", TOK("survey-api-kiosk"), ib)[0] == 403, "키오스크 토큰으로 직원 개입이 열림"
    assert http("POST", "survey", f"/v1/sessions/{sid}/intervention", TOK("survey-api-staff"), ib)[0] == 409, "멈추지 않은 세션의 개입이 409가 아님"
    assert http("GET", "gw", f"/v1/sessions/{sid}/turns", TOK("survey-api-kiosk"))[0] in (404, 405)
    c, en = kiosk(f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"}); assert c == 200, (c, en); validate_survey("FrontendInput", en)
    # 서비스가 턴마다 Trace를 I6로 보냈는지(outbox 전송 수)
    sent = wait(lambda: (lambda cr: cr[1]["trace_outbox"]["sent"] if cr[1]["trace_outbox"]["sent"] >= 2 else None)(survey_ready()), 30, "Trace 전송")
    STATE["sess_a"] = sid; save()
    rec(5, "REAL", f"게이트웨이 경유 공개 API(Bearer 토큰, 없으면 401): 세션 시작·발화 2턴·종료, 응답 FrontendInput 스키마 통과, 같은 turn_id 재시도는 같은 응답, 게이트웨이는 토큰 없이 부른 키오스크 요청에 kiosk 토큰을 붙이고(survey 직접 호출은 토큰 없으면 401), 직원 개입은 인증 없으면 401, survey에서 키오스크 토큰은 403·직원 토큰은 멈추지 않은 세션에 409. 실제 survey-service가 게이트 포인터를 HTTP로 폴링해 릴리스 {new} 적재(번들 해시 검증)하고 턴마다 Trace를 I6로 전송(outbox sent={sent}). 한 턴이 model-serving 컨테이너(I9 v2: 서비스 -> PUT 적재 -> extract(JSON) -> respond(text))를 거쳤다(고정 출력 '(가짜 응답)' 확인, /v1/info loaded, 토큰 없으면 거부). 서버 직접 호출: {v2chk}. 추론 서버를 멈추면 그 턴만 실패하고 서비스는 살아 있으며 다시 띄우면 다음 턴이 복구된다. 모델은 fake 백엔드와 시험용 번들(TEST-SUB)")

def step5f():
    title("5f", "프론트 이미지와 게이트웨이: 정적 화면, 공개 API 호출 순서, 직원 경로 권한 분리, 직원 알림 입력원 없음 (kiosk-frontend)")
    if "pointers" not in STATE: rec("5f", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    # (a) 정적 화면
    c, html, _ = gw_text("/"); assert c == 200 and "문진" in html, (c, html[:100])
    assert gw_text("/staff/")[0] == 401, "직원 콘솔이 인증 없이 열려 있다"
    assert gw_text("/staff/", ("staff", "wrong"))[0] == 401
    c, stf, _ = gw_text("/staff/", STAFF()); assert c == 200 and "직원 콘솔" in stf, (c, stf[:100])
    c, sw, h = gw_text("/staff/sw.js", STAFF()); assert c == 200, c
    assert gw_text("/healthz")[0] == 200
    c, _t, hd = gw_text("/"); assert "default-src 'self'" in " ".join(f"{v}" for k, v in hd.items() if k.lower() == "content-security-policy"), "CSP 헤더가 없다"
    assert gw_text("/v1/turns")[0] == 404
    rec("5a", "REAL", "게이트웨이 경유 kiosk-frontend: /(키오스크 화면) 200, /staff/ 는 인증 없이·틀린 암호로 401, 기본 인증으로 200, /staff/sw.js 200, CSP 헤더, /v1 기타 경로 404")
    # (b) 브라우저가 부르는 순서를 HTTP로(토큰 없이 같은 출처): 세션 시작, 발화 2턴, state 조회, 종료
    sf = f"sess-{RID}-fe"
    c, st = kiosk("/v1/sessions", {"session_id": sf, "kind": "SESSION_START"}); assert c == 200, (c, st); validate_survey("FrontendInput", st)
    for i, text in enumerate(("뇌졸중은 없고 약도 안 먹어요", "약도 안 먹어요"), 1):
        c, tr = public_turn(sf, f"fe-{i}", text); assert c == 200, (c, tr); validate_survey("FrontendInput", tr)
    c, state = state_of(sf); assert c == 200, (c, state); validate("SessionState", state)
    assert state["state"] == "ACTIVE", state
    c, en = kiosk(f"/v1/sessions/{sf}/end", {"session_id": sf, "kind": "SESSION_END"}); assert c == 200, (c, en)
    rec("5b", "REAL", "프론트의 공개 API 호출 순서가 게이트웨이(같은 출처, 토큰 없이)를 거쳐 실제 survey-service에 통과: 세션 시작 -> 발화 2턴 -> state(SessionState 스키마, ACTIVE) -> 종료")
    # (c) 직원 경로 권한 분리
    c1 = http("GET", "gw", "/v1/staff/alerts", None)[0]; assert c1 in (401, 403), c1
    c2 = http("GET", "survey", "/v1/staff/alerts", TOK("survey-api-kiosk"))[0]; assert c2 == 403, f"키오스크 토큰으로 직원 API가 열림 {c2}"
    c3 = http("GET", "gw", "/v1/staff/alerts", TOK("survey-api-kiosk"))[0]; assert c3 in (401, 403), c3   # 클라이언트가 보낸 Authorization은 게이트웨이가 바꾸지 못한 채 인증 없이 거부된다
    c, pg = gws("GET", "/v1/staff/alerts?status=OPEN"); assert c == 200, (c, pg); validate("StaffAlertPage", pg)
    rec("5c", "REAL", f"권한 분리: 인증 없는 키오스크 쪽 호출은 게이트웨이에서 {c1}(직원 API는 기본 인증 필요), survey에 키오스크 토큰으로 직접 부르면 403, 기본 인증 뒤에는 staff 토큰이 붙어 목록 200(StaffAlertPage 스키마). 인증 없는 호출이 403이 아니라 401인 것은 브라우저가 인증 창을 띄우게 하려는 선택이다")
    # (d) 직원 알림의 입력원이 없다(OPEN_GAPS G01, D78/D79): 알림이 *나오지 않는 것*과 /readyz 의 staff_alert_source.active=false 를 확인한다.
    c, rz = survey_ready(); sas = rz.get("staff_alert_source"); assert isinstance(sas, dict) and sas.get("active") is False, f"/readyz 의 staff_alert_source 가 active=false 가 아니다: {sas}"
    s0 = f"sess-{RID}-nors"; assert kiosk("/v1/sessions", {"session_id": s0, "kind": "SESSION_START"})[0] == 200
    for i, text in enumerate(("숨이 안 쉬어져요", "가슴이 너무 아파요"), 1):   # v1 이었다면 위험으로 멈췄을 발화(시험 자료). 입력원이 없으므로 멈추지 않아야 한다
        c, rr = public_turn(s0, f"nr{i}", text); assert c == 200, (c, rr); validate_survey("FrontendInput", rr)
        assert not (rr.get("turn_failure_signal") or {}).get("staff_alert") in ("DELIVERED", "DELIVERY_FAILED"), f"입력원이 없는데 직원 알림이 나왔다: {rr}"
    c, stn = state_of(s0); validate("SessionState", stn); assert stn["state"] == "ACTIVE", ("입력원이 없는데 세션이 멈췄다", stn)
    c, pg0 = gws("GET", "/v1/staff/alerts?status=OPEN"); validate("StaffAlertPage", pg0)
    assert not [x for x in pg0["items"] if x["session_id"] == s0], "입력원이 없는데 알림 목록에 이 세션의 알림이 있다"
    assert kiosk(f"/v1/sessions/{s0}/end", {"session_id": s0, "kind": "SESSION_END"})[0] == 200
    rec("5d", "REAL", "직원 알림 입력원 없음(G01): /readyz staff_alert_source.active=false, v1 이었다면 위험 정지였을 발화 2건에도 세션은 ACTIVE로 이어지고 알림 목록(OPEN)에 이 세션의 알림이 없으며 전달 실패 신호도 없다. 이것은 '알림이 동작한다'는 뜻이 아니라 알림이 일부러 비어 있다는 확인이다")
    rec("5d-skip", "SKIPPED", "직원 콘솔 알림 화면 시험(알림 OPEN, SSE alert/resolved, 직원 RESUME/END, 정지 중 발화 무응답)은 건너뛴다. 이유: 알림을 만들려면 survey-service 의 시험용 입력원(SURVEY_RISK_SOURCE=tests.smoke_fakes:risk_source)이 필요한데, 그 코드는 survey-service 리포의 tests/ 에만 있고 이미지에 없다(스모크가 tests/ 를 읽기 전용으로 붙임). 다른 영역 리포의 시험 코드를 이 시험 구성에 끌어와 결합하는 것은 하지 않았고 운영 설정에 넣지도 않는다. 직원 개입의 권한 분리(키오스크 403, 직원 토큰 409)는 단계 5에서 REAL 로 본다")
    rec("5x", "BLOCKED", "실제 브라우저에서의 화면 동작, STT(Web Speech API), 웹 푸시 수신은 E2E에서 볼 수 없다(보안 출처 HTTPS·VAPID 키 필요, 푸시는 VAPID 없이 비활성: SSE만 확인). 운영 TLS·직원 콘솔 인증 방식은 미정")

def trace_env(release_id, n):
    keys = list(survey_schema.load_schema("TurnTrace")["$defs"]["TurnTrace"].get("required") or [])
    t = {k: None for k in keys}
    t.update(session_id=f"s-{RID}", turn_id=f"t-{RID}-{n}", contract_version=1)
    # v2 TurnTrace(D74): 모델 입력은 ActionExtractionInput 그대로(extract_input). 추출이 형식을 못 지킨 턴(OUTPUT_INVALID)을 시험 자료로 만든다
    t["extract_input"] = {"question_id": "Q1.D01", "current_question": "시험 문항 Q1.D01입니다. 알려 주세요.", "user_utterance": "뇌졸중은 없고 약도 안 먹어요", "state": {}}
    validate("ActionExtractionInput", t["extract_input"])
    t["extract_output"] = None; t["extract_status"] = "OUTPUT_INVALID"; t["extract_attempts"] = 2
    STATE["extract_input"] = t["extract_input"]
    t["orchestrator_output"] = {"turn_kind": None, "session_info_created": None, "log_entry": None, "dispatch_called": False,
        "turn_failure_signal": {"session_id": f"s-{RID}", "write_committed": "NOT_COMMITTED", "staff_alert": "NONE"}, "intervention_result": None}
    e = {"pipeline_schema_version": bc.PIPELINE_SCHEMA_VERSION, "release_id": release_id, "runtime_contract_version": 1,
         "session_id": f"s-{RID}", "turn_id": f"t-{RID}-{n}", "sent_at": "2026-10-15T00:00:00Z", "trace": t}
    validate("TraceEnvelope", e); validate_survey("TurnTrace", t); return e

def step6():
    title(6, "Trace를 수집·비식별해 실패 사례를 만든다 (ops-feedback, I6->I7)")
    rel = (STATE.get("releases") or {}).get(STATE["qs"][-1]["version"], f"rel-{RID}-none")
    ing = HttpTraceIngest(URL("ops"), TOK("ops-ingest-survey-service"))
    env = trace_env(rel, 1); STATE["trace_env"] = env; save(); r1 = ing.send(env); r2 = ing.send(env)
    assert (r1["status"], r2["status"]) == ("ACCEPTED", "DUPLICATE"), (r1, r2)
    validate("IngestResult", dict(r1)); validate("IngestResult", dict(r2))
    assert http("POST", "ops", "/v1/traces", None, env)[0] == 403
    c, e4 = http("POST", "ops", "/v1/traces", TOK("ops-ingest-survey-service"), {**env, "trace": {"x": 1}}); assert c == 400; validate("BoundaryError", e4)
    rec("6a", "TEST-SUB", f"실패 신호가 든 봉투는 e2e가 만든 시험 자료(공개 API의 정상 턴으로는 실패 사례가 생기지 않음; 정상 턴의 Trace 전송은 단계 5에서 REAL로 확인; release_id는 단계 4의 실제 릴리스). 수집 REAL: HttpTraceIngest ACCEPTED→DUPLICATE, 토큰 없음 403, 스키마 위반 400")
    r = subprocess.run(["bash", str(ROOT / "scripts/run-job.sh"), "job-ops-feedback"], capture_output=True, text=True)
    assert r.returncode == 0, f"ops 잡 종료 {r.returncode}: {(r.stderr + r.stdout)[-600:]}"
    summ = json.loads(r.stdout.strip().splitlines()[-1])
    fs = HttpFailureStore(URL("ops"), TOK("ops-read-synthetic-data"))
    cases = fs.list_cases(source_release_id=rel)[0]
    assert cases, f"FailureCase가 생기지 않았다: {summ}"
    for c in cases:
        validate("FailureCase", dict(c))
        ref = c.get("deidentified_trace_ref") or c.get("trace_ref")
    tr = fs.get_trace(cases[0]["deidentified_trace_ref"]); blob = json.dumps(tr, ensure_ascii=False)
    assert f"s-{RID}" not in blob and f"t-{RID}-1" not in blob, "비식별 trace에 원본 세션/턴 ID가 남았다"
    r2 = subprocess.run(["bash", str(ROOT / "scripts/run-job.sh"), "job-ops-feedback"], capture_output=True, text=True)
    s2 = json.loads(r2.stdout.strip().splitlines()[-1]); assert s2.get("cases_published", 0) == 0, f"잡이 멱등이 아니다: {s2}"
    STATE["cases"] = [dict(c) for c in cases]; save()
    rec("6b", "REAL", f"비식별 잡 run-once(컨테이너, 시험용 잡 설정 test/ops-job): FailureCase {len(cases)}건 게시, 스키마 통과, 비식별 trace에 원본 세션·턴 ID 없음(I7 HTTP 읽기), 재실행은 새 사례 0건(멱등). 요약 {json.dumps(summ)[:160]}")

GOOD_EXPECTED = {"action": "NEXT", "next_item": "Q1.D02", "values": [{"key": "Q1.D01.diagnosed", "value": False, "precision": "exact", "status": "ANSWERED", "save": True}]}   # 검토자가 쓴 정답(시험 자료, ActionExtraction)
def bad_ok():
    return {"review_status": "CONFIRMED", "expected_kind": "LORA_A", "expected": GOOD_EXPECTED}

def step7():
    title(7, "실패 사례가 데이터 생성·학습·저작으로 돌아간다 (I7 HTTP)")
    if not STATE.get("cases"): rec(7, "BLOCKED", "FailureCase가 없다(단계 6)"); return
    fs = HttpFailureStore(URL("ops"), TOK("ops-read-synthetic-data"))
    mine = {c["case_id"] for c in STATE["cases"]}
    cid = STATE["cases"][0]["case_id"]
    # 개선 신호(저작으로의 환류): question-authoring이 I7을 HTTP로 읽어 문항별 사례 수를 낸다. 저자 토큰으로 읽는다
    c, sig = http("GET", "qa", f"/v1/signals?question_set_id={QS}", TOK("qa-author-e2e")); assert c == 200, (c, sig)
    blob = json.dumps(sig, ensure_ascii=False)
    assert QS in blob and any(k in blob for k in ("case_count", "cases", "count")), f"신호에 문항 세트/사례 수가 없다: {blob[:300]}"
    assert http("GET", "qa", "/v1/signals", TOK("qa-read-synthetic-data"))[0] == 403, "읽기 토큰으로 신호가 열림"
    assert f'"s-{RID}"' not in blob and "삼십육" not in blob, "신호에 발화/ID 원문이 있다"
    rec("7s", "REAL", f"question-authoring GET /v1/signals(저자 토큰, 읽기 토큰은 403)가 ops-feedback I7을 HTTP로 읽어 문항 세트 {QS}의 사례 수를 낸다(저작으로의 환류). 응답 {blob[:200]}")
    rv_tok = TOK("ops-review-reviewer")
    bad = {"review_status": "CONFIRMED", "expected": {"items": [{"bad": 1}]}, "expected_kind": "LORA_A"}
    c, e = http("POST", "ops", f"/v1/cases/{cid}/review", rv_tok, bad); assert c == 400, (c, e); validate("BoundaryError", e)
    c, e2 = http("POST", "ops", f"/v1/cases/{cid}/review", rv_tok, {"review_status": "CONFIRMED", "expected": GOOD_EXPECTED}); assert c == 400, (c, e2)
    assert http("POST", "ops", f"/v1/cases/{cid}/review", TOK("ops-read-synthetic-data"), bad)[0] == 403, "읽기 토큰으로 검토 게시됨"
    assert http("POST", "ops", f"/v1/cases/nonexistent-case/review", rv_tok, {"review_status": "DISMISSED"})[0] == 404
    pi = dict(__import__("copy").deepcopy(STATE["extract_input"])); pi["user_utterance"] = "뇌졸중은 진단받은 적 없어요"   # 개인정보를 뺀 문장으로 검토자가 쓴 입력(시험 자료, ActionExtractionInput)
    badri = {**bad_ok(), "reviewed_input": {"user_utterance": 1}}
    c, eri = http("POST", "ops", f"/v1/cases/{cid}/review", rv_tok, badri); assert c == 400, ("잘못된 reviewed_input이 받아들여짐", c, eri)
    good = {"review_status": "CONFIRMED", "expected_kind": "LORA_A", "reviewed_input": pi, "expected": GOOD_EXPECTED}
    # ---- 게이트웨이 경유 검토(admin-console 검토 화면의 경로): 사람 계정(reviewer-e2e) 인증 뒤, ops-feedback 읽기/reviewer 쓰기 토큰은 게이트웨이가 붙인다
    assert gw_raw("GET", "/v1/cases")[0] == 401, "인증 없이 /v1/cases 가 열려 있다"
    assert gw_raw("POST", f"/v1/cases/{cid}/review", good)[0] == 401
    assert gw_raw("GET", "/v1/cases", basic=ADMIN())[0] == 403, "승인자 계정이 검토 경로를 부를 수 있다"
    assert gw_raw("POST", f"/v1/cases/{cid}/review", good, basic=ADMIN())[0] == 403, "승인자 계정이 검토를 게시할 수 있다"
    assert gw_raw("GET", "/v1/submissions", basic=REVIEWER())[0] == 403, "검토자 계정이 승인 경로를 부를 수 있다"
    assert gw_raw("POST", "/v1/approvals", {}, basic=REVIEWER())[0] == 403
    assert gw_raw("POST", "/v1/traces", {}, basic=REVIEWER())[0] == 404, "서비스 내부 면(POST /v1/traces)이 게이트웨이에 열려 있다"
    c, lst, hd = gw_raw("GET", "/v1/cases?review_status=PENDING", basic=REVIEWER()); assert c == 200, (c, lst)
    assert "no-store" in {k.lower(): v for k, v in hd.items()}.get("cache-control", ""), "Cache-Control: no-store 가 유지되지 않았다"
    mine_pending = [x for x in lst["items"] if x["case_id"] == cid]; assert mine_pending and mine_pending[0]["review_status"] == "PENDING", lst
    c, one, _ = gw_raw("GET", f"/v1/cases/{cid}", basic=REVIEWER()); assert c == 200 and one["case_id"] == cid, (c, one); validate("FailureCase", one)
    c, trc, _ = gw_raw("GET", "/v1/deidentified-traces/" + one["deidentified_trace_ref"], basic=REVIEWER()); assert c == 200 and trc, (c, trc)
    assert "삼십육" not in json.dumps(trc, ensure_ascii=False) and f's-{RID}' not in json.dumps(trc), "비식별 trace에 원문이 있다"
    c, r1, _ = gw_raw("POST", f"/v1/cases/{cid}/review", good, basic=REVIEWER(), headers={"X-Openit-User": "spoofed-user"}); assert c == 201, (c, r1); validate("FailureCase", r1)
    c, r2, _ = gw_raw("POST", f"/v1/cases/{cid}/review", good, basic=REVIEWER(), headers={"X-Openit-User": "spoofed-user"}); assert c == 200 and r2 == r1, (c, "같은 검토 재전송이 같은 결과가 아니다")
    rec("7g", "REAL", "검토 화면 경로를 게이트웨이 경유로 한 번: 인증 없이 401, 승인자 계정으로 검토 경로 403·검토자 계정으로 승인 경로 403, POST /v1/traces 404, 검토자 계정으로 PENDING 목록 -> 사례 조회(FailureCase 스키마) -> 비식별 trace 조회(no-store 유지, 원문 없음) -> reviewed_input 포함 CONFIRMED 201(재전송 200, 위조 X-Openit-User 무시 요청)")
    rb = (r1.get("ext") or {}).get("ops-feedback", {}).get("reviewed_by")
    assert rb == REVIEWER()[0], f"검토 응답의 reviewed_by 가 인증 계정이 아니다(위조 X-Openit-User={'spoofed-user'}): {rb!r}"
    via_i7 = fs.get_case(cid)   # I7 HTTP 읽기(다른 경로)에서도 같은 기록이어야 한다
    assert (via_i7.get("ext") or {}).get("ops-feedback", {}).get("reviewed_by") == REVIEWER()[0], dict(via_i7).get("ext")
    rec("7h", "REAL", f"검토자 기록: 게이트웨이 경유 검토 응답과 I7 조회 결과의 ext[ops-feedback].reviewed_by 가 인증 계정 {REVIEWER()[0]}이고, 요청에 실은 위조 X-Openit-User(spoofed-user)는 기록되지 않았다(게이트웨이가 덮어씀). 승인 쪽도 같은 위조 시험이 REAL이다(4g: approver_id가 인증 계정 {ADMIN()[0]}). 화면 렌더링은 BLOCKED")

    confirmed = [x for x in fs.list_cases(review_status="CONFIRMED")[0] if x["case_id"] in mine]; assert confirmed
    assert confirmed[0].get("reviewed_input") == pi, "reviewed_input이 I7 읽기에 그대로 보이지 않는다"
    rec("7a", "REAL", f"검토 확인을 HTTP로(직접 호출 검증 + 게이트웨이 경유 확인은 7g): POST /v1/cases/{{id}}/review 잘못된 expected는 400({e.get('message','')[:80]}), expected_kind 없음 400, 읽기 토큰 403, 없는 사례 404, 올바른 확인(reviewed_input 포함)은 201(새 version, FailureCase 스키마 통과, I7 읽기에서 reviewed_input 그대로), 잘못된 reviewed_input 400, 재전송 200 같은 결과. 검토 UI는 아직 없다")
    out = run_sd("2", seeds=True, failure=True); m, _ = read_manifest(out)
    seeded = json.dumps(m.get("ext", {}), ensure_ascii=False) + (WORK / "sd-work-2" / "report.json").read_text()
    for f in (WORK / "datasets" / f"ds-{RID}" / m["version"] / "files").rglob("*.jsonl"):
        seeded += f.read_text()
    cited = any(c["case_id"] in seeded for c in STATE["cases"])
    prev = STATE["dataset"]["version"]
    if cited and m["version"] != prev:
        STATE["dataset2"] = {"id": m["dataset_id"], "version": m["version"], "content_hash": m["content_hash"]}; save()
        rec(7, "REAL", f"synthetic-data가 I7(HTTP)로 CONFIRMED FailureCase를 읽어 새 데이터셋 버전 {m['version']}(이전 {prev})이 사례 ID를 시드로 인용. 저작으로의 환류는 7s(개선 신호). reviewed_input은 I7 읽기에서 그대로 보인다. 학습(model-lab) 회귀 평가가 reviewed_input을 쓰는지는 실행하지 못했다(CPU로 도는 model-lab 이미지가 없고 E2E_GPU는 신호 전, CR-D12)")
    else:
        rec("7b", "BLOCKED", f"새 데이터셋 버전 {m['version']}(이전 {prev})이 만들어졌으나 시드 인용이 없다(CONFIRMED가 아닌 사례는 시드로 쓰이지 않는다). 인용 확인: {cited}. 학습(model-lab)과 저작으로의 환류는 실행하지 않았다")

def step8():
    title(8, "롤백 요청이 활성 릴리스를 되돌린다 (ops-feedback -> release-gate, I5 HTTP)")
    gate_s = HttpGateService(URL("gate"), TOK("gate-write-ops-feedback")); gate_r = HttpReleaseReader(URL("gate"), TOK("gate-read-survey-service"))
    if "releases" not in STATE:
        req = {"pipeline_schema_version": bc.PIPELINE_SCHEMA_VERSION, "request_id": f"rbk-{RID}-0", "requested_at": "2026-10-15T00:00:00Z", "from_release_id": f"rel-{RID}-new",
               "to_release_id": f"rel-{RID}-old", "reason": "E2E 시험", "evidence_refs": ["ev-e2e-test-1"], "requested_by_role": "ops-feedback"}
        validate("RollbackRequest", req); rc = gate_s.request_rollback(req); validate("RollbackReceipt", dict(rc)); assert rc["status"] == "REJECTED"
        rec(8, "BLOCKED", "릴리스가 없어 APPLIED를 못 보인다. 요청 경로만 확인(REJECTED 영수증)"); return
    rels = STATE["releases"]; old, new = rels[STATE["qs"][0]["version"]], rels[STATE["qs"][-1]["version"]]
    cur = gate_r.get_active_pointer(); assert cur["release_id"] == new
    req = {"pipeline_schema_version": bc.PIPELINE_SCHEMA_VERSION, "request_id": f"rbk-{RID}-1", "requested_at": "2026-10-15T00:00:00Z", "from_release_id": new,
           "to_release_id": old, "reason": "E2E 시험 롤백", "evidence_refs": [STATE["cases"][0]["case_id"]] if STATE.get("cases") else ["ev-e2e-test-1"], "requested_by_role": "ops-feedback"}
    validate("RollbackRequest", req)
    rc = gate_s.request_rollback(req); validate("RollbackReceipt", dict(rc)); assert rc["status"] == "APPLIED", dict(rc)
    assert dict(gate_s.request_rollback(req)) == dict(rc), "같은 request_id가 같은 결과가 아니다"
    ap = gate_r.get_active_pointer(); validate("ActivePointer", dict(ap)); assert ap["release_id"] == old and ap["pointer_version"] > STATE["pointers"][-1]["pointer_version"]
    r = wait(lambda: (lambda cr: cr[1] if cr[0] == 200 and cr[1].get("active_release") == old else None)(survey_ready()), 60, f"survey가 이전 릴리스 {old}로 복귀")
    assert not r["release_loader"]["rejections"]
    # 공개 API: 롤백 뒤에도 서비스가 산다. 새 세션은 이전 릴리스로 시작된다(/readyz active_release), 롤백 전에 시작한 세션도 이어서 처리된다
    sidb = f"sess-{RID}-b"
    c, st = kiosk("/v1/sessions", {"session_id": sidb, "kind": "SESSION_START"}); assert c == 200, (c, st)
    c, tb = public_turn(sidb, "turn-1", "뇌졸중은 없어요"); assert c == 200, (c, tb)
    kiosk(f"/v1/sessions/{sidb}/end", {"session_id": sidb, "kind": "SESSION_END"})
    bad = HttpGateService(URL("gate"), TOK("gate-write-question-authoring"))
    try: bad.request_rollback({**req, "request_id": f"rbk-{RID}-2"}); raise AssertionError("허용되지 않은 역할이 롤백함")
    except bc.BoundaryError as e: assert e.code == "PERMISSION_DENIED"
    rec(8, "REAL", f"ops-feedback 토큰의 RollbackRequest -> RollbackReceipt APPLIED(멱등), 활성 포인터 {new}->{old}, 실제 survey-service가 /readyz에서 이전 릴리스로 복귀, 롤백 권한 없는 역할은 PERMISSION_DENIED, 롤백 뒤 공개 API로 새 세션 한 턴 처리(이전 릴리스). 롤백을 요청한 주체는 e2e(ops-feedback 역할 토큰)이고 ops-feedback 잡의 자동 롤백 평가는 아님")

def _gate_clients():
    return (HttpReleaseReader(URL("gate"), TOK("gate-read-survey-service")), HttpGateService(URL("gate"), TOK("gate-write-operator")),
            HttpGateService(URL("gate"), TOK("gate-read-ops-feedback")), HttpGateService(URL("gate"), TOK("gate-write-release-approver")))

def demo4():
    """demo.sh 용: 후보 수집·자동 검사까지 하고, 승인은 --demo-stop 이면 사람에게 남긴다(아니면 시험용 승인자 토큰으로 대신: TEST-SUB). 승인 화면에 볼 제출 하나는 항상 대기로 둔다."""
    title("demo4", "데모 릴리스: 후보 수집·자동 검사 -> 승인 -> 활성화 (release-gate)")
    if "lora" not in STATE: rec("demo4", "BLOCKED", "단계 3의 패키지가 없다"); return
    gate_r, gate_op, gate_rep, gate_ap = _gate_clients()
    r = subprocess.run(["bash", str(ROOT / "scripts/run-job.sh"), "job-release-gate-collect"], capture_output=True, text=True)
    assert r.returncode in (0, 75), f"collect 종료 {r.returncode}: {(r.stderr + r.stdout)[-500:]}"
    A, B = STATE["lora"]["LORA_A"], STATE["lora"]["LORA_B"]
    subj = {v["version"]: {"question_set": v, "lora_a": A, "lora_b": B} for v in STATE["qs"]}
    subj_u = {"question_set": STATE["qsu"], "lora_a": A, "lora_b": B}
    subs = {k: dict(gate_op.submit_candidate(sj, requested_by_role="operator")) for k, sj in subj.items()}
    sub_u = dict(gate_op.submit_candidate(subj_u, requested_by_role="operator"))
    def report_of(sid):
        try: return dict(gate_rep.get_review_report(sid))
        except bc.BoundaryError: return None
    for k, sub in list(subs.items()) + [("u", sub_u)]:
        wait_review_report(report_of, sub["submission_id"], k)
    STATE["demo_subs"] = {**{k: v["submission_id"] for k, v in subs.items()}, "u": sub_u["submission_id"]}; save()
    if a.demo_stop:
        rec("demo4", "REAL", f"후보 수집·자동 검사까지 완료. 승인 대기 제출: " + ", ".join(f"문항 세트 v{k}={v['submission_id']}" for k, v in subs.items()) + f", 보지 못한 문항 세트={sub_u['submission_id']}. 사람이 /admin/ 에서 승인한 뒤 demo.sh activate")
        return
    rels = {}
    for k, sub in subs.items():
        gate_ap.decide(sub["submission_id"], "APPROVE", approver_id="trainer-test", approver_role="release-approver", reason="데모: 시험용 승인자(스크립트)가 대신 승인")
    for k, sj in subj.items():
        d = wait(lambda sj=sj: next((x for x in decisions_for(gate_r, sj) if x["result"] == "PASS"), None), 30, f"PASS 판정 v{k}")
        rels[k] = d.get("release_id")
    for k in sorted(rels): gate_op.activate(rels[k], requested_by_role="operator")
    STATE["releases"] = rels; save()
    rec("demo4", "TEST-SUB", f"승인자를 스크립트가 시험용 토큰으로 대신했다(TEST-SUB). PASS 릴리스 {rels}, 활성화 완료. 승인 화면용으로 제출 {sub_u['submission_id']}(보지 못한 문항 세트)는 승인 대기로 남겼다")

def demo_activate():
    """사람이 /admin/ 에서 승인한 제출의 릴리스를 활성화한다(오래된 문항 세트 버전부터)."""
    title("demo_activate", "승인된 제출의 릴리스 활성화")
    gate_r, gate_op, _, _ = _gate_clients()
    rels = {}
    for k in sorted(v["version"] for v in STATE["qs"]):
        sj = {"question_set": next(v for v in STATE["qs"] if v["version"] == k), "lora_a": STATE["lora"]["LORA_A"], "lora_b": STATE["lora"]["LORA_B"]}
        d = next((x for x in decisions_for(gate_r, sj) if x["result"] == "PASS"), None)
        if d: rels[k] = d.get("release_id")
    if not rels: rec("demo_activate", "BLOCKED", "승인된(PASS) 제출이 아직 없다. /admin/ 에서 승인한 뒤 다시 실행한다"); return
    cur = gate_r.get_active_pointer()
    for k in sorted(rels):
        if not cur or cur["release_id"] != rels[k]: cur = gate_op.activate(rels[k], requested_by_role="operator")
    STATE["releases"] = rels; save()
    rec("demo_activate", "REAL", f"승인된 릴리스 활성화: {rels}, 현재 활성 {dict(cur)['release_id']}")

def diag():
    """demo.sh diag: 켜져 있는 데모의 게이트·레지스트리 상태를 읽기 전용으로 요약한다(HTTP만, 토큰·비밀 값은 출력하지 않는다)."""
    title("diag", "진단: 제출·판정·수집기·모델 패키지")
    gs, rd = gate_diag_clients()
    try:
        items, _ = gs.list_submissions(limit=100)
        print(f"-- release-gate 제출 {len(items)}건")
        for v in items:
            subj = v.get("subject", {}); qs = subj.get("question_set", {}); la = subj.get("lora_a", {}); lb = subj.get("lora_b", {})
            print(f"  [{v.get('status')}] {v['submission_id']} 문항 세트 {qs.get('id')}@{qs.get('version')} LoRA_A {la.get('id')}@{la.get('version')} LoRA_B {lb.get('id')}@{lb.get('version')} decision={v.get('decision_id')} release={v.get('release_id')}")
            if v.get("decision_id"):
                print("\n".join("      " + l for l in decision_text(dict(rd.get_decision(v["decision_id"]))).splitlines()))
    except Exception as e:
        print(f"-- 제출 목록을 읽지 못했다: {type(e).__name__}: {str(e)[:200]}")
    try:
        ap = rd.get_active_pointer(); print(f"-- 활성 릴리스 포인터: {ap}")
    except Exception as e:
        print(f"-- 활성 포인터를 읽지 못했다: {type(e).__name__}: {str(e)[:120]}")
    r = subprocess.run(["bash", str(ROOT / "scripts/run-job.sh"), "job-release-gate-collect"], capture_output=True, text=True)
    print(f"-- 후보 수집기 run-once 다시 실행(멱등) 종료 코드 {r.returncode}; 마지막 출력: {(r.stdout.strip().splitlines() or ['(없음)'])[-1][:300]}")
    try:
        mr = HttpModelRegistry(URL("mr"), TOK("model-registry-read-release-gate")); ids = mr.list_ids()
        print(f"-- model-registry 패키지 {len(ids)}개")
        for i in ids:
            vs = mr.list_versions(i); print(f"  {i}: 버전 {vs}")
            for v in vs[-1:]:
                m = mr.get_manifest(i, v); sc = m.get("serving_config", {}); print(f"      role={m.get('role')} base={m.get('base_model')} constraint.backend={sc.get('constraint', {}).get('backend')}@{sc.get('constraint', {}).get('backend_version')} prompt={sc.get('prompt_template_version')} runtime={m.get('lineage', {}).get('model_runtime_version')}")
    except Exception as e:
        print(f"-- model-registry 패키지를 읽지 못했다: {type(e).__name__}: {str(e)[:200]}")
    try:
        c, info = http("GET", "ms", "/v1/info", INF_TOK())
        ex = (info.get("serving_config_expectation") or {}) if c == 200 else {}
        print(f"-- model-serving /v1/info: HTTP {c} backend={info.get('backend') if c == 200 else '-'} 기대 constraint={ex.get('constraint')} prompt={ex.get('prompt_template_versions')} loaded={info.get('loaded') if c == 200 else '-'}")
    except Exception as e:
        print(f"-- model-serving /v1/info 를 읽지 못했다: {type(e).__name__}: {str(e)[:120]}")
    try:
        c, rz = http("GET", "ms", "/readyz"); reason = rz.get("reason") if isinstance(rz, dict) else None
        print(f"-- model-serving /readyz: HTTP {c} status={rz.get('status') if isinstance(rz, dict) else rz} 사유={reason}")
        r = sh([a.docker, "exec", MS_CONTAINER, "sh", "-c", "echo uid=$(id -u); echo hf_home=${HF_HOME:-<unset>}; d=${HF_HOME:-/var/lib/model-runtime/hf}; echo owner=$(stat -c %U:%u \"$d\"); (test -w \"$d\" && echo writable) || echo NOT-writable"], check=False)
        info_txt = " ".join((r.stdout or "").split()) or (r.stderr or "").strip()[:160]
        print(f"-- model-serving 컨테이너 안(읽기만, 쓰기 시험 없음): {info_txt}")
        if "NOT-writable" in (r.stdout or "") or "OSError" in str(reason):
            print("   -> 모델 캐시 쓰기 불가 가능성: HF 경로가 root 소유이거나 이미지가 준비한 경로가 아닌 곳에 마운트됐다. 빈 볼륨이면 demo.sh down 뒤 docker volume rm deploy-llm-hf-cache 로 지우고 다시 up --llm (docs/RUN.md '모델 캐시가 쓰기 불가일 때')")
    except Exception as e:
        print(f"-- model-serving /readyz·컨테이너 점검을 건너뜀: {type(e).__name__}: {str(e)[:120]}")
    print(f"-- 상태 파일 요약: 릴리스 {STATE.get('releases')}, 제출 {STATE.get('demo_subs')}, llm 대조 {STATE.get('llm_cfg_vs_server')}")
    rec("diag", "REAL", "진단 출력만 했다(변경 없음)")

STEPS = [("1", step1), ("2", step2), ("3", step3), ("4", step4), ("5", step5), ("5f", step5f), ("6", step6), ("7", step7), ("8", step8), ("demo4", demo4), ("demo_activate", demo_activate), ("diag", diag)]
only = set(filter(None, a.only.split(",")))
TIMES = []
for n, fn in STEPS:
    if only and n not in only: continue
    if n.startswith("demo") and n not in only: continue   # demo.sh 전용 단계는 E2E 기본 실행에 넣지 않는다
    t0 = time.time()
    try: fn()
    except AssertionError as e: rec(fn.__name__, "FAIL", str(e))
    except Exception as e: rec(fn.__name__, "FAIL", f"{type(e).__name__}: {e}")
    TIMES.append((n, time.time() - t0)); print(f"  (소요 {TIMES[-1][1]:.1f}s)", flush=True)
print("\n== 요약 (단계 1~8)")
for s, st, d in RESULTS: print(f"  {str(s):>4} {st:9} {d[:170]}")
print("\n== 단계별 소요 시간 (1~8)")
for n, sec in TIMES: print(f"  {sec:7.1f}s  단계 {n}")
print(f"  {sum(x for _, x in TIMES):7.1f}s  합계")
(WORK / "steps.json").write_text(json.dumps([list(r) for r in RESULTS], ensure_ascii=False, indent=1))
sys.exit(1 if any(r[1] == "FAIL" for r in RESULTS) else 0)
