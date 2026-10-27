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
import e2e_asserts as EA

ap = argparse.ArgumentParser()
ap.add_argument("--project", required=True); ap.add_argument("--secrets", required=True)
ap.add_argument("--ports", required=True); ap.add_argument("--images", required=True)
ap.add_argument("--docker", default="docker"); ap.add_argument("--root", required=True)
ap.add_argument("--work", required=True, help="이번 실행의 임시 작업 폴더")
ap.add_argument("--run-id", default="e2e-test")
ap.add_argument("--demo-stop", action="store_true", help="demo4: 승인 대기까지만 만든다(사람이 /admin/ 에서 승인)")
ap.add_argument("--gw-ca", default="", help="gateway(HTTPS)의 내부 CA 루트 인증서 파일(시험용 CA). 있으면 gw 주소는 https 이고 이 CA만 신뢰한다")
ap.add_argument("--only", default="", help="쉼표로 구분한 단계(예: 1,2). 비우면 전부")
ap.add_argument("--ms-url", default="", help="추론 서버를 다른 곳에 둔 경우 그 주소(예: http://gpu-host:8080). 비우면 이 프로젝트의 model-serving 컨테이너")
ap.add_argument("--ms-container", default="", help="추론 서버 컨테이너 이름(멈춤·재시작 시험용). 기본 <프로젝트>-model-serving-1")
ap.add_argument("--ms-token-file", default="", help="외부 추론 서버의 호출자 토큰 파일(내용이 토큰 하나). 비우면 이 구성이 만든 토큰")
ap.add_argument("--llm-package", default="", help="실제 LLM 데모: make_neutral_package.py 가 만든 폴더(LORA_A, LORA_B). 단계 3이 시험용 fake 어댑터 대신 이 중립 LoRA 패키지(vllm 서빙 설정)를 게시한다")
ap.add_argument("--turn-engine-version", default=os.environ.get("DEPLOY_TE_TAG", "v0.4.0").lstrip("v"), help="매니페스트 lineage 의 turn-engine 버전(게이트 기준과 문자열이 같아야 한다, D80). e2e.sh 가 lib.sh 의 값을 넘긴다")
ap.add_argument("--skip-ms-restart", action="store_true", help="5단계의 추론 서버 중단·복구를 건너뛴다(서버 호스트 포트가 Docker 배정이라 재시작 뒤 주소가 바뀌는 별도 프로젝트 시험용)")
a = ap.parse_args()
import ssl
if a.gw_ca:   # 게이트웨이 호출(urlopen)이 HTTPS 이고 이 CA 만 신뢰한다. boundary_contracts 클라이언트는 gateway 를 거치지 않아 영향 없다
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=a.gw_ca))))
PORTS = json.loads(a.ports); IMAGES = json.loads(a.images); ROOT = pathlib.Path(a.root); WORK = pathlib.Path(a.work)
WORK.mkdir(parents=True, exist_ok=True)
RID = a.run_id
TOK = lambda n: (pathlib.Path(a.secrets) / "tokens" / n).read_text().strip()
def INF_TOK():   # 추론 서버가 호출자(survey-service)에게 기대하는 토큰
    if a.ms_token_file:
        t = pathlib.Path(a.ms_token_file).read_text().strip()
        if not t or t.startswith("EXTERNAL_INFERENCE_TOKEN="): raise SystemExit("--ms-token-file 은 토큰 값 하나가 든 파일이어야 한다(D84)")
        return t
    return TOK("inference-survey-service")
MS_CONTAINER = a.ms_container or f"{a.project}-model-serving-1"
def _ms_port():   # 추론 서버는 멈췄다 다시 뜨면 호스트 포트가 바뀔 수 있어 매번 Docker에게 묻는다
    out = subprocess.run([a.docker, "port", MS_CONTAINER, "8080/tcp"], capture_output=True, text=True).stdout
    return out.splitlines()[0].strip().rsplit(":", 1)[1] if out.strip() else PORTS["ms"]
def _dyn_port(svc, key, cport="8080"):   # 멈췄다 다시 띄우는 단계(5q·5w·5u)가 있는 서비스는 Docker 배정 호스트 포트가 바뀔 수 있어 매번 묻는다
    out = subprocess.run([a.docker, "port", f"{a.project}-{svc}-1", f"{cport}/tcp"], capture_output=True, text=True).stdout
    return out.splitlines()[0].strip().rsplit(":", 1)[1] if out.strip() else PORTS[key]
DYN = {"survey": "survey-service", "gate": "release-gate", "ops": "ops-feedback-ingest"}   # (gw 는 HTTPS 8443 이라 아래 URL 에서 따로)
URL = lambda k: a.ms_url.rstrip("/") if (k == "ms" and a.ms_url) else f"{'https' if (k == 'gw' and a.gw_ca) else 'http'}://127.0.0.1:{_ms_port() if k == 'ms' else _dyn_port(DYN[k], k) if k in DYN else _dyn_port('gateway', 'gw', '8443') if k == 'gw' else PORTS[k]}"
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
def http(method, k, path, token=None, body=None, raw=None, ctype="application/json", basic=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(URL(k) + path, data=data, method=method)
    if token: req.add_header("Authorization", f"Bearer {token}")
    if basic: req.add_header("Authorization", "Basic " + __import__("base64").b64encode(f"{basic[0]}:{basic[1]}".encode()).decode())
    if data is not None: req.add_header("Content-Type", ctype)
    for hk, hv in (headers or {}).items(): req.add_header(hk, hv)
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        b = e.read()
        try: return e.code, json.loads(b)
        except Exception: return e.code, b.decode(errors="replace")
def with_user(client, user):
    """승인(POST /v1/approvals)은 X-Openit-User 가 없으면 401 이고 approver_id 는 이 헤더 값으로 기록된다(release-gate CR-0008). SDK 클라이언트는 헤더를 못 보내므로 opener 의 기본 헤더로 붙인다(gateway 가 붙이는 인증 사용자 흉내, TEST-SUB)."""
    client._opener.addheaders = [h for h in client._opener.addheaders if h[0].lower() != "x-openit-user"] + [("X-Openit-User", user)]
    return client

RVH = {"X-Openit-User": "reviewer-direct-e2e"}   # 검토 게시는 X-Openit-User(gateway 가 붙이는 인증 사용자)가 없으면 403(ops-feedback D88/U7). gateway 를 거치지 않는 직접 호출에 시험용 값을 붙인다
OPERATOR_ID = "operator-e2e-script"   # 시험용 운영자 ID: 게이트웨이가 계정 ID를 X-Openit-User 로 붙이는 것을 스크립트가 직접 흉내 낸다
def gate_ops(path, body, user=OPERATOR_ID, token=None):
    """release-gate 의 activate·rollback 을 HTTP 로 부른다(D85: 역할은 쓰기 토큰, 행위자는 X-Openit-User 헤더. SDK 는 헤더를 못 보낸다). (상태, JSON 본문)을 돌려준다.
    user=None 이면 헤더를 붙이지 않는다. 본문의 requested_by_role 은 게이트가 무시한다(옛 게이트 호환을 위해 operator 로 넣는다)."""
    req = urllib.request.Request(URL("gate") + path, data=json.dumps({"requested_by_role": "operator", **body}).encode(), method="POST")
    req.add_header("Authorization", "Bearer " + (token or TOK("gate-write-operator"))); req.add_header("Content-Type", "application/json")
    if user is not None: req.add_header("X-Openit-User", user)
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        b = e.read()
        try: return e.code, json.loads(b)
        except Exception: return e.code, b.decode(errors="replace")
def gate_activate(release_id, user=OPERATOR_ID):
    c, b = gate_ops("/v1/activate", {"release_id": release_id}, user)
    assert c == 200, f"activate {release_id} 실패 {c}: {str(b)[:200]}"
    return b
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
    # 4-eyes(question-authoring D88/U9): 저자의 확인은 clinical_basis_approved=false 이고, 임상 근거 승인은 clinical-reviewer 역할의 다른 주체가 덧붙여야 reviewed_only 에 나타난다
    c, rv = http("POST", "qa", "/v1/reviews", TOK("qa-reviewer-e2e"), body={"question_set": ref, "decision": "APPROVED", "clinical_basis_approved": True, "reason": "E2E 시험용 임상 근거 승인(TEST-SUB: 스크립트가 검수자 역할을 대신한다)"}); assert c in (200, 201), ("임상 근거 승인 실패", c, rv)
    return ref, raw

def step1():
    title(1, "저자가 문항 자료를 올리고 미리보기를 확인한다 (question-authoring, I1 HTTP 읽기)")
    form = (ROOT / "test/fixtures/question-form-v2.txt").read_text()   # 학습 데이터셋 v2 의 문항 ID 31개(survey-service 의 QuestionFlow 와 같은 순서). 값은 모두 시험용
    r1, raw1 = upload(QS, form, "form1.txt")
    r2, _ = upload(QS, form.replace("시험 문항 Q1.D01입니다. 알려 주세요.", "시험 문항 Q1.D01입니다. 말씀해 주세요."), "form2.txt")
    ru, _ = upload(QSU, form.replace("알려 주세요.", "들려 주세요."), "unseen.txt")
    c, e_ = http("POST", "qa", "/v1/reviews", TOK("qa-author-e2e"), body={"question_set": r1, "decision": "APPROVED", "clinical_basis_approved": True}); assert c == 403, ("저자가 자기 확인을 임상 승인했다(4-eyes)", c, e_)
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
        revs = list(rd.get_reviews(v)); assert len(revs) == 2, ("저자 확인 + 검수자 승인 두 검수여야 한다", len(revs))
        for r_ in revs: validate("ReviewRecord", r_)
        assert revs[0]["clinical_basis_approved"] is False, "저자의 확인이 임상 근거를 승인했다(4-eyes 위반)"
        rv = revs[-1]
        assert rv["decision"] == "APPROVED" and rv["clinical_basis_approved"] is True and rv["question_set"] == v and rv["reviewer_id"] != revs[0]["reviewer_id"], rv
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

IMPORT_DIR = ROOT / "test/import-v2"   # 이 E2E 를 위해 직접 만든 아주 작은 v2 형식 jsonl 6개(실제 학습 데이터가 아니다, test/import-v2/make_rows.py)
def imp_config(name, max_invalid_rows, store_root):
    q = STATE["qs"][-1]   # 문항 세트 출처: CR-006 미정이라 임시로 이 E2E 가 단계 1 에서 만든 문항 세트 참조를 적는다(deploy 가 정한 값이 아니다)
    cfg = {"dataset_id": f"ds-{RID}", "input_dir": str(IMPORT_DIR), "survey_schema_dir": str(SD["schema"]),
           "question_sets": [{"id": QS, "version": q["version"], "content_hash": q["content_hash"]}],
           "source_label": "deploy-e2e-test-data", "turn_engine_version": a.turn_engine_version, "created_at": "2026-10-27T00:00:00Z",
           "tolerance": {"max_invalid_rows": max_invalid_rows, "max_invalid_rate": 1.0},
           "output": {"work_dir": str(WORK / f"sd-import-{name}"), "store": {"kind": "file", "root": str(store_root)}}}
    p = WORK / f"sd-import-{name}.json"; p.write_text(json.dumps(cfg, ensure_ascii=False, indent=1)); return p

def run_import(name, max_invalid_rows, store_root):
    p = imp_config(name, max_invalid_rows, store_root)
    r = subprocess.run([str(SD["venv"]), "-m", "synthetic_data", "import", "--config", str(p)], cwd=str(SD["src"]), capture_output=True, text=True,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    return r.returncode, out, json.loads((WORK / f"sd-import-{name}" / "import_report.json").read_text())

def step2():
    title(2, "학습 데이터 게시 (synthetic-data 게시기 모드 import: 시험용 v2 jsonl 6개를 행 단위로 검증하고 허용치 안에서 게시) -- 배선 REAL, 데이터는 시험용")
    print("  !! 입력은 데이터셋 담당의 실제 학습 데이터가 아니다: 이 E2E 를 위해 직접 만든 아주 작은 모음이고 행 형식은 추정이다(실제 데이터로 게시한 적 없음) !!")
    files = sorted(IMPORT_DIR.glob("lora_*_*.jsonl")); assert len(files) == 6, [f.name for f in files]
    # (a) 허용치 초과: 일부러 넣은 위반 2행이 허용 1행을 넘으면 게시하지 않는다(종료 코드 4, REJECTED, 저장소에 데이터셋이 생기지 않는다)
    rc, o, rep = run_import("reject", 1, WORK / "datasets-rejected")
    assert rc == 4 and o.get("status") == "REJECTED", f"허용치 초과가 게시 거부(종료 4)가 아니다: {rc} {o}"
    assert not (WORK / "datasets-rejected" / f"ds-{RID}").exists(), "거부했는데 저장소에 데이터셋이 생겼다"
    # (b) 허용치 안(2행): 게시. 위반 집계와 입력 해시를 보고서에서 확인한다
    rc, o, rep = run_import("ok", 2, WORK / "datasets")
    assert rc == 0 and o.get("status") in ("PUBLISHED", "ALREADY_PUBLISHED"), f"게시 실패: {rc} {o}"
    cnt = o["counts"]; assert (cnt["rows_total"], cnt["rows_valid"], cnt["rows_invalid"]) == (26, 24, 2), cnt
    assert sum(rep["invalid_reasons_by_file"]["lora_a_train.jsonl"].values()) >= 1 and sum(rep["invalid_reasons_by_file"]["lora_b_val.jsonl"].values()) == 1, rep["invalid_reasons_by_file"]
    for f in files:
        h = "sha256:" + hashlib.sha256(f.read_bytes()).hexdigest(); assert rep["inputs"][f.name]["sha256"] == h, f"입력 해시가 다르다 {f.name}"
        assert rep["inputs"][f.name]["rows"] == len(f.read_text(encoding="utf-8").splitlines()), f.name
    m, root = read_manifest(o)
    for f in m["files"]:
        assert canonical.file_hash(root / "files" / f["path"]) == f["content_hash"], f"파일 해시 불일치 {f['path']}"
    assert sum(f["sample_count"] for f in m["files"]) == 24 and {f["split"] for f in m["files"]} == {"TRAIN", "VALIDATION", "EVAL"}, [(f["path"], f["split"], f["sample_count"]) for f in m["files"]]
    # (c) 같은 입력 재실행은 멱등
    rc2, o2, _ = run_import("ok2", 2, WORK / "datasets")
    assert rc2 == 0 and o2["status"] == "ALREADY_PUBLISHED" and o2["version"] == o["version"], f"같은 입력 재실행이 같은 결과가 아니다: {rc2} {o2}"
    STATE["dataset"] = {"id": m["dataset_id"], "version": m["version"], "content_hash": m["content_hash"]}; save()
    rec(2, "REAL", f"배선 REAL, 데이터는 시험용: synthetic-data import 모드(호스트)가 이 E2E 용으로 직접 만든 v2 형식 jsonl 6개(실제 학습 데이터 아님, 행 형식은 추정, 실제 데이터로 게시한 적 없음)를 행 단위로 검증: 26행 중 24 통과, 일부러 넣은 위반 2행(v2 출력 위반 1, JSON 아님 1)을 사유별로 집계. 허용 1행이면 게시 거부(종료 4, 저장소 무변화), 허용 2행이면 DatasetManifest {m['dataset_id']}@{m['version']} 게시(스키마·파일 해시·입력 sha256·건수 일치), 재실행은 ALREADY_PUBLISHED(멱등). 못 보는 것: 의미 검사(targets·next_item·건너뛰기 순서, CR-006), 실제 데이터의 형식, 보지 못한 문항 세트 평가 분리")

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

def publish_packages(pk):
    """make_packages() 의 패키지 2건을 model-registry 에 HTTP 로 게시(멱등 확인)하고 읽기 토큰으로 다시 읽어 해시를 검증한다. 단계 3 과 demo.sh swap-adapters 가 같이 쓴다. {역할: 참조} 를 돌려준다."""
    reg = HttpModelRegistry(URL("mr"), TOK("model-registry-write-model-lab"))
    refs = {}
    for role, (mf, adir, rep) in pk.items():
        rb = json.dumps(rep, ensure_ascii=False, sort_keys=True).encode()
        got = reg.publish(mf, adir, rb)
        again = reg.publish(mf, adir, rb); assert dict(again) == dict(got), "게시가 멱등이 아니다"
        refs[role] = {"id": mf["package_id"], "version": mf["version"], "content_hash": mf["content_hash"]}
    rr = HttpModelRegistry(URL("mr"), TOK("model-registry-read-release-gate"))
    for role, (mf, adir, rep) in pk.items():
        g = rr.get_manifest(mf["package_id"], mf["version"]); validate("ModelPackageManifest", g); assert g["content_hash"] == mf["content_hash"]
        got_rep = json.loads(rr.get_eval_report(g["eval_report_ref"])); validate("EvaluationReport", got_rep); assert got_rep["content_hash"] == rep["content_hash"] == canonical.content_hash({k: v for k, v in got_rep.items()})
        dest = WORK / f"adapter-{role}-{mf['package_id']}"; p = rr.open_adapter(mf["package_id"], mf["version"], dest=dest)   # 해시 검증 포함
        assert canonical.directory_hash(p) == mf["adapter_hash"]
    return refs

def step3():
    title(3, "설정 하나로 학습·평가·패키징·게시가 돈다 (model-lab, I3) -- 시험 대역")
    if os.environ.get("E2E_GPU") == "1":
        r = subprocess.run(["bash", str(ROOT / "scripts/e2e_gpu.sh"), str(PORTS["mr"]), str(pathlib.Path(a.secrets) / "tokens" / "model-registry-write-model-lab")], capture_output=True, text=True)
        if r.returncode != 0:
            rec(3, "BLOCKED", f"E2E_GPU=1 경로(scripts/e2e_gpu.sh, 미검증) 실패 {r.returncode}: {(r.stderr or r.stdout)[-300:]}. 기본 경로(시험용 어댑터)로 계속하지 않았다"); return
        rec(3, "BLOCKED", "E2E_GPU=1 경로는 게시까지만 있고 이후 단계가 읽을 참조 해석이 미구현(CR-D12)"); return
    pk = make_packages(); refs = publish_packages(pk)
    try:
        reg_ro = HttpModelRegistry(URL("mr"), TOK("model-registry-read-release-gate")); reg_ro.publish(pk["LORA_A"][0], pk["LORA_A"][1], b"{}"); raise AssertionError("읽기 토큰으로 게시됨")
    except bc.BoundaryError as e: assert e.code == "PERMISSION_DENIED"
    STATE["lora"] = refs; STATE["system_prompt"] = {r: pk[r][0]["system_prompt"]["sha256"] for r in pk}; save()
    src_desc = ("학습 서버에서 가져온 LoRA-A/B(model-runtime 설정 + 가져온 어댑터, 평가하지 않음)" if a.llm_package and pk["LORA_A"][0].get("ext", {}).get("deploy", {}).get("attached") else "학습하지 않은 중립 LoRA(model-runtime make_neutral_package.py + 학습 데이터 system 메시지 프롬프트, vllm 서빙 설정, lora_B=0이라 출력은 기반 모델과 같다)" if a.llm_package
                else "시험용 어댑터(test/fixtures/e2e-test-adapter, PEFT 형식 r=16, 기반 모델 Qwen/Qwen2.5-1.5B-Instruct; fake 백엔드는 기반 모델을 적재하지 않는다)")
    rec(3, "TEST-SUB", f"학습 대신 {src_desc}와 시험용 EvaluationReport(METRICS.md 이름의 고정 지표, 실제 평가 아님)를 model-registry에 HTTP로 게시. serving_config는 추론 서버 /v1/info의 serving_config_expectation으로 만들었다(survey 이미지 fake_serving_configs와 다른 키: {STATE.get('fake_cfg_vs_survey_image')}). 게시(REAL): 멱등, 읽기 토큰 게시 거부, 읽기로 매니페스트·어댑터 해시 검증 통과. 계보의 dataset은 단계 2가 게시한 실제 데이터셋(단계 2가 BLOCKED이면 자리표시 참조, TEST-SUB). 시스템 프롬프트는 어댑터 디렉터리의 system_prompt.txt와 ModelPackageManifest.system_prompt(path, sha256)로 패키지에 들어 있다(시험용 자리표시 문장). model-lab 파이프라인·패키징 코드는 실행하지 않음(이웃 코드를 가져오지 않는다)")

def decisions_for(gate_read, subj):
    return gate_read.find_decisions(question_set=subj["question_set"], lora_a=subj["lora_a"], lora_b=subj["lora_b"])[0]

ADMIN = lambda: ("trainer-e2e", TOK("account-trainer-e2e-password"))   # 개별 계정(config/gateway-accounts.conf, D85 E절)
OPERATOR = lambda: ("operator-e2e", TOK("account-operator-e2e-password"))   # 역할 operator: /v1/activate, /v1/rollback
REVIEWER = lambda: ("reviewer-e2e", TOK("account-reviewer-e2e-password"))   # 실패 사례 검토 화면 계정(역할 reviewer)   # 승인 화면 기본 인증 시험 계정(운영 인증 방식은 미정)

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
    # release-gate CR-0008: 본문의 approver_id 가 인증된 사용자(X-Openit-User)와 다르면 400 이다(본문 값을 조용히 무시하지 않는다). 위조 헤더는 gateway 가 인증 계정으로 덮어쓴다
    c, bad_, _ = gw_raw("POST", "/v1/approvals", body, basic=ADMIN(), headers={"X-Openit-User": "spoofed-user"}); assert c == 400, ("본문 approver_id 가 인증 사용자와 달라도 받아들여졌다", c, bad_)
    body = {**body, "approver_id": ADMIN()[0]}
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
    gate_r = HttpReleaseReader(URL("gate"), TOK("gate-read-survey-service")); gate_op = with_user(HttpGateService(URL("gate"), TOK("gate-write-operator")), "op-test")
    gate_rep = HttpGateService(URL("gate"), TOK("gate-read-ops-feedback")); gate_ap = with_user(HttpGateService(URL("gate"), TOK("gate-write-release-approver")), "trainer-test")
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
    c401, b401 = gate_ops("/v1/activate", {"release_id": rid1}, user=None)
    assert c401 == 401, f"헤더 없이 operator 토큰으로 activate 하면 401이어야 한다: {c401} {str(b401)[:100]}"
    assert dict(gate_r.get_active_pointer() or {}).get("release_id") != rid1, "401인데 활성 포인터가 바뀌었다"
    ap1 = dict(gate_activate(rid1)); validate("ActivePointer", ap1)
    cur = dict(gate_r.get_active_pointer()); assert cur["ext"]["release-gate"]["requested_by"] == OPERATOR_ID, f"활성 포인터 조회의 requested_by 가 헤더의 ID가 아니다: {cur.get('ext')}"
    # 둘째 후보: 활성 릴리스와 같은 지표끼리 맞댄 보고서(comparisons), 활성화로 보고서가 바뀌면 이전 해시는 낡은 것
    rep2 = report_of(subs["2"]["submission_id"]); validate("ReviewReport", rep2)
    assert rep2["comparisons"], "활성 릴리스와의 비교가 비어 있다"
    sid2 = subs["2"]["submission_id"]
    a2 = dict(gate_ap.decide(sid2, "APPROVE", approver_id="trainer-test", approver_role="release-approver", reason="시험: 둘째 후보 검토함")); validate("GateApproval", a2)
    d2 = wait(lambda: next((d for d in decisions_for(gate_r, subj["2"]) if d["result"] == "PASS"), None), 30, "둘째 PASS 판정"); validate("GateDecision", dict(d2))
    rid2 = d2.get("release_id"); rel2 = dict(gate_r.get_release(rid2)); validate("ReleaseManifest", rel2); gate_r.load_bundle(rid2, dest=bd)
    STATE["containers_before_swap"] = container_ids(); save()   # 포인터 1 -> 2 활성화 직전(StartedAt, ID 만 읽는다)
    ap2 = dict(gate_activate(rid2)); validate("ActivePointer", ap2); assert ap2["pointer_version"] > ap1["pointer_version"]
    cx, bx = gate_ops("/v1/activate", {"release_id": du.get("release_id") or "rel-none-x"}); assert cx != 200 and isinstance(bx, dict) and bx.get("code") in ("NOT_FOUND", "FAILED_PRECONDITION"), ("PASS가 아닌 릴리스가 활성화됨", cx, str(bx)[:100])
    STATE["releases"] = {"1": rid1, "2": rid2}; STATE["pointers"] = [ap1, ap2]; save()
    rec("4b", "TEST-SUB", f"승인자를 스크립트가 대신한다(TEST-SUB). REAL: 자동 검사 통과 후 승인 요청 보고서(ReviewReport, 활성 릴리스와 비교), 승인 전 PASS 없음, operator의 승인 403, 낡은 report_hash 409, REJECT -> REJECT 판정(HUMAN_APPROVAL FAIL, CHECK_FAILED), APPROVE 재전송 멱등·번복 409, 승인 뒤 PASS(HUMAN_APPROVAL PASS)·ReleaseManifest(해시)·번들(해시)·활성화 x2(포인터 {ap1['pointer_version']}->{ap2['pointer_version']})")

def survey_ready():
    c, r = http("GET", "survey", "/readyz"); return c, r

def kiosk(path, body):
    # 키오스크 앱처럼 기기 토큰(Authorization: Bearer)으로 부른다: 게이트웨이가 대조한 뒤 kiosk 역할 토큰으로 바꿔 붙인다(D85 F절)
    return http("POST", "gw", path, KDEV(), body)

KDEV = lambda: TOK("kiosk-device-e2e")   # 시험 기기 토큰(scripts/gen-secrets.sh)
STAFF = lambda: ("staff-e2e", TOK("account-staff-e2e-password"))   # 직원 콘솔 기본 인증(개발/E2E용)
def state_of(sid):
    """GET /v1/sessions/{id}/state. 서버가 0.5초보다 잦은 조회를 429(UNAVAILABLE)로 막으므로 간격을 두고 재시도한다(키오스크는 2초 간격 폴링)."""
    for _ in range(8):
        time.sleep(0.7)
        c, r = http("GET", "gw", f"/v1/sessions/{sid}/state", KDEV())
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
# 0.7.1: 칸 정의(slots)가 있는 문항은 발화에서 첫 칸의 ANSWERED 값을 낸다. 아래 직접 호출은 Q1.D03(boolean, '아니' 없음 -> true)
FAKE_EXTRACTION = {"action": "NEXT", "next_item": "Q1.D04", "values": [{"key": "Q1.D03.diagnosed", "precision": "exact", "save": True, "status": "ANSWERED", "value": True}]}
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

SWAP_SERVICES = ["survey-service", "release-gate", "model-registry", "ops-feedback-ingest", "question-authoring", "gateway"]
def container_ids():
    """서비스별 (컨테이너 ID, StartedAt). docker inspect 의 두 필드만 읽는다(Env 등은 읽지 않는다)."""
    out = {}
    for svc in SWAP_SERVICES:
        r = sh([a.docker, "inspect", "-f", "{{.Id}} {{.State.StartedAt}}", f"{a.project}-{svc}-1"], check=False)
        parts = r.stdout.strip().split(" ", 1)
        if r.returncode == 0 and len(parts) == 2: out[svc] = (parts[0], parts[1])
    return out

def fake_values_check(new, tok):
    """가짜 A(칸 정의가 든 흐름 파일)가 값을 내고 건너뛰기를 적용하는지 추론 서버를 직접 불러 본다. 모델 정확성이 아니라 시험 구성의 확인이다."""
    cases = [("Q4", "아니요", "Q4.answer", False, "Q5"),          # 건너뛰기: Q4.answer == false -> Q4_1 건너뜀
             ("Q4", "네 있어요", "Q4.answer", True, "Q4_1"),
             ("Q7", "네 안 마셔요", "Q7.does_not_drink", True, "Q8_1"),   # Q7_1, Q7_2 건너뜀
             ("Q8_1", "없어요", "Q8_1.days", 0, "Q9_1"),          # Q8_2 건너뜀
             ("Q8_1", "3일이요", "Q8_1.days", 3, "Q8_2"),
             ("Q2.D01", "네 있어요", "Q2.D01.family_history", True, "Q2.D02")]
    for qid, utt, key, val, nxt in cases:
        ein = {"question_id": qid, "current_question": f"시험 문항 {qid}입니다.", "user_utterance": utt, "state": {}}
        validate("ActionExtractionInput", ein)
        c, body, h = ms_call(f"/v1/releases/{new}/extract", ein, tok); assert c == 200, (qid, c, body[:200])
        out = json.loads(body); validate("ActionExtraction", out)
        EA.check_fake_extraction(out, key, val, nxt, f"[{qid} '{utt}']")
    return f"{len(cases)}건(Q4 아니요 -> Q4.answer=false·Q4_1 건너뜀, Q7 -> Q8_1, Q8_1 없어요 -> days=0·Q8_2 건너뜀 등)"

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
    fvc = fake_values_check(new, ms_tok)
    # 서비스를 거친 값 있는 턴: 가짜 A 가 매 턴 값(ANSWERED)을 내고, 서비스의 검증·저장을 통과해야 한다(실패 신호 없음, 추론 실패·형식 위반 증가 없음, Trace 전송)
    sv = f"sess-{RID}-val"; assert kiosk("/v1/sessions", {"session_id": sv, "kind": "SESSION_START"})[0] == 200
    rb = survey_ready()[1]; replies = []
    for i, text in enumerate(("네 있어요", "아니요 없어요", "네 있어요"), 1):
        c, rp = public_turn(sv, f"val-{i}", text); assert c == 200, (c, rp); validate_survey("FrontendInput", rp); replies.append(rp)
    wait(lambda: survey_ready()[1]["trace_outbox"]["sent"] - rb["trace_outbox"]["sent"] >= len(replies) or None, 30, "값 있는 턴의 Trace 전송")
    EA.check_turns_clean(replies, rb, survey_ready()[1])
    kiosk(f"/v1/sessions/{sv}/end", {"session_id": sv, "kind": "SESSION_END"})
    rec("5g", "REAL", f"가짜 A 의 값 추출(흐름 파일 slots/skips): 직접 호출 {fvc}. 서비스 경유 값 있는 3턴(Q1.D01~: '네 있어요','아니요 없어요','네 있어요'): 실패 신호 없음(검증 통과·쓰기 확정), /readyz inference 의 failures·output_invalid·retries·timeouts·outcome_fallback 증가 0, 턴마다 Trace 전송. 모델은 가짜(정확성 아님, 시험 구성 확인). 한계: 저장된 값을 돌려주는 공개 읽기 경로가 없고(PUBLIC_API 에 없음) ops-feedback 은 실패 사례만 노출하므로 저장 값 자체는 단언하지 않았다. 가짜 A 는 CORRECT 를 내지 않아 정정은 시험하지 않았다")
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
    # D85 F절: 기기 토큰 없음·틀린 토큰·서비스 kiosk 토큰을 기기 토큰으로 쓰기는 모두 401, 올바른 기기 토큰은 통과
    for lab, tk in (("토큰 없음", None), ("틀린 토큰", "0" * 48), ("서비스 kiosk 토큰", TOK("survey-api-kiosk"))):
        assert http("POST", "gw", "/v1/sessions", tk, {"session_id": f"sess-{RID}-nodev", "kind": "SESSION_START"})[0] == 401, f"기기 토큰 없이 키오스크 API가 열려 있다({lab})"
    # D85 E절: 개별 계정과 역할. 직원 개입·직원 API는 staff 계정만(다른 역할 403), 운영자 경로는 operator 계정만(없으면 401, 다른 역할 403)
    assert gw_raw("GET", "/v1/staff/alerts", basic=OPERATOR())[0] == 403, "operator 계정이 직원 API를 부를 수 있다"
    assert gw_raw("GET", "/v1/staff/alerts", basic=ADMIN())[0] == 403, "승인자 계정이 직원 API를 부를 수 있다"
    assert gw_raw("POST", "/v1/activate", {})[0] == 401 and gw_raw("POST", "/v1/rollback", {})[0] == 401, "운영자 경로가 인증 없이 열려 있다"
    for nm, acct in (("staff", STAFF()), ("release-approver", ADMIN()), ("reviewer", REVIEWER())):
        assert gw_raw("POST", "/v1/activate", {}, basic=acct)[0] == 403 and gw_raw("POST", "/v1/rollback", {}, basic=acct)[0] == 403, f"{nm} 계정이 운영자 경로를 부를 수 있다"
    for pth in ("/v1/activate", "/v1/rollback"):
        c, b, _ = gw_raw("POST", pth, {}, basic=OPERATOR())
        assert c not in (401, 403) and not isinstance(b, str), f"operator 계정의 {pth} 가 게이트까지 가지 않았다: {c} {str(b)[:80]}"   # 게이트웨이의 404는 평문 'not found', 게이트의 오류는 JSON
    assert gw_raw("GET", "/v1/activate", basic=OPERATOR())[0] == 404, "GET /v1/activate 가 열려 있다"
    # CR-004: 조회 두 경로도 operator 계정만(없으면 401, 다른 역할 403), 번들 경로는 닫혀 있다
    for pth in ("/v1/active-pointer", "/v1/releases"):
        assert gw_raw("GET", pth)[0] == 401, f"{pth} 가 인증 없이 열려 있다"
        assert gw_raw("GET", pth, basic=ADMIN())[0] == 403 and gw_raw("GET", pth, basic=STAFF())[0] == 403, f"{pth} 가 operator 밖 계정에 열려 있다"
        c, b, hd = gw_raw("GET", pth, basic=OPERATOR()); assert c == 200 and not isinstance(b, str), f"operator 의 {pth} 조회 실패 {c} {str(b)[:80]}"
        assert hd.get("Cache-Control", "").lower() == "no-store", f"{pth} 응답의 Cache-Control 이 no-store 가 아니다: {hd.get('Cache-Control')}"
    assert gw_raw("GET", "/v1/releases/x/bundle", basic=OPERATOR())[0] == 404, "번들 경로가 열려 있다"
    assert gw_text("/staff/", OPERATOR())[0] == 403, "operator 계정이 직원 콘솔 화면을 연다"
    # 직원 개입은 서비스에 직접(내부 경로)만: 키오스크 토큰은 403, 직원 토큰은 멈추지 않은 세션에 409(PUBLIC_API.md)
    ib = {"session_id": sid, "decision": "RESUME", "turn_id": "i1"}
    assert http("POST", "survey", f"/v1/sessions/{sid}/intervention", KDEV(), ib)[0] == 403, "키오스크 토큰으로 직원 개입이 열림"
    # D85: 서비스는 개입의 행위자를 게이트웨이가 붙인 X-Openit-User 로 정한다(없으면 401). 내부 직접 호출에는 헤더를 직접 붙인다
    def survey_intervene(user):
        rq = urllib.request.Request(URL("survey") + f"/v1/sessions/{sid}/intervention", data=json.dumps(ib).encode(), method="POST")
        rq.add_header("Authorization", "Bearer " + TOK("survey-api-staff")); rq.add_header("Content-Type", "application/json")
        if user is not None: rq.add_header("X-Openit-User", user)
        try:
            with urllib.request.urlopen(rq, timeout=30) as r: return r.status, r.read().decode(errors="replace")[:200]
        except urllib.error.HTTPError as e: return e.code, e.read().decode(errors="replace")[:200]
    c0, b0 = survey_intervene(None); assert c0 == 401, f"헤더 없는 직원 개입이 401이 아님: {c0} {b0}"
    c1, b1 = survey_intervene(STAFF()[0]); assert c1 == 409, f"멈추지 않은 세션의 개입이 409가 아님: {c1} {b1}"
    assert http("GET", "gw", f"/v1/sessions/{sid}/turns", KDEV())[0] in (404, 405)
    c, en = kiosk(f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"}); assert c == 200, (c, en); validate_survey("FrontendInput", en)
    # 서비스가 턴마다 Trace를 I6로 보냈는지(outbox 전송 수)
    sent = wait(lambda: (lambda cr: cr[1]["trace_outbox"]["sent"] if cr[1]["trace_outbox"]["sent"] >= 2 else None)(survey_ready()), 30, "Trace 전송")
    STATE["sess_a"] = sid; save()
    rec(5, "REAL", f"게이트웨이 경유 공개 API(Bearer 토큰, 없으면 401): 세션 시작·발화 2턴·종료, 응답 FrontendInput 스키마 통과, 같은 turn_id 재시도는 같은 응답, 게이트웨이는 토큰 없이 부른 키오스크 요청에 kiosk 토큰을 붙이고(survey 직접 호출은 토큰 없으면 401), 직원 개입은 인증 없으면 401, survey에서 키오스크 토큰은 403·직원 토큰은 멈추지 않은 세션에 409. 실제 survey-service가 게이트 포인터를 HTTP로 폴링해 릴리스 {new} 적재(번들 해시 검증)하고 턴마다 Trace를 I6로 전송(outbox sent={sent}). 한 턴이 model-serving 컨테이너(I9 v2: 서비스 -> PUT 적재 -> extract(JSON) -> respond(text))를 거쳤다(고정 출력 '(가짜 응답)' 확인, /v1/info loaded, 토큰 없으면 거부). 서버 직접 호출: {v2chk}. 추론 서버를 멈추면 그 턴만 실패하고 서비스는 살아 있으며 다시 띄우면 다음 턴이 복구된다. 모델은 fake 백엔드와 시험용 번들(TEST-SUB)")

def step5c():
    title("5c", "정정(CORRECT) 흐름: 값이 있는 턴 뒤 정정 발화 -> 서비스가 CORRECT 를 처리한다 (가짜 A 의 corrections, model-runtime 0.7.2)")
    if "pointers" not in STATE: rec("5c", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    new = STATE["releases"]["2"]
    wait(lambda: (lambda cr: cr[0] == 200 and cr[1].get("active_release") == new)(survey_ready()), 300, f"survey가 릴리스 {new} 적재", every=3)
    # (1) 추론 서버 직접: 정정 발화는 at 문항(Q1.D02)에서만 CORRECT, 다른 문항에서는 일반 값 추출
    tok = INF_TOK(); utt = "아까 말한 거 아니에요"
    def ext(qid, text, state):
        ein = {"question_id": qid, "current_question": f"시험 문항 {qid}입니다.", "user_utterance": text, "state": state}
        validate("ActionExtractionInput", ein)
        c, body, _ = ms_call(f"/v1/releases/{new}/extract", ein, tok); assert c == 200, (qid, c, body[:200])
        out = json.loads(body); validate("ActionExtraction", out); return out
    o1 = ext("Q1.D02", utt, {"Q1.D01.diagnosed": {"value": True, "status": "ANSWERED"}})
    assert o1["action"] == "CORRECT" and o1["next_item"] == "Q1.D02", o1
    (cv,) = o1["values"]; assert (cv["key"], cv["value"], cv["status"], cv["save"]) == ("Q1.D01.diagnosed", False, "CORRECTION", True), cv
    o2 = ext("Q1.D03", utt, {}); assert o2["action"] == "NEXT" and o2["values"][0]["status"] == "ANSWERED", ("at 가 다른 문항인데 CORRECT 가 나왔다", o2)
    # (2) 서비스 경유: Q1.D01 에 '네' -> 저장, 다음 턴에 정정 발화
    sid = f"sess-{RID}-corr"; assert kiosk("/v1/sessions", {"session_id": sid, "kind": "SESSION_START"})[0] == 200
    rb = survey_ready()[1]
    c, r1 = public_turn(sid, "cor-1", "네 있어요"); assert c == 200, (c, r1); validate_survey("FrontendInput", r1)
    v1 = {v["key"]: v for v in gws("GET", f"/v1/staff/sessions/{sid}")[1]["values"]}
    assert v1["Q1.D01.diagnosed"]["value"] is True and v1["Q1.D01.diagnosed"]["status"] == "ANSWERED", v1
    c, r2 = public_turn(sid, "cor-2", utt); assert c == 200, (c, r2); validate_survey("FrontendInput", r2)
    wait(lambda: survey_ready()[1]["trace_outbox"]["sent"] - rb["trace_outbox"]["sent"] >= 2 or None, 30, "정정 턴의 Trace 전송")
    EA.check_turns_clean([r1, r2], rb, survey_ready()[1])
    c, sv = gws("GET", f"/v1/staff/sessions/{sid}"); assert c == 200, (c, sv); validate_survey("StaffSessionView", sv)
    said = [t for t in sv["turns"] if t["utterance"]]
    assert [t["action"] for t in said] == ["NEXT", "CORRECT"], ("턴 기록의 action", [(t["turn_id"], t["action"]) for t in said])
    v2 = {v["key"]: v for v in sv["values"]}
    assert v2["Q1.D01.diagnosed"]["value"] is False and v2["Q1.D01.diagnosed"]["status"] == "CORRECTION", ("정정이 저장 값에 반영되지 않았다", v2["Q1.D01.diagnosed"])
    assert sv["status"] == "IN_PROGRESS", sv["status"]
    # (3) 대조: 같은 발화가 at 이 아닌 문항(Q1.D01)에서는 정정이 아니다
    sid2 = f"sess-{RID}-corr-ctl"; assert kiosk("/v1/sessions", {"session_id": sid2, "kind": "SESSION_START"})[0] == 200
    c, r3 = public_turn(sid2, "ctl-1", utt); assert c == 200, (c, r3)
    sv3 = gws("GET", f"/v1/staff/sessions/{sid2}")[1]; said3 = [t for t in sv3["turns"] if t["utterance"]]
    assert [t["action"] for t in said3] == ["NEXT"] and all(v["status"] == "ANSWERED" for v in sv3["values"]), ("at 밖의 발화가 정정으로 처리됨", said3, sv3["values"])
    for s_ in (sid, sid2): kiosk(f"/v1/sessions/{s_}/end", {"session_id": s_, "kind": "SESSION_END"})
    rec("5c", "REAL", "정정 흐름(가짜 A corrections: '아까 말'+at Q1.D02, 키 Q1.D01.diagnosed). 추론 서버 직접: Q1.D02 에서 CORRECT(CORRECTION, 값 false, next_item Q1.D02), Q1.D03 에서는 NEXT. 서비스 경유: 'cor-1' 뒤 직원 세션 조회에서 Q1.D01.diagnosed=true ANSWERED -> 'cor-2' 뒤 턴 기록 action [NEXT, CORRECT], 값 false·status CORRECTION, 세션 IN_PROGRESS, 실패 신호 없음, Trace 전송. 대조 세션(Q1.D01 에서 같은 발화)은 NEXT·ANSWERED. 못 보는 것: 이력의 이전 값(NEW_REVISION)과 다음 질문 문항(공개 조회에 없음)")

# ---- 시간 단언의 상수: 설정(config/Caddyfile, 서비스 문서)에서 도출한 값과 측정 환경별 관찰값을 이름으로 둔다. 단언의 의미(상한 안에 들어와야 한다)는 그대로이고, 한 환경의 측정값을 불변식처럼 쓰지 않는다.
KIOSK_WAIT_S = 10.0          # 키오스크 대기(kiosk-frontend 영역, ADR 0003)
SURVEY_TURN_DEADLINE_S = 6.0 # survey-service 서버 턴 총 마감(SURVEY_TURN_DEADLINE_SECONDS 기본)
GW_DIAL_PROXY_S = 2.0        # 사람용 프록시(proxy_limits) 연결 상한 dial_timeout
GW_READYZ_CAP_S = 3.0        # gateway /readyz 프록시 = 연결 1s + 응답 헤더 2s (Caddyfile)
GW_HDR_GATE_S, GW_HDR_OPS_S = 15.0, 10.0   # 사람용 프록시 응답 헤더 상한: release-gate / ops-feedback-ingest (proxy_limits, 시작값)
DOCKER_DNS_FAIL_S = 3.0      # 멈춘 컨테이너 이름을 Docker 내부 DNS가 해석하지 못하는 지연. 근거: 설정 없는 Caddy가 이름 해석 실패 502를 3.0s 뒤에 냈다(docs/E2E.md 관찰, 한 환경에서 측정)
BASIC_AUTH_S = 2.0           # gateway 기본 인증(bcrypt) 확인 시간의 여유. 관찰: 이 PC 약 0.9s(검토 목록 pause 가 설정 10s 에 10.87s). 근거 기록 없음 이상의 일반화는 하지 않는다
CLIENT_EXTRA_S = 2.0         # 호스트 클라이언트가 gateway 응답을 더 늦게 받는 정도. 관찰: gpu-dev(Docker Desktop 4.50) +0.5~1.9s, 이 PC 0 (docs/E2E.md 5w 계측)
# 연결 거부(상류 stop)가 걸리는 시간의 상한 = dial + Docker DNS 실패 지연 + 여유. 응답 헤더 상한(release-gate 15s)까지 매달리지 않고 그보다 충분히 짧게 끝나야 한다.
# 관찰값: 이 PC 2.7~3.8s, gpu-dev 4.6s. 한 환경의 측정이 아니라 위 설정·관찰에서 도출하되 헤더 상한의 절반 아래(7.5s)로 둔다.
CONN_REFUSED_MAX_S = GW_DIAL_PROXY_S + DOCKER_DNS_FAIL_S + 1.5
assert CONN_REFUSED_MAX_S < GW_HDR_GATE_S / 2, "연결 거부 상한이 응답 헤더 상한에 가까우면 단언이 의미가 없다"
READYZ_PAUSED_MAX_S = GW_READYZ_CAP_S + CLIENT_EXTRA_S   # gateway /readyz 가 무응답 상류에서 504 를 주기까지(클라이언트가 본 시간)
TURN_CLIENT_MAX_S = SURVEY_TURN_DEADLINE_S + CLIENT_EXTRA_S   # 클라이언트가 본 환자 턴 상한(서버 마감 + 호스트 전달 지연), 키오스크 대기(10s)와 gateway 상한(9.5s) 아래

def gwk(method, path, body=None, timeout=30, auth=True):
    """게이트웨이 경유 호출(키오스크 기기 토큰). (상태, 본문, 소문자 헤더, 걸린 초). 연결 오류는 상태 0."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL("gw") + path, data=data, method=method)
    if auth: req.add_header("Authorization", "Bearer " + KDEV())
    if data is not None: req.add_header("Content-Type", "application/json")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: code, raw, hd = r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e: code, raw, hd = e.code, e.read(), dict(e.headers)
    except Exception as e: return 0, type(e).__name__, {}, time.time() - t0
    try: b = json.loads(raw or b"null")
    except ValueError: b = raw.decode(errors="replace")
    return code, b, {k.lower(): v for k, v in hd.items()}, time.time() - t0

def gk_turn(sid, tid, text, timeout=30):
    return gwk("POST", f"/v1/sessions/{sid}/turns", {"session_id": sid, "kind": "UTTERANCE", "utterance": text, "turn_id": tid}, timeout)

def staff_sv(sid):
    c, sv = gws("GET", f"/v1/staff/sessions/{sid}"); assert c == 200, (c, sv); return sv

def utt_count(sv, text): return sum(1 for t in sv["turns"] if t["utterance"] == text)

def policy(step, waits, name, fn):
    """정책 단언: FAULT_POLICY 가 정한 기대인데 지금 영역 코드로는 통과하지 않을 수 있는 것. 통과하면 REAL, 아니면 POLICY-PENDING(실패가 아니다, 기다리는 변경과 지금 값을 적는다). 약화하지 않는다."""
    try: fn(); rec(f"{step}-policy", "REAL", f"정책 단언 통과: {name}")
    except AssertionError as e: rec(f"{step}-policy", "POLICY-PENDING", f"{name} -- 기다리는 변경: {waits}. 지금 값: {e}")

def wait_gw_ready(timeout):
    wait(lambda: gwk("GET", "/readyz", auth=False)[0] == 200, timeout, "gateway /readyz 200(survey-service 가 활성 릴리스까지 적재)", every=2)

def upstream_503_json(c, b, h, what):
    assert c == 503 and b == {"code": "UPSTREAM_UNAVAILABLE"}, f"{what}: 503 UPSTREAM_UNAVAILABLE 이 아니다: {c} {str(b)[:120]}"
    assert h.get("content-type", "").startswith("application/json") and h.get("retry-after"), f"{what}: Content-Type/Retry-After 헤더 {h.get('content-type')} {h.get('retry-after')}"
    assert "survey" not in json.dumps(b) and ":8080" not in json.dumps(b), f"{what}: 본문에 내부 주소"

def step5q():
    title("5q", "survey-service 컨테이너 중지 -> gateway 경유 환자 API 503 UPSTREAM_UNAVAILABLE, gateway /readyz 비정상, /healthz 200 -> 기동 -> 복구, 세션 보존 (FAULT_POLICY 6)")
    if "pointers" not in STATE: rec("5q", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    wait_gw_ready(300)
    svc = f"{a.project}-survey-service-1"; sid = f"sess-{RID}-outq"
    assert kiosk("/v1/sessions", {"session_id": sid, "kind": "SESSION_START"})[0] == 200
    c, r1 = public_turn(sid, "q-1", "네 있어요"); assert c == 200, (c, r1)
    sh([a.docker, "stop", "-t", "3", svc]); obs = {}
    try:
        c, b, h, el = gk_turn(sid, "q-2", "아니요 없어요"); obs["turn"] = (c, round(el, 2)); upstream_503_json(c, b, h, "환자 턴")
        rc, rb_, rh, rel = gwk("GET", "/readyz", auth=False); obs["readyz"] = (rc, round(rel, 2)); assert rc != 200, "survey-service 가 없는데 gateway /readyz 가 200"
        assert "survey" not in json.dumps(rb_) and ":8080" not in json.dumps(rb_), f"gateway /readyz 본문에 내부 정보: {rb_}"
        hc = gwk("GET", "/healthz", auth=False); obs["healthz"] = hc[0]; assert hc[0] == 200, hc[:2]
    finally: sh([a.docker, "start", svc])
    wait(lambda: sh([a.docker, "inspect", "-f", "{{.State.Health.Status}}", svc]).stdout.strip() == "healthy", 120, "survey-service healthy", every=2)
    t0 = time.time(); wait_gw_ready(300); t_rec = time.time() - t0
    sv = staff_sv(sid); vals = {v["key"]: v for v in sv["values"]}
    assert vals["Q1.D01.diagnosed"]["value"] is True, ("재시작 뒤 이전 값이 사라졌다", vals)
    assert utt_count(sv, "아니요 없어요") == 0 and "Q1.D02.diagnosed" not in vals, "상류에 닿지 못한 턴이 기록됐다"
    c, r2 = public_turn(sid, "q-2", "아니요 없어요"); assert c == 200, ("복구 뒤 같은 turn_id 재전송이 200이 아니다", c, r2)
    assert {v["key"]: v for v in staff_sv(sid)["values"]}["Q1.D02.diagnosed"]["value"] is False
    def idem():
        c, again = public_turn(sid, "q-1", "네 있어요"); assert c == 200 and again == r1, ("재시작 뒤 이미 확정된 turn_id 재전송이 저장된 응답과 다르다", c, str(again)[:100])
        assert utt_count(staff_sv(sid), "네 있어요") == 1, "같은 turn_id 가 두 번 기록됐다"
    policy("5q", "survey-service 의 turn_id 멱등(저장된 결과 재생)", "재시작 뒤 확정된 turn_id 재전송은 같은 응답이고 한 번만 기록된다", idem)
    kiosk(f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"})
    rec("5q", "REAL", f"survey-service stop 중 gateway 경유: 환자 턴 {obs['turn'][0]}({obs['turn'][1]}s) {{\"code\":\"UPSTREAM_UNAVAILABLE\"}} + Retry-After + JSON(본문에 내부 주소 없음), gateway /readyz {obs['readyz'][0]}({obs['readyz'][1]}s), /healthz {obs['healthz']}. start 뒤 gateway /readyz 200 까지 {t_rec:.0f}s. 세션 보존(Q1.D01 값 유지, 상류에 닿지 못한 턴은 기록 없음), 같은 turn_id 로 재전송하면 200 으로 확정")

def gw_log_duration(path_part, since):
    """gateway(Caddy) 접근 로그(JSON)에서 path_part 가 든 요청의 서버 쪽 처리 시간(duration, 초)과 상태를 (가장 최근 것으로) 읽는다. 클라이언트와 gateway 사이 전달 지연은 이 값에 들지 않는다."""
    r = sh([a.docker, "logs", "--since", str(int(since) - 1), f"{a.project}-gateway-1"], check=False)
    best = None
    for ln in (r.stdout + r.stderr).splitlines():
        try: d = json.loads(ln)
        except ValueError: continue
        if path_part in d.get("request", {}).get("uri", "") and d.get("duration") is not None: best = (float(d["duration"]), d.get("status"))
    return best

def step5w():
    title("5w", "survey-service 무응답(docker pause) -> gateway 경유 환자 요청이 마감 안에 504 UPSTREAM_UNAVAILABLE -> unpause 후 복구 (FAULT_POLICY 6)")
    if "pointers" not in STATE: rec("5w", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    wait_gw_ready(300)
    svc = f"{a.project}-survey-service-1"; sid = f"sess-{RID}-outw"
    assert kiosk("/v1/sessions", {"session_id": sid, "kind": "SESSION_START"})[0] == 200
    sh([a.docker, "pause", svc]); obs = {}
    try:
        t_req = time.time(); c, b, h, el = gk_turn(sid, "w-1", "네 있어요", timeout=30); obs["turn"] = (c, round(el, 2))
        assert c == 504 and b == {"code": "UPSTREAM_UNAVAILABLE"} and h.get("retry-after"), f"무응답 상류: 504 UPSTREAM_UNAVAILABLE 이 아니다: {c} {str(b)[:100]}"
        # 불변식: 키오스크 대기(10s) > gateway 처리 시간 > 서버 턴 총 마감(6s, survey-service SURVEY_TURN_DEADLINE_SECONDS 기본). 설정은 연결 1s + 응답 헤더 8.5s(합 9.5s 상한, config/Caddyfile).
        # gateway 의 상한은 gateway 자신의 접근 로그 duration 으로 잰다(클라이언트가 본 시간에는 호스트 게시 포트 전달 지연이 섞인다: 아래 정책 단언과 docs/E2E.md 측정표)
        gd = gw_log_duration(f"/v1/sessions/{sid}/turns", t_req); assert gd, "gateway 접근 로그에서 이 요청을 찾지 못했다"
        obs["gw_duration"] = round(gd[0], 2); assert gd[1] == 504, ("gateway 로그의 상태", gd)
        assert SURVEY_TURN_DEADLINE_S <= gd[0] < KIOSK_WAIT_S, f"gateway 처리 시간이 서버 총 마감({SURVEY_TURN_DEADLINE_S}s)~키오스크 대기({KIOSK_WAIT_S}s) 사이가 아니다: {gd[0]:.2f}s"
        rc, rb_, rh, rel = gwk("GET", "/readyz", auth=False); obs["readyz"] = (rc, round(rel, 1))
        assert rc == 504 and rel < READYZ_PAUSED_MAX_S, f"gateway /readyz 가 무응답 상류에서 504 를 {READYZ_PAUSED_MAX_S:.1f}s(설정 {GW_READYZ_CAP_S}s + 클라이언트 지연 여유) 안에 주지 않았다: {rc} {rel:.1f}s"
        hc = gwk("GET", "/healthz", auth=False); obs["healthz"] = hc[0]; assert hc[0] == 200
    finally: sh([a.docker, "unpause", svc])
    t0 = time.time(); wait_gw_ready(60); t_rec = time.time() - t0
    def client_seen(): assert obs["turn"][1] < KIOSK_WAIT_S, f"클라이언트가 본 시간 {obs['turn'][1]}s (gateway 처리 {obs['gw_duration']}s, 차이 {obs['turn'][1]-obs['gw_duration']:.2f}s: 호스트 게시 포트 경유 전달 지연)"
    policy("5w", "Docker Desktop(WSL2) 호스트 게시 포트 전달 지연(운영 서버의 gateway 직접 접속에서는 해당 없음, 미확인)", "호스트 클라이언트가 본 gateway 504 시간이 키오스크 대기(10s) 미만이다", client_seen)
    time.sleep(3)   # 멈춘 사이 도착한 요청을 서비스가 풀린 뒤 처리했을 수 있다
    sv = staff_sv(sid); n_after_unpause = utt_count(sv, "네 있어요")
    c, r = public_turn(sid, "w-1", "네 있어요"); assert c == 200, ("복구 뒤 같은 turn_id 재전송이 200이 아니다", c, r)
    n_final = utt_count(staff_sv(sid), "네 있어요")
    print(f"  관찰: 504 를 받은 턴 w-1 이 unpause 뒤 서비스에서 처리된 횟수 {n_after_unpause}, 같은 turn_id 재전송 뒤 기록 {n_final}회")
    policy("5w", "survey-service 의 turn_id 멱등(처리 중·확정 재전송은 새로 처리하지 않음)", "504 로 끝난 턴을 같은 turn_id 로 재전송해도 발화는 한 번만 기록된다", lambda: (_ for _ in ()).throw(AssertionError(f"기록 {n_final}회")) if n_final != 1 else None)
    kiosk(f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"})
    rec("5w", "REAL", f"survey-service pause 중 gateway 경유: 환자 턴 {obs['turn'][0]} 까지 클라이언트 {obs['turn'][1]}s / gateway 접근 로그 duration {obs['gw_duration']}s (설정: 연결 1s + 응답 헤더 8.5s), gateway /readyz {obs['readyz'][0]}({obs['readyz'][1]}s, 설정 2s), /healthz {obs['healthz']}. unpause 뒤 gateway /readyz 200 까지 {t_rec:.0f}s. 멈춘 사이 요청이 풀린 뒤 서비스에서 처리된 횟수 {n_after_unpause}")

def step5u():
    title("5u", "사람이 쓰는 화면 경로(승인·운영·검토)의 gateway 상류 상한: release-gate 중지/무응답, ops-feedback-ingest 무응답 (FAULT_POLICY 6, config/Caddyfile proxy_limits)")
    gate, ops = f"{a.project}-release-gate-1", f"{a.project}-ops-feedback-ingest-1"
    def call(path, acct, who):
        t0 = time.time(); c, b, h = gw_raw("GET", path, basic=acct); return c, b, time.time() - t0, t0
    def up503(c, b, what): assert c == 503 and b == {"code": "UPSTREAM_UNAVAILABLE"}, f"{what}: 503 UPSTREAM_UNAVAILABLE 이 아니다: {c} {str(b)[:100]}"
    obs = {}
    # (1) release-gate 중지: 승인 조회(C7, release-approver)와 운영자 읽기(C8, operator)가 빨리 503 JSON
    sh([a.docker, "stop", "-t", "3", gate])
    try:
        for lab, path, acct in (("승인 조회 C7", "/v1/submissions", ADMIN()), ("운영자 active-pointer C8", "/v1/active-pointer", OPERATOR())):
            c, b, el, _ = call(path, acct, lab); up503(c, b, lab); assert el < CONN_REFUSED_MAX_S, f"{lab}: 연결 거부인데 {el:.1f}s 걸렸다(상한 {CONN_REFUSED_MAX_S:.1f}s = dial {GW_DIAL_PROXY_S}s + Docker DNS 실패 {DOCKER_DNS_FAIL_S}s + 여유, 응답 헤더 상한 {GW_HDR_GATE_S}s 까지 매달리면 안 된다)"; obs[lab] = (c, round(el, 2))
    finally: sh([a.docker, "start", gate])
    wait(lambda: sh([a.docker, "inspect", "-f", "{{.State.Health.Status}}", gate]).stdout.strip() == "healthy", 120, "release-gate healthy", every=2)
    wait(lambda: gw_raw("GET", "/v1/submissions", basic=ADMIN())[0] == 200, 60, "승인 조회 복구(200)", every=2)
    # (2) release-gate 무응답(pause): gateway 상한 15s(연결 2s + 헤더 15s 설정; 접근 로그 duration 으로 잰다)
    def paused(svc, path, acct, lab, lo, hi):
        sh([a.docker, "pause", svc])
        try:
            c, b, el, t0 = call(path, acct, lab); assert c == 504 and b == {"code": "UPSTREAM_UNAVAILABLE"}, f"{lab}: 504 UPSTREAM_UNAVAILABLE 이 아니다: {c} {str(b)[:100]}"
            gd = gw_log_duration(path, t0); assert gd and gd[1] == 504, f"{lab}: gateway 로그에서 못 찾았다 {gd}"
            assert lo <= gd[0] < hi, f"{lab}: gateway 처리 시간 {gd[0]:.2f}s 가 설정 상한({lo}~{hi}s)과 다르다"
            obs[lab] = (c, round(el, 1), round(gd[0], 2))
        finally: sh([a.docker, "unpause", svc])
    paused(gate, "/v1/submissions", ADMIN(), "승인 조회 pause", GW_HDR_GATE_S - 0.5, GW_HDR_GATE_S + BASIC_AUTH_S)
    wait(lambda: gw_raw("GET", "/v1/submissions", basic=ADMIN())[0] == 200, 60, "승인 조회 복구(200)", every=2)
    paused(ops, "/v1/cases", REVIEWER(), "검토 목록 pause", GW_HDR_OPS_S - 0.5, GW_HDR_OPS_S + BASIC_AUTH_S)
    wait(lambda: gw_raw("GET", "/v1/cases", basic=REVIEWER())[0] == 200, 60, "검토 목록 복구(200)", every=2)
    rec("5u", "REAL", "사람이 쓰는 화면 경로의 gateway 상류 상한: release-gate 중지 중 승인 조회 " + f"{obs['승인 조회 C7']}·운영자 읽기 {obs['운영자 active-pointer C8']}(코드, 초)가 503 {{\"code\":\"UPSTREAM_UNAVAILABLE\"}}; release-gate 무응답 중 승인 조회 {obs['승인 조회 pause']}(코드, 클라이언트 초, gateway duration 초; 설정 헤더 15s), ops-feedback-ingest 무응답 중 검토 목록 {obs['검토 목록 pause']}(설정 헤더 10s)이 504 UPSTREAM_UNAVAILABLE; 해제 뒤 모두 200 복구. 정적 화면(admin-console, kiosk-frontend) 프록시의 상한은 같은 설정이나 이 단계에서 시험하지 않았다")

def step5m():
    title("5m", "model-serving 무응답(docker pause) 중 환자 턴: survey 턴 마감 안에 분류된 실패, 값 미저장, unpause 뒤 같은 turn_id 확정 (FAULT_MATRIX B1, model-runtime 요청 상한)")
    if "pointers" not in STATE: rec("5m", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    wait_gw_ready(300)
    sid = f"sess-{RID}-outm"
    assert kiosk("/v1/sessions", {"session_id": sid, "kind": "SESSION_START"})[0] == 200
    c, r1 = public_turn(sid, "m-1", "네 있어요"); assert c == 200 and not r1.get("turn_failure_signal"), (c, r1)
    sidr = f"sess-{RID}-outmr"; assert kiosk("/v1/sessions", {"session_id": sidr, "kind": "SESSION_START"})[0] == 200
    phrase, _rules = risk_phrase_from_defaults()
    sh([a.docker, "pause", MS_CONTAINER])
    try:
        # 모델 서버가 멈춘 턴에서도 위험 발화의 직원 알림이 먼저 나간다(D88 U1: 규칙 감지는 모델 추출·쓰기 확정과 무관). 추출 호출 없이 정지하므로 마감 안에 끝난다
        t_r = time.time(); cr, rr = public_turn(sidr, "mr-1", f"저는 {phrase} 있어요"); dt_r = time.time() - t_r
        assert cr == 200 and (rr.get("turn_failure_signal") or {}).get("staff_alert") in ("DELIVERED", "DELIVERY_FAILED"), ("모델 서버가 멈췄는데 위험 발화의 직원 알림이 나가지 않았다", cr, str(rr)[:160])
        assert dt_r < TURN_CLIENT_MAX_S, f"위험 정지 턴이 마감을 넘겼다: {dt_r:.1f}s (상한 {TURN_CLIENT_MAX_S}s = 서버 마감 {SURVEY_TURN_DEADLINE_S}s + 클라이언트 지연 여유)"
        assert [x for x in gws("GET", "/v1/staff/alerts?status=OPEN")[1]["items"] if x["session_id"] == sidr], "모델 서버가 멈춘 중의 위험 발화가 직원 알림 목록에 없다"
        t_req = time.time(); c, b, h, el = gk_turn(sid, "m-2", "아니요 없어요", timeout=30)
        failed = c != 200 or (isinstance(b, dict) and b.get("turn_failure_signal"))
        assert failed, ("model-serving 이 멈췄는데 턴이 성공했다", c, str(b)[:120])
        gd = gw_log_duration(f"/v1/sessions/{sid}/turns", t_req); assert gd, "gateway 접근 로그에서 못 찾았다"
        assert gd[0] < SURVEY_TURN_DEADLINE_S + 0.5, f"survey 턴 마감({SURVEY_TURN_DEADLINE_S}s)을 넘겼다: gateway duration {gd[0]:.2f}s (클라이언트 {el:.2f}s)"
        body = json.dumps(b, ensure_ascii=False)[:150] if isinstance(b, dict) else str(b)[:80]
    finally: sh([a.docker, "unpause", MS_CONTAINER])
    wait(lambda: sh([a.docker, "inspect", "-f", "{{.State.Health.Status}}", MS_CONTAINER]).stdout.strip() == "healthy", 60, "model-serving healthy", every=2)
    sv = staff_sv(sid); vals = {v["key"]: v for v in sv["values"]}
    assert vals["Q1.D01.diagnosed"]["value"] is True and "Q1.D02.diagnosed" not in vals, ("멈춘 동안 값이 저장됐거나 이전 값이 사라졌다", vals)
    n_logged = utt_count(sv, "아니요 없어요")
    # 같은 turn_id 재전송(FAULT_POLICY 2: NOT_COMMITTED 로 끝난 턴의 재전송은 확정되어야 한다): 이 PC 관찰은 서비스가 실패 응답(turn_failure_signal NOT_COMMITTED)을 저장해 같은 turn_id 에 계속 같은 실패를 돌려준다 -> 정책 단언(CR-D25)
    tries = []
    for _ in range(4):
        c2, r2 = public_turn(sid, "m-2", "아니요 없어요"); tries.append((c2, r2))
        if c2 == 200 and not r2.get("turn_failure_signal"): break
        time.sleep(3)
    def same_id_confirms(): assert tries[-1][0] == 200 and not tries[-1][1].get("turn_failure_signal"), f"같은 turn_id 재전송 {len(tries)}회 모두 실패 응답: {str(tries[-1][1])[:150]}"
    policy("5m", "survey-service: NOT_COMMITTED 로 끝난 턴의 turn_id 재전송이 새로 처리되도록(CR-D25)", "model-serving 정지로 실패한 턴을 unpause 뒤 같은 turn_id 로 재전송하면 확정된다", same_id_confirms)
    # 서비스 자체의 복구는 새 turn_id 로 확인한다(하드 단언): 값이 한 번 저장된다
    if not (tries[-1][0] == 200 and not tries[-1][1].get("turn_failure_signal")):   # 같은 turn_id 가 확정되지 않았을 때만(확정됐다면 이미 저장돼 중복 기록이 된다)
        def new_id():
            c3, r3 = public_turn(sid, "m-3", "아니요 없어요"); return c3 == 200 and not r3.get("turn_failure_signal")
        wait(new_id, 60, "unpause 뒤 새 turn_id 턴 확정", every=3)
    sv2 = staff_sv(sid); assert {v["key"]: v for v in sv2["values"]}["Q1.D02.diagnosed"]["value"] is False, "복구 뒤 값이 저장되지 않았다"
    n_final = utt_count(sv2, "아니요 없어요")
    # model-runtime 요청 상한(MODEL_RUNTIME_REQUEST_DEADLINE_S 3.5s)과 엔진 멈춤 시 /readyz 503 은 pause 로는 볼 수 없다(컨테이너가 통째로 얼어 /readyz 도 응답하지 못한다).
    # 이 이미지가 그 코드를 가졌는지는 라벨의 model-runtime 태그로만 안다: 태그가 73e79f9(요청 상한) 이후를 포함해야 한다.
    chk_ = subprocess.run(["bash", str(ROOT / "scripts/check-health.sh"), "--project", a.project, "--skip-backup", "--disk-path", str(WORK), "--scheduler-state", str(WORK / "none.json"), "--jobs", str(ROOT / "config/jobs.yaml")], capture_output=True, text=True)
    lines = chk_.stdout.splitlines(); gate_l = [l for l in lines if "release-gate 판정 루프" in l]; ms_l = [l for l in lines if "readyz model-serving" in l]
    assert ms_l and ms_l[0].startswith("OK"), ("check-health 의 model-serving 판정", ms_l)
    assert gate_l and not gate_l[0].startswith(("CRIT", "SKIP")), ("check-health 의 release-gate 판정 루프", gate_l)
    rec("5m", "REAL", f"model-serving pause 중 환자 턴(gateway 경유): 상태 {c}, gateway duration {gd[0]:.2f}s(survey 턴 마감 6s 안), 실패 응답 {body}; 위험 발화는 같은 모델 정지 중에도 직원 알림(staff_alert)이 먼저 나갔다({dt_r:.1f}s); 값 저장 없음(Q1.D01 유지, Q1.D02 없음), 중지 중 발화 기록 {n_logged}건; unpause 뒤 새 turn_id 턴은 확정(값 저장, 서비스 복구); 같은 turn_id(m-2) 재전송은 정책 단언(survey-service 가 실패 응답을 저장해 계속 NOT_COMMITTED 를 돌려주면 POLICY-PENDING, CR-D25). 발화 기록 {n_final}건. 실제 스택의 check-health --project 가 model-serving /readyz OK, release-gate 판정 루프 '{gate_l[0][5:60].strip()}...'를 읽었다. 못 보는 것: model-runtime 요청 상한 3.5s·엔진 멈춤 시 /readyz 503(pause 로는 컨테이너가 통째로 얼어 볼 수 없고, 이 E2E 이미지의 model-runtime 태그에 상한 코드가 들어 있는지는 docs/E2E.md 참고)")

AUTHOR = lambda: ("author-e2e", TOK("account-author-e2e-password"))        # 저자 경로 계정(역할 author)
CLINICAL = lambda: ("clinical-e2e", TOK("account-clinical-e2e-password"))   # 임상 근거 검수자(역할 clinical-reviewer, 저자와 다른 주체)
def gw_bytes(method, path, data, ctype, basic=None, headers=None):
    """게이트웨이 경유 원문 본문 호출(자료 업로드). (상태, JSON 또는 문자열, 헤더)"""
    req = urllib.request.Request(URL("gw") + path, data=data, method=method)
    if basic: req.add_header("Authorization", "Basic " + __import__("base64").b64encode(f"{basic[0]}:{basic[1]}".encode()).decode())
    if data is not None: req.add_header("Content-Type", ctype)
    for k, v in (headers or {}).items(): req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as r: b = r.read(); return r.status, json.loads(b or b"null"), dict(r.headers)
    except urllib.error.HTTPError as e:
        b = e.read()
        try: return e.code, json.loads(b), dict(e.headers)
        except Exception: return e.code, b.decode(errors="replace"), dict(e.headers)

def step5a():
    title("5a", "저자 경로(question-authoring)를 gateway 기본 인증 뒤에서: 자료 등록·확인(author), 임상 근거 승인(clinical-reviewer), 자기 승인 403, 본문 상한 (D88/U9)")
    qset = f"qs-{RID}-gwauthor"; form = (ROOT / "test/fixtures/question-form-v2.txt").read_bytes()
    up = f"/v1/materials?question_set_id={qset}&filename=gw.txt"
    assert gw_bytes("POST", up, form, "text/plain")[0] == 401, "인증 없이 저자 경로가 열려 있다"
    assert gw_bytes("POST", up, form, "text/plain", basic=STAFF())[0] == 403, "author 역할이 아닌 계정(staff)이 저자 경로를 쓸 수 있다"
    c, d, _ = gw_bytes("POST", up, form, "text/plain", basic=AUTHOR(), headers={"X-Openit-User": "spoofed-user", "Authorization-X": "x"}); assert c in (200, 201), ("자료 등록", c, d)
    c, pv, _ = gw_raw("GET", f"/v1/drafts/{d['draft_id']}/preview", basic=AUTHOR()); assert c == 200 and pv["ready_to_confirm"], (c, pv)
    c, ref, _ = gw_raw("POST", f"/v1/drafts/{d['draft_id']}/confirm", {"preview_hash": pv["preview_hash"]}, basic=AUTHOR()); assert c == 200, ("확인", c, ref)
    # 4-eyes: 저자는 자기 확인을 임상 승인하지 못하고, 검수자의 위조 X-Openit-User 는 무시되어 인증 계정이 기록된다
    body = {"question_set": ref, "decision": "APPROVED", "clinical_basis_approved": True, "reason": "E2E 시험용 임상 근거 승인(TEST-SUB)"}
    c, e, _ = gw_raw("POST", "/v1/reviews", body, basic=AUTHOR()); assert c == 403, ("저자가 자기 확인을 임상 승인했다", c, e)
    c, r_, _ = gw_raw("POST", "/v1/reviews", body, basic=CLINICAL(), headers={"X-Openit-User": AUTHOR()[0]}); assert c in (200, 201), ("임상 승인", c, r_)
    revs = list(qa_reader().get_reviews(ref)); assert len(revs) == 2, len(revs)
    assert revs[-1]["clinical_basis_approved"] is True and revs[-1]["reviewer_id"] == CLINICAL()[0], ("위조 헤더가 무시되고 인증 계정이 기록돼야 한다", revs[-1])
    assert dict(qa_reader().latest(qset, reviewed_only=True))["version"] == ref["version"], "임상 승인 뒤 reviewed_only 에 나타나야 한다"
    # 이웃 읽기 면(I1)은 gateway 에 열지 않는다. 본문 상한 8MiB 초과는 413
    assert gw_raw("GET", "/v1/question-sets", basic=AUTHOR())[0] == 404, "I1 읽기 면이 gateway 에 열려 있다"
    # Caddy 는 상한을 넘는 본문을 읽다가 413 으로 끊는다. 클라이언트가 아직 보내는 중이면 응답을 받기 전에 연결이 끊겨(SSL EOF·연결 재설정) 상태 코드를 못 읽기도 한다: 둘 다 '거부됨'으로 본다(정상 업로드가 아님)
    try: c9 = gw_bytes("POST", up, b"x" * (9 * 1024 * 1024), "text/plain", basic=AUTHOR())[0]
    except (urllib.error.URLError, ConnectionError, OSError) as e9: c9 = f"연결 끊김({type(e9).__name__})"
    assert c9 == 413 or isinstance(c9, str), ("8MiB 초과 본문이 거부되지 않았다", c9)
    rec("5a", "REAL", f"저자 경로(gateway 경유, 개별 계정): 인증 없음 401, 역할 없는 계정 403, author 계정의 자료 등록·미리보기·확인(문항 세트 {qset}@{ref['version']}), 저자의 자기 임상 승인 403(4-eyes), clinical-reviewer 계정의 승인 200(위조 X-Openit-User 는 무시되고 reviewer_id={CLINICAL()[0]} 가 기록됨), 승인 뒤 reviewed_only 최신 버전, I1 읽기 면 404, 9MiB 본문 거부({c9})")

def dev_tok(d): return TOK(f"kiosk-device-{d}")
def step5d():
    title("5d", "기기별 키오스크 토큰(D88/U8): 기기 A가 만든 세션에 기기 B는 접근하지 못한다, 폐기된 기기 토큰은 거부, 공유 토큰 경고 없음")
    if "pointers" not in STATE: rec("5d", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    wait_gw_ready(300)
    sid = f"sess-{RID}-devA"; A, B = dev_tok("e2e-a"), dev_tok("e2e-b")
    def gk(tok, method, path, body=None):
        req = urllib.request.Request(URL("gw") + path, data=json.dumps(body).encode() if body is not None else None, method=method)
        req.add_header("Authorization", "Bearer " + tok)
        if body is not None: req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r: return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            b = e.read()
            try: return e.code, json.loads(b)
            except Exception: return e.code, b.decode(errors="replace")
    print("  진단: 기기별 /v1/sessions 응답 코드 " + ", ".join(f"{d}={gk(dev_tok(d), 'POST', '/v1/sessions', {'session_id': 'sess-diag-' + d, 'kind': 'SESSION_START'})[0]}" for d in ("e2e", "e2e-a", "e2e-b", "e2e-c")))
    c, st = gk(A, "POST", "/v1/sessions", {"session_id": sid, "kind": "SESSION_START"}); assert c == 200, ("기기 A 세션 시작", c, st)
    c, r = gk(A, "POST", f"/v1/sessions/{sid}/turns", {"session_id": sid, "kind": "UTTERANCE", "utterance": "네 있어요", "turn_id": "dA-1"}); assert c == 200, ("기기 A 발화", c, r)
    cs, _ = gk(A, "GET", f"/v1/sessions/{sid}/state"); assert cs in (200, 429), ("기기 A 상태 조회", cs)
    # 기기 B 는 같은 session_id 로 상태·발화·종료를 시도해도 세션에 접근하지 못한다(계약상 404, 존재를 드러내지 않는다)
    time.sleep(1)
    for lab, m, pth, bd in (("상태", "GET", f"/v1/sessions/{sid}/state", None),
                            ("발화", "POST", f"/v1/sessions/{sid}/turns", {"session_id": sid, "kind": "UTTERANCE", "utterance": "아니요 없어요", "turn_id": "dB-1"}),
                            ("종료", "POST", f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"})):
        cb, rb = gk(B, m, pth, bd); assert cb in (404, 403), (f"기기 B 가 기기 A 의 세션에 {lab} 접근이 허용됐다", cb, str(rb)[:100])
    sv = staff_sv(sid); assert utt_count(sv, "아니요 없어요") == 0 and sv["status"] == "IN_PROGRESS", "기기 B 의 시도가 세션을 바꿨다"
    c, r2 = gk(A, "POST", f"/v1/sessions/{sid}/turns", {"session_id": sid, "kind": "UTTERANCE", "utterance": "아니요 없어요", "turn_id": "dA-2"}); assert c == 200, ("기기 A 는 계속 정상이어야 한다", c, r2)
    # 공유 서비스 토큰(survey-api-kiosk) 경로는 없다: 알림 없이 /readyz 에 shared_kiosk_token 이 켜져 있지 않다
    rz = survey_ready()[1]; kt = rz.get("kiosk_tokens") or {}
    assert kt.get("shared_kiosk_token") is False and (kt.get("device_tokens") or 0) >= 2, ("/readyz 의 기기 토큰 상태", kt)
    # 폐기: 기기 c 를 remove --apply (gateway·survey 재시작) 하면 그 토큰은 거부된다
    C = dev_tok("e2e-c"); c, _ = gk(C, "POST", "/v1/sessions", {"session_id": f"sess-{RID}-devC", "kind": "SESSION_START"}); assert c == 200, ("폐기 전 기기 C 는 정상이어야 한다", c)
    env = {"SECRETS_DIR": a.secrets, "DEPLOY_PROJECT": a.project}
    sh(["bash", str(ROOT / "scripts/kiosk-add-device.sh"), "remove", "e2e-c", "--apply"], env=env)
    wait_gw_ready(300)
    cc, _ = gk(C, "POST", "/v1/sessions", {"session_id": f"sess-{RID}-devC2", "kind": "SESSION_START"}); assert cc == 401, ("폐기된 기기 토큰이 거부되지 않는다", cc)
    c, _ = gk(A, "POST", "/v1/sessions", {"session_id": f"sess-{RID}-devA2", "kind": "SESSION_START"}); assert c == 200, "다른 기기는 폐기의 영향을 받지 않는다"
    # 폐기 뒤 시험이 쓰는 비밀 폴더에서 e2e-c 파일이 지워졌고 survey 표에서도 빠졌다
    assert "e2e-c=" not in (pathlib.Path(a.secrets) / "tokens" / "survey-kiosk-device-tokens").read_text(), "survey 기기 토큰 표에 폐기된 기기가 남았다"
    rec("5d", "REAL", "기기별 토큰: 기기 A 가 만든 세션에 기기 B 의 상태·발화·종료는 404/403 이고 세션은 바뀌지 않았다, 기기 A 는 계속 정상, /readyz kiosk_tokens.shared_kiosk_token=false(기기 토큰 표 사용), 기기 C 를 remove --apply 하자 그 토큰은 gateway 401 이고 survey 표에서도 빠졌다(gateway·survey 재시작). 못 보는 것: 폐기가 survey 에 반영되는 시점(재시작 필요, 재시작 전 gateway 가 먼저 막는다)")

def step5r():
    title("5r", "환자 세션 -> 외부 위험 신호 -> 직원 확인·개입 -> 결과 조회 (D85 A~F절, 가짜 모델)")
    if "pointers" not in STATE: rec("5r", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    wait(lambda: survey_ready()[0] == 200, 300, "survey-service 가 활성 릴리스를 적재(/readyz 200)", every=3)   # 단계 5 없이 단독으로 돌려도 되게
    sid = f"sess-{RID}-risk"; subj = f"e2e-subject-{RID}"; utter = "뇌졸중은 없고 약도 안 먹어요"
    RES = lambda: TOK("survey-result-reader"); RSK = lambda: TOK("survey-risk-source")   # 내부 호출용 토큰(게이트웨이에 열지 않는다)
    # (A) 기기 토큰으로 세션 시작(subject_ref), 발화 한 턴
    c, st = kiosk("/v1/sessions", {"session_id": sid, "kind": "SESSION_START", "subject_ref": subj}); assert c == 200, (c, st); validate_survey("FrontendInput", st)
    c, tr = public_turn(sid, "rk-1", utter); assert c == 200, (c, tr)
    # (D) 위험 신호: risk-source 토큰으로 서비스에 직접. 다른 역할 토큰은 403, 게이트웨이에는 열려 있지 않다
    sig = {"signal_id": f"sig-{RID}-1", "source": "e2e-detector", "code": "TEST_RISK", "severity": "RISK"}
    for lab, tk in (("kiosk", KDEV()), ("staff", TOK("survey-api-staff")), ("result-reader", RES())):
        assert http("POST", "survey", f"/v1/sessions/{sid}/risk-signals", tk, sig)[0] in (401, 403), f"{lab} 토큰으로 위험 신호 입력이 열림"
    assert http("POST", "gw", f"/v1/sessions/{sid}/risk-signals", KDEV(), sig)[0] in (403, 404), "위험 신호 입력이 게이트웨이를 통과함"
    c, r1 = http("POST", "survey", f"/v1/sessions/{sid}/risk-signals", RSK(), sig); assert c == 201, (c, r1)
    assert r1["session_status"] == "PAUSED_RISK" and r1["alert_id"], r1
    c, r2 = http("POST", "survey", f"/v1/sessions/{sid}/risk-signals", RSK(), sig); assert c == 200 and r2["alert_id"] == r1["alert_id"], ("같은 signal_id 재전송이 멱등이 아님", c, r2)
    # 직원 알림이 목록에 나온다(게이트웨이 경유, 직원 계정)
    c, pg = gws("GET", "/v1/staff/alerts?status=OPEN"); assert c == 200, (c, pg); validate("StaffAlertPage", pg)
    mine = [x for x in pg["items"] if x["session_id"] == sid and x["alert_id"] == r1["alert_id"]]; assert mine and mine[0]["status"] == "OPEN", ("위험 신호가 알림 목록에 없다", pg["items"][:2])
    assert mine[0]["kind"] == "RISK_STOP", mine[0]   # 목록(StaffAlert)의 kind 는 RISK_STOP, 세션 조회(StaffViewAlert)의 kind 는 RISK(신호 severity)
    # (C) 직원 세션 조회: 대화 기록·값·subject_ref
    c, sv = gws("GET", f"/v1/staff/sessions/{sid}"); assert c == 200, (c, sv); validate_survey("StaffSessionView", sv)
    assert sv["status"] == "PAUSED_RISK" and sv["subject_ref"] == subj and sv["turns"], (sv["status"], sv.get("subject_ref"), len(sv.get("turns", [])))
    va = [al for al in sv["alerts"] if al["alert_id"] == r1["alert_id"]]; assert va, "직원 세션 조회의 alerts 에 이 알림이 없다"
    assert va[0]["kind"] == "RISK" and va[0]["rule_id"] == "e2e-detector:TEST_RISK", va[0]
    assert gw_raw("GET", f"/v1/staff/sessions/{sid}", basic=OPERATOR())[0] == 403, "operator 계정이 직원 세션 조회를 부를 수 있다"
    # (E) 직원 개입(RESUME): 행위자는 게이트웨이가 붙인 헤더의 계정, 본문의 staff_id 는 무시
    # 본문은 InterventionDecision(+turn_id 봉투)뿐이다(additionalProperties false: staff_id 를 실으면 400). 행위자는 헤더가 정본이므로 위조 X-Openit-User 를 실어도 인증 계정이 기록되어야 한다
    c, iv, _ = gw_raw("POST", f"/v1/sessions/{sid}/intervention", {"session_id": sid, "decision": "RESUME", "turn_id": "iv-1"}, basic=STAFF(), headers={"X-Openit-User": "spoofed-staff"}); assert c == 200, (c, iv)
    c, sv2 = gws("GET", f"/v1/staff/sessions/{sid}"); assert c == 200, (c, sv2); validate_survey("StaffSessionView", sv2)
    res = [al.get("resolved_by") for al in sv2["alerts"] if al["alert_id"] == r1["alert_id"]]
    assert res == [STAFF()[0]], f"alerts[].resolved_by 가 인증된 직원 ID가 아니다: {res}"
    assert sv2["status"] == "IN_PROGRESS", sv2["status"]
    c, en = kiosk(f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"}); assert c == 200, (c, en)
    # (B) 결과 조회: result-reader 토큰. subject_ref·상태·answers 는 있고 환자 발화 원문은 없다
    c, rs = http("GET", "survey", f"/v1/results/{sid}", RES()); assert c == 200, (c, rs); validate_survey("SessionResult", rs)
    assert rs["subject_ref"] == subj and rs["status"].startswith("ENDED") and isinstance(rs["answers"], list), rs
    assert utter not in json.dumps(rs, ensure_ascii=False), "결과 조회 응답에 환자 발화 원문이 있다"
    c, lst = http("GET", "survey", f"/v1/results?subject_ref={subj}", RES()); assert c == 200 and any(x["session_id"] == sid for x in lst["items"]), (c, str(lst)[:150])
    for lab, tk in (("kiosk", KDEV()), ("staff", TOK("survey-api-staff")), ("risk-source", RSK())):
        assert http("GET", "survey", f"/v1/results/{sid}", tk)[0] in (401, 403), f"{lab} 토큰으로 결과 조회가 열림"
    for pth in (f"/v1/results/{sid}", f"/v1/results?subject_ref={subj}"):
        assert gw_raw("GET", pth, basic=STAFF())[0] == 404 and gw_raw("GET", pth, basic=OPERATOR())[0] == 404, f"결과 조회 {pth} 가 게이트웨이에 열려 있다"
    # 접근 기록: 읽는 공개 경로가 없다(DB 를 열지 않는다). 기록을 못 남기면 데이터를 주지 않는 설계(fail-closed)라 위 조회 성공이 기록 쓰기 성공을 뜻한다. /readyz 에 접근 기록 항목이 있으면 함께 본다
    c, rz = survey_ready(); acc = {k: v for k, v in (rz or {}).items() if "access" in k.lower()}
    rec("5r", "REAL", f"세션 시작(기기 토큰, subject_ref) -> 발화 -> POST /v1/sessions/{{id}}/risk-signals(risk-source 토큰, 서비스에 직접: 201 PAUSED_RISK, 재전송 200 같은 alert_id, 다른 역할 토큰·게이트웨이 경유는 거부) -> 직원 알림 목록(RISK_STOP, OPEN) -> GET /v1/staff/sessions/{{id}}(직원 계정, 게이트웨이 경유, StaffSessionView 스키마, subject_ref·turns, alerts[].rule_id e2e-detector:TEST_RISK) -> 개입 RESUME(위조 X-Openit-User 무시, alerts[].resolved_by={STAFF()[0]}) -> GET /v1/results/{{id}}·/v1/results?subject_ref(result-reader 토큰, SessionResult 스키마, 발화 원문 없음, 게이트웨이에는 404). 접근 기록: 읽는 경로가 없어 간접 확인(조회 성공 = 기록 성공, /readyz 접근 항목 {sorted(acc) or '없음'}). SSE 수신은 확인하지 않았다(목록으로 확인).")

def step5s():
    title("5s", "어댑터 교체(포인터 1 -> 2)에서 다른 서비스는 그대로이고 새 릴리스가 LOADED 이다")
    before = STATE.get("containers_before_swap")
    if not before or "releases" not in STATE: rec("5s", "BLOCKED", "포인터 교체 전 스냅샷이 없다(단계 4)"); return
    after = container_ids()
    EA.check_unchanged({k: tuple(v) for k, v in before.items()}, after, SWAP_SERVICES)
    new = STATE["releases"]["2"]
    c, st = http("GET", "ms", f"/v1/releases/{new}", INF_TOK()); assert c == 200, (c, st)
    EA.check_release_loaded(st, new)
    rec("5s", "REAL", f"포인터 교체(활성화 2회째) 전후로 {', '.join(SWAP_SERVICES)} 컨테이너의 ID 와 StartedAt 이 같다(docker inspect 의 두 필드만 읽음). model-serving 의 /v1/releases/{new} 가 LOADED(오류 없음). 변경된 것은 model-serving 의 적재 릴리스뿐이다. 어댑터는 시험용 가짜(TEST-SUB)")

def risk_phrase_from_defaults():
    """survey-service 기본(임시) 위험 문구 목록에서 문구 하나를 읽는다(지어내지 않는다). 빌드 사본의 survey_service/risk_rules.py 의 _PROVISIONAL 을 ast 로 읽는다. (문구, 규칙 키 목록)"""
    import ast
    src = (ROOT / "build/ctx/survey-service/survey_service/risk_rules.py").read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_PROVISIONAL" for t in node.targets):
            d = ast.literal_eval(node.value); k = "chest-pain" if "chest-pain" in d else next(iter(d)); return d[k][0], list(d)
    raise AssertionError("risk_rules.py 에서 _PROVISIONAL 을 찾지 못했다")

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
    c2 = http("GET", "survey", "/v1/staff/alerts", KDEV())[0]; assert c2 == 403, f"키오스크 토큰으로 직원 API가 열림 {c2}"
    c3 = http("GET", "gw", "/v1/staff/alerts", TOK("survey-api-kiosk"))[0]; assert c3 in (401, 403), c3   # 클라이언트가 보낸 Authorization은 게이트웨이가 바꾸지 못한 채 인증 없이 거부된다
    c, pg = gws("GET", "/v1/staff/alerts?status=OPEN"); assert c == 200, (c, pg); validate("StaffAlertPage", pg)
    rec("5c", "REAL", f"권한 분리: 인증 없는 키오스크 쪽 호출은 게이트웨이에서 {c1}(직원 API는 기본 인증 필요), survey에 키오스크 토큰으로 직접 부르면 403, 기본 인증 뒤에는 staff 토큰이 붙어 목록 200(StaffAlertPage 스키마). 인증 없는 호출이 403이 아니라 401인 것은 브라우저가 인증 창을 띄우게 하려는 선택이다")
    # (d) 위험 감지는 기본으로 켜져 있다(D88 U1·U2, survey-service ADR-0013): 모든 발화 턴의 원문에 임시 기본 목록(임상 검토 전)을 먼저 적용한다. 알림은 모델 추출·쓰기 확정과 무관하게 먼저 나간다
    c, rz = survey_ready(); sas = rz.get("staff_alert_source") or {}
    assert sas.get("active") is True and sas.get("provisional") is True and sas.get("clinically_reviewed") is False and sas.get("source") == "PROVISIONAL_DEFAULT" and sas.get("rule_count", 0) > 0, f"/readyz 의 staff_alert_source 가 '켜짐, 임시 기본 목록, 임상 검토 전'이 아니다: {sas}"
    phrase, rule_ids = risk_phrase_from_defaults()
    s0 = f"sess-{RID}-risk0"; assert kiosk("/v1/sessions", {"session_id": s0, "kind": "SESSION_START"})[0] == 200
    c, ok_ = public_turn(s0, "rk0-1", "네 있어요"); assert c == 200 and not ok_.get("turn_failure_signal"), ("위험 문구가 없는 발화는 정상 진행해야 한다", c, ok_)
    c, stn = state_of(s0); validate("SessionState", stn); assert stn["state"] == "ACTIVE", ("위험 문구가 없는데 세션이 멈췄다", stn)
    c, pg0 = gws("GET", "/v1/staff/alerts?status=OPEN"); assert not [x for x in pg0["items"] if x["session_id"] == s0], "위험 문구가 없는데 알림이 있다"
    vals_before = staff_sv(s0)["values"]
    risk_text = f"저는 {phrase} 있어요"   # 기본 목록(survey-service risk_rules.py)에서 읽은 위험 문구로 만든 시험 문장
    c, rr = public_turn(s0, "rk0-2", risk_text); assert c == 200, (c, rr); validate_survey("FrontendInput", rr)
    fs = rr.get("turn_failure_signal") or {}
    assert fs.get("staff_alert") in ("DELIVERED", "DELIVERY_FAILED"), ("위험 발화인데 직원 알림 신호가 없다(키오스크가 대기/직원 호출 화면으로 갈 신호)", rr)
    c, stn = state_of(s0); assert stn["state"] == "PAUSED_RISK" or stn.get("status") == "PAUSED_RISK" or "PAUSED" in json.dumps(stn), ("세션이 위험 정지가 아니다", stn)
    c, pg1 = gws("GET", "/v1/staff/alerts?status=OPEN"); validate("StaffAlertPage", pg1)
    mine = [x for x in pg1["items"] if x["session_id"] == s0]; assert mine, "위험 발화인데 직원 알림 목록(OPEN)에 이 세션의 알림이 없다"
    sv0 = staff_sv(s0); assert sv0["status"] == "PAUSED_RISK" and sv0["values"] == vals_before, ("위험 정지 턴의 답이 저장됐거나 상태가 다르다", sv0["status"], sv0["values"], vals_before)
    hits = (survey_ready()[1].get("staff_alert_source") or {}).get("hits_by_rule") or {}; assert sum(hits.values()) >= 1, ("/readyz hits_by_rule 에 적중이 없다", hits)
    kiosk(f"/v1/sessions/{s0}/end", {"session_id": s0, "kind": "SESSION_END"})
    rec("5k", "REAL", f"위험 감지 기본 켜짐(D88 U1·U2): /readyz staff_alert_source active=true, provisional=true, clinically_reviewed=false, 규칙 {sas['rule_count']}개(임시 기본 목록, 임상 검토 전). 위험 문구가 없는 발화는 정상 진행(ACTIVE, 알림 없음). 기본 목록에서 읽은 문구('{phrase}')가 든 발화는 turn_failure_signal.staff_alert={fs.get('staff_alert')}, 세션 PAUSED_RISK, 직원 알림 목록(OPEN)에 나타남, 답은 저장되지 않음, /readyz hits_by_rule 적중 {sum(hits.values())}. 거짓 알림 가능성과 임상 검토 전이라는 한계는 survey-service 문서의 것이다")
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
    c, e = http("POST", "ops", f"/v1/cases/{cid}/review", rv_tok, bad, headers=RVH); assert c == 400, (c, e); validate("BoundaryError", e)
    c, e2 = http("POST", "ops", f"/v1/cases/{cid}/review", rv_tok, {"review_status": "CONFIRMED", "expected": GOOD_EXPECTED}, headers=RVH); assert c == 400, (c, e2)
    assert http("POST", "ops", f"/v1/cases/{cid}/review", TOK("ops-read-synthetic-data"), bad, headers=RVH)[0] == 403, "읽기 토큰으로 검토 게시됨"
    assert http("POST", "ops", f"/v1/cases/nonexistent-case/review", rv_tok, {"review_status": "DISMISSED"}, headers=RVH)[0] == 404
    pi = dict(__import__("copy").deepcopy(STATE["extract_input"])); pi["user_utterance"] = "뇌졸중은 진단받은 적 없어요"   # 개인정보를 뺀 문장으로 검토자가 쓴 입력(시험 자료, ActionExtractionInput)
    badri = {**bad_ok(), "reviewed_input": {"user_utterance": 1}}
    c, eri = http("POST", "ops", f"/v1/cases/{cid}/review", rv_tok, badri, headers=RVH); assert c == 400, ("잘못된 reviewed_input이 받아들여짐", c, eri)
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
    return (HttpReleaseReader(URL("gate"), TOK("gate-read-survey-service")), with_user(HttpGateService(URL("gate"), TOK("gate-write-operator")), "op-test"),
            HttpGateService(URL("gate"), TOK("gate-read-ops-feedback")), with_user(HttpGateService(URL("gate"), TOK("gate-write-release-approver")), "trainer-test"))

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
    for k in sorted(rels): gate_activate(rels[k])
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
        if not cur or cur["release_id"] != rels[k]: cur = gate_activate(rels[k])
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

def demo_active():
    """demo.sh swap-adapters 가 전후에 부른다: 활성 릴리스 포인터(읽기 전용)."""
    title("demo_active", "활성 릴리스 포인터 (읽기 전용)")
    ap = dict(_gate_clients()[0].get_active_pointer())
    print(f"  활성 릴리스 {ap.get('release_id')} pointer_version {ap.get('pointer_version')}")
    rec("demo_active", "REAL", f"활성 릴리스 {ap.get('release_id')} (pointer_version {ap.get('pointer_version')})")

def demo_swap():
    """demo.sh swap-adapters: 새 모델 패키지(LORA_A/LORA_B)를 게시 -> 후보 수집·자동 검사 -> 시험용 승인자(스크립트) 승인 -> 활성화 -> model-serving 만 새 번들을 적재.
    문항 세트는 가장 최근 것을 그대로 쓰고 어댑터 쌍만 바뀐다. 단계 3(make_packages, publish_packages)·5s(container_ids, check_unchanged, check_release_loaded)와 같은 함수를 쓴다."""
    title("demo_swap", "어댑터 교체: 게시 -> 자동 검사 -> 시험용 승인 -> 활성화 -> model-serving 적재")
    if "qs" not in STATE or "dataset" not in STATE: rec("demo_swap", "BLOCKED", "데모 상태(문항 세트·데이터셋)가 없다: demo.sh up 이 먼저"); return
    print("  !! 승인자는 사람이 아니라 이 스크립트가 시험용 release-approver 토큰으로 대신한다(TEST-SUB) !!")
    gate_r, gate_op, gate_rep, gate_ap = _gate_clients()
    before_ptr = dict(gate_r.get_active_pointer())
    pk = make_packages(); refs = publish_packages(pk)
    subj = {"question_set": STATE["qs"][-1], "lora_a": refs["LORA_A"], "lora_b": refs["LORA_B"]}
    snap = container_ids(); assert set(snap) == set(SWAP_SERVICES), f"컨테이너를 찾지 못했다: {sorted(set(SWAP_SERVICES) - set(snap))}"
    ms_before = sh([a.docker, "inspect", "-f", "{{.State.StartedAt}}", MS_CONTAINER], check=False).stdout.strip()
    r = subprocess.run(["bash", str(ROOT / "scripts/run-job.sh"), "job-release-gate-collect"], capture_output=True, text=True)
    assert r.returncode in (0, 75), f"collect 종료 {r.returncode}: {(r.stderr + r.stdout)[-500:]}"
    sub = dict(gate_op.submit_candidate(subj, requested_by_role="operator")); validate("GateSubmission", sub); sid = sub["submission_id"]
    def report_of(x):
        try: return dict(gate_rep.get_review_report(x))
        except bc.BoundaryError: return None
    existing = next((d for d in decisions_for(gate_r, subj) if d["result"] == "PASS"), None)
    if not existing:
        rep = wait_review_report(report_of, sid, "교체 후보"); validate("ReviewReport", rep)
        bad = [c for c in rep["checks"] if c["result"] not in ("PASS", "SKIPPED")]
        assert not bad, f"자동 검사가 통과하지 못했다(승인하지 않고 멈춤): {bad}"
        print("  자동 검사: " + ", ".join(f"{c['kind']}={c['result']}" for c in rep["checks"]))
        dec = dict(gate_ap.decide(sid, "APPROVE", approver_id="trainer-test", approver_role="release-approver", reason="데모: 시험용 승인자(스크립트)가 대신 승인(어댑터 교체)")); validate("GateApproval", dec)
        existing = wait(lambda: next((d for d in decisions_for(gate_r, subj) if d["result"] == "PASS"), None), 30, "승인 뒤 PASS 판정")
    rid = existing.get("release_id"); validate("ReleaseManifest", dict(gate_r.get_release(rid)))
    gate_r.load_bundle(rid, dest=WORK / "bundles")
    unchanged_pointer = before_ptr["release_id"] == rid
    ap = dict(before_ptr) if unchanged_pointer else dict(gate_activate(rid)); validate("ActivePointer", ap)
    r = wait(lambda: (lambda cr: cr[1] if cr[0] == 200 and cr[1].get("active_release") == rid else None)(survey_ready()), 300, f"survey가 릴리스 {rid} 적재", every=3)
    tok = INF_TOK()
    st = wait(lambda: (lambda cs: cs[1] if cs[0] == 200 and cs[1].get("state") in ("LOADED", "FAILED") else None)(http("GET", "ms", f"/v1/releases/{rid}", tok)), 600, f"model-serving 이 {rid} 적재", every=3)
    EA.check_release_loaded(st, rid)
    after = container_ids(); EA.check_unchanged({k: tuple(v) for k, v in snap.items()}, after, SWAP_SERVICES)
    ms_after = sh([a.docker, "inspect", "-f", "{{.State.StartedAt}}", MS_CONTAINER], check=False).stdout.strip()
    print(f"  활성 릴리스: {before_ptr['release_id']} (pointer_version {before_ptr['pointer_version']}) -> {rid} (pointer_version {ap['pointer_version']})" + ("  [이미 활성이었다: 같은 어댑터 쌍, 교체 없음]" if unchanged_pointer else ""))
    print("  컨테이너 StartedAt (전 -> 후):")
    for svc in SWAP_SERVICES: print(f"    {svc:22} {snap[svc][1]} -> {after[svc][1]}  {'불변' if snap[svc] == after[svc] else '바뀜'}")
    print(f"    {'model-serving':22} {ms_before} -> {ms_after}  {'불변' if ms_before == ms_after else '바뀜(컨테이너 재시작)'}")
    print(f"  model-serving 의 릴리스 {rid}: state={st['state']} (LOADED)")
    STATE.setdefault("swaps", []).append({"release_id": rid, "packages": refs}); save()
    rec("demo_swap", "TEST-SUB", f"새 릴리스 {rid} 활성화(승인자는 스크립트가 대신함, TEST-SUB). model-serving 에서 LOADED. {', '.join(SWAP_SERVICES)} 컨테이너의 ID·StartedAt 불변")

def step5p():
    title("5p", "PostgreSQL 컨테이너 중지 -> 서비스 /readyz 비정상 관찰 -> 기동 -> /readyz 복구, 이전 데이터 보존, 새 쓰기 (D85)")
    pg = f"{a.project}-postgres-1"
    svcs = [("qa", "question-authoring"), ("gate", "release-gate"), ("ops", "ops-feedback-ingest"), ("survey", "survey-service")]
    def ready(k):
        try: return http("GET", k, "/readyz")
        except Exception as e: return 0, f"{type(e).__name__}"
    def healthy(k): return ready(k)[0] == 200
    def pgfp(db):
        return sh(["bash", str(ROOT / "scripts/pg-fingerprint.sh"), db], env={"DEPLOY_PROJECT": a.project}).stdout.strip()
    has_release = "pointers" in STATE
    if not has_release:
        # 단독 실행: 활성 릴리스가 없으면 survey-service /readyz 는 DB 가 멀쩡해도 503 no_active_release 이다. 이 단계는 그 경우 survey-service 의 복구를 판정하지 못한다
        svcs = [x for x in svcs if x[0] != "survey"]
        print("  (활성 릴리스가 없어 survey-service 는 제외한다: 단계 4 를 포함해 돌려야 survey-service 복구도 확인된다)")
    # 1) 서비스를 거쳐 데이터를 쓴다(question-authoring 자료 등록 -> 확인). 다른 데이터베이스는 행 지문으로 비교한다
    qset = f"qs-{RID}-pgrestart"
    form = (ROOT / "test/fixtures/question-form-v2.txt").read_text()
    upload(qset, form, "pg1.txt")
    before_v = [dict(v) for v in qa_reader().list_versions(qset)[0]]
    assert len(before_v) == 1, before_v
    dbs = ["qa", "gate", "ops_log", "ops_failure"] + (["survey"] if has_release else [])
    sidp = f"sess-{RID}-pgturn"
    if has_release:
        # 환자 세션: 값이 하나 확정된 상태에서 DB 를 멈춘다. Trace 전송이 끝나기를 기다려 행 지문이 흔들리지 않게 한다
        rb0 = survey_ready()[1]
        assert kiosk("/v1/sessions", {"session_id": sidp, "kind": "SESSION_START"})[0] == 200
        c, _p1 = public_turn(sidp, "p-1", "네 있어요"); assert c == 200, (c, _p1)
        wait(lambda: survey_ready()[1]["trace_outbox"]["sent"] - rb0["trace_outbox"]["sent"] >= 1 or None, 30, "p-1 Trace 전송")
        time.sleep(3)
    fp0 = {d: pgfp(d) for d in dbs}
    for k, n in svcs: assert healthy(k), f"{n} /readyz 가 처음부터 200 이 아니다: {ready(k)}"
    # 2) 중지. /healthz(살아 있음)는 유지되고 /readyz 는 비정상이 되어야 한다
    t0 = time.time(); sh([a.docker, "stop", pg])
    obs = {}   # 서비스 -> (처음 비정상이 관찰된 시각, 코드, 본문 일부)
    def all_down():
        for k, n in svcs:
            if k in obs: continue
            c, b = ready(k)
            if c != 200: obs[k] = (time.time() - t0, c, b if isinstance(b, str) else json.dumps(b, ensure_ascii=False)[:120])
        return len(obs) == len(svcs)
    wait(all_down, 90, "postgres 중지 뒤 모든 서비스의 /readyz 가 비정상(200 아님)", every=1)
    for k, n in svcs:
        sec, c, b = obs[k]; print(f"    {n:22} /readyz {c} ({sec:.0f}s 후) {b}")
    out_turn = None
    if has_release:
        out_turn = gk_turn(sidp, "p-2", "아니요 없어요", timeout=30)   # DB 가 멈춘 동안 환자 턴
        print(f"    환자 턴(DB 중지 중, gateway 경유): 상태 {out_turn[0]} {out_turn[3]:.1f}s 본문 {str(out_turn[1])[:160]}")
    for k, n in svcs:
        hc = http("GET", k, "/healthz")[0]
        assert hc == 200, f"{n} /healthz 가 DB 중지 중 {hc} (살아 있음 점검은 DB 와 무관해야 한다)"
    # 3) 기동하고 복구를 기다린다
    t1 = time.time(); sh([a.docker, "start", pg])
    wait(lambda: sh([a.docker, "inspect", "-f", "{{.State.Health.Status}}", pg], check=False).stdout.strip() == "healthy", 120, "postgres healthy", every=2)
    t_pg = time.time() - t1
    rec_t = {}
    def all_up():
        for k, n in svcs:
            if k not in rec_t and healthy(k): rec_t[k] = time.time() - t1
        return len(rec_t) == len(svcs)
    wait(all_up, 180, "postgres 기동 뒤 모든 서비스의 /readyz 200 복구", every=1)
    # 4) 데이터 보존과 새 쓰기
    fp1 = {d: pgfp(d) for d in dbs}
    diff = [d for d in dbs if fp0[d] != fp1[d]]
    assert not diff, f"재시작 전후 행 지문이 다르다: {diff}"
    after_v = [dict(v) for v in qa_reader().list_versions(qset)[0]]
    assert after_v == before_v, ("문항 버전이 달라졌다", before_v, after_v)
    upload(qset, form.replace("알려 주세요.", "들려 주세요."), "pg2.txt")
    assert len(qa_reader().list_versions(qset)[0]) == 2, "복구 뒤 새 쓰기(버전 2)가 반영되지 않았다"
    turn_note = ""
    if has_release:
        c, b, h, el = out_turn
        # FAULT_POLICY 가 인정한 실패 응답: 재시도 가능한 503 UNAVAILABLE(retryable true). 값이 저장되지 않았음은 아래에서 직원 조회로 본다
        assert c == 503 and isinstance(b, dict) and b.get("code") == "UNAVAILABLE" and b.get("retryable") is True, ("DB 중지 중 환자 턴이 503 UNAVAILABLE(retryable)이 아니다", c, str(b)[:140])
        sv = staff_sv(sidp); vals = {v["key"]: v for v in sv["values"]}
        assert vals["Q1.D01.diagnosed"]["value"] is True, ("확정된 이전 값이 사라졌다", vals)
        assert "Q1.D02.diagnosed" not in vals, "DB 중지 중 턴의 값이 저장됐다(부분 저장)"
        n_logged = utt_count(sv, "아니요 없어요")
        c2, r2 = public_turn(sidp, "p-2", "아니요 없어요"); assert c2 == 200 and not r2.get("turn_failure_signal"), ("복구 뒤 같은 turn_id 재전송이 확정되지 않았다", c2, str(r2)[:120])
        sv2 = staff_sv(sidp); v2 = {v["key"]: v for v in sv2["values"]}
        assert v2["Q1.D02.diagnosed"]["value"] is False, "재전송 뒤 값이 저장되지 않았다"
        turn_note = f" 환자 턴(DB 중지 중): 상태 {c} {el:.1f}s, 응답 {json.dumps(b, ensure_ascii=False)[:110] if isinstance(b, dict) else str(b)[:60]}; 값 저장 없음, 중지 중 발화 기록 {n_logged}건; 복구 뒤 같은 turn_id 재전송은 200 으로 확정(값 1회)."
        def pol_deadline(): assert el <= TURN_CLIENT_MAX_S, f"{el:.1f}s (survey-service 턴 총 마감 {SURVEY_TURN_DEADLINE_S}s + 클라이언트 지연 여유 {CLIENT_EXTRA_S}s)"
        def pol_once(): assert utt_count(sv2, "아니요 없어요") == 1, f"재전송 뒤 같은 발화 기록 {utt_count(sv2, '아니요 없어요')}건(중지 중 {n_logged}건)"
        policy("5p", "survey-service 의 턴 총 마감 시간(6s)과 DB 접속·문장 상한", "DB 중지 중 환자 턴이 총 마감(6s + 클라이언트 지연 여유) 안에 끝난다", pol_deadline)
        policy("5p", "survey-service 의 turn_id 멱등", "실패한 턴을 같은 turn_id 로 재전송하면 발화가 한 번만 기록된다", pol_once)
    detail = ", ".join(f"{n} {obs[k][1]}({obs[k][0]:.0f}s)->200({rec_t[k]:.0f}s)" for k, n in svcs)
    rec("5p", "REAL", f"postgres 컨테이너 stop -> /readyz 비정상 관찰 -> start (healthy {t_pg:.0f}s) -> 복구. 서비스별 중지 뒤 처음 비정상 코드(경과)->복구 200(기동 뒤 경과): {detail}. /healthz 는 중지 중에도 200. 행 지문 보존: {', '.join(dbs)}. 복구 뒤 새 쓰기 반영(question-authoring 버전 2)." + turn_note + ("" if has_release else " survey-service 는 활성 릴리스가 없는 단독 실행이라 제외."))

STEPS = [("1", step1), ("2", step2), ("3", step3), ("4", step4), ("5", step5), ("5s", step5s), ("5f", step5f), ("5c", step5c), ("5a", step5a), ("5d", step5d), ("5q", step5q), ("5w", step5w), ("5u", step5u), ("5m", step5m), ("5r", step5r), ("6", step6), ("7", step7), ("8", step8), ("5p", step5p), ("demo4", demo4), ("demo_activate", demo_activate), ("demo_active", demo_active), ("demo_swap", demo_swap), ("diag", diag)]
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
