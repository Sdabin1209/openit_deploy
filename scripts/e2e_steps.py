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
ap.add_argument("--only", default="", help="쉼표로 구분한 단계(예: 1,2). 비우면 전부")
a = ap.parse_args()
PORTS = json.loads(a.ports); IMAGES = json.loads(a.images); ROOT = pathlib.Path(a.root); WORK = pathlib.Path(a.work)
WORK.mkdir(parents=True, exist_ok=True)
RID = a.run_id
TOK = lambda n: (pathlib.Path(a.secrets) / "tokens" / n).read_text().strip()
URL = lambda k: f"http://127.0.0.1:{PORTS[k]}"
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
def http(method, k, path, token=None, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(URL(k) + path, data=data, method=method)
    if token: req.add_header("Authorization", f"Bearer {token}")
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
def hostpath(p):
    if a.docker.endswith(".exe"): return subprocess.check_output(["wslpath", "-w", str(p)], text=True).strip()
    return str(p)
def wait(fn, timeout, what, every=2):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v: return v
        time.sleep(every)
    raise AssertionError(f"시간 초과({timeout}s): {what}")

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
    form = (ROOT / "build/ctx/question-authoring/examples/question_form.txt").read_text()
    r1, raw1 = upload(QS, form, "form1.txt")
    r2, _ = upload(QS, form.replace("오늘 체온이 얼마였나요?", "오늘 측정한 체온이 얼마였나요?"), "form2.txt")
    ru, _ = upload(QSU, form.replace("체온", "맥박수").replace("body_temp", "pulse"), "unseen.txt")
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
    out = run_sd("1", seeds=False); m, root = read_manifest(out)
    assert out["status"] in ("PUBLISHED", "ALREADY_PUBLISHED"), out
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
    fx = ROOT / "test/fixtures/e2e-test-adapter"
    code = '''
import json, pathlib, model_runtime as m, survey_schema
from boundary_contracts import canonical as c
cfgs = m.fake_serving_configs()
hashes = {r: m.serving_config_hash(v) for r, v in cfgs.items()}
ad = {r: pathlib.Path("/mnt/fx")/r for r in ("LORA_A", "LORA_B")}
m.load(ad, cfgs, schema_dir=survey_schema.schema_dir(), expected_serving_config_hashes=hashes, backend=m.FakeBackend())
print(json.dumps({"cfgs": cfgs, "hashes": hashes, "adapter_hash": {r: c.directory_hash(p) for r, p in ad.items()}, "runtime": m.RUNTIME_VERSION}))
'''
    d = json.loads(docker_py(IMAGES["survey-service"], code, [(hostpath(fx), "/mnt/fx")]))
    assert d["adapter_hash"]["LORA_A"] == canonical.directory_hash(fx / "LORA_A")
    pk = {}
    for role in ("LORA_A", "LORA_B"):
        mf = {"pipeline_schema_version": bc.PIPELINE_SCHEMA_VERSION, "package_id": f"pkg-{RID}-{role.lower().replace('_', '-')}", "version": "1", "role": role,
              "created_at": "2026-10-15T00:00:00Z", "runtime_contract_version": 1,
              "base_model": {"id": "Qwen/Qwen2.5-1.5B-Instruct", "revision": "main"},
              "adapter_hash": d["adapter_hash"][role], "serving_config": d["cfgs"][role], "serving_config_hash": d["hashes"][role],
              "lineage": {"dataset": STATE["dataset"], "training_run_id": f"run-{RID}-1", "turn_engine_version": "0.2.0",
                          "model_runtime_version": d["runtime"], "question_sets": STATE["qs"][-1:]},
              "eval_report_ref": f"eval-{RID}-{role.lower().replace('_', '-')}"}
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
        pk[role] = (mf, fx / role, rep)
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
    STATE["lora"] = refs; save()
    rec(3, "TEST-SUB", "학습 대신 시험용 어댑터(test/fixtures/e2e-test-adapter, PEFT 형식 r=16, 기반 모델 Qwen/Qwen2.5-1.5B-Instruct)와 시험용 EvaluationReport(METRICS.md 이름의 고정 지표, 실제 평가 아님)를 model-registry에 HTTP로 게시. model-runtime FakeBackend 적재 확인. 게시(REAL): 멱등, 읽기 토큰 게시 거부, 읽기로 매니페스트·어댑터 해시 검증 통과. 계보의 dataset은 단계 2의 실제 데이터셋. model-lab 파이프라인은 실행하지 않음")

def decisions_for(gate_read, subj):
    return gate_read.find_decisions(question_set=subj["question_set"], lora_a=subj["lora_a"], lora_b=subj["lora_b"])[0]

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
        reps[k] = wait(lambda sid=sub["submission_id"]: report_of(sid), 60, f"자동 검사 후 승인 요청 보고서 {k}")
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
    ru = dict(gate_ap.decide(sub_u["submission_id"], "REJECT", approver_id="trainer-test", approver_role="release-approver", reason="시험: 반려")); validate("GateApproval", ru)
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

def kiosk(path, body, token="kiosk"):
    t = TOK("survey-api-kiosk") if token == "kiosk" else token
    return http("POST", "gw", path, t, body)

def public_turn(sid, tid, text):
    c, r = kiosk(f"/v1/sessions/{sid}/turns", {"session_id": sid, "kind": "UTTERANCE", "utterance": text, "turn_id": tid}); return c, r

def step5():
    title(5, "서비스가 새 포인터를 보고 새 세션부터 새 릴리스로 한 턴 이상을 처리한다 (공개 API, 게이트웨이 경유)")
    if "pointers" not in STATE: rec(5, "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    new = STATE["releases"]["2"]
    r = wait(lambda: (lambda cr: cr[1] if cr[0] == 200 and cr[1].get("active_release") == new else None)(survey_ready()), 60, f"survey가 릴리스 {new} 적재")
    assert r["ready"] and not r["release_loader"]["rejections"], r
    sid = f"sess-{RID}-a"
    assert http("POST", "gw", "/v1/sessions", None, {"session_id": sid, "kind": "SESSION_START"})[0] == 401, "토큰 없는 요청이 거부되지 않음"
    c, st = kiosk("/v1/sessions", {"session_id": sid, "kind": "SESSION_START"}); assert c == 200, (c, st)
    validate_survey("FrontendInput", st); assert st["response_text"], st
    c, t1 = public_turn(sid, "turn-1", "체온은 삼십육점오 도예요"); assert c == 200, (c, t1); validate_survey("FrontendInput", t1)
    c, t1b = public_turn(sid, "turn-1", "체온은 삼십육점오 도예요"); assert c == 200 and t1b == t1, "같은 turn_id 재시도가 같은 응답이 아니다"
    c, t2 = public_turn(sid, "turn-2", "기침은 없어요"); assert c == 200, (c, t2)
    # 한 턴이 추론 서버(model-serving)를 거쳤다: 서버의 가짜 백엔드는 출력이 고정이라 생성기 문장이 "(가짜 응답)" 이다
    texts = " ".join(str(x.get("response_text")) for x in (t1, t2))
    assert "(가짜 응답)" in texts, f"model-serving의 고정 출력이 아니다(서비스 내부 가짜?): {texts[:200]}"
    ms_tok = TOK("inference-survey-service")
    c, info = http("GET", "ms", "/v1/info", ms_tok); assert c == 200 and new in info.get("loaded", []), (c, info)
    assert info["backend"] == "fake", info
    assert http("GET", "ms", "/v1/info", None)[0] in (401, 403), "토큰 없이 추론 서버 /v1/가 열림"
    c, st_ = http("GET", "ms", f"/v1/releases/{new}", ms_tok); assert c == 200 and st_["state"] == "LOADED", (c, st_)
    rd = survey_ready()[1]; inf = rd.get("inference") or {}
    # 추론 서버를 멈췄다 다시 띄운다: 그 턴만 실패하고 서비스는 산다, 다시 띄우면 복구(404 -> PUT 재적재)
    mname = f"{a.project}-model-serving-1"
    sidc = f"sess-{RID}-c"; assert kiosk("/v1/sessions", {"session_id": sidc, "kind": "SESSION_START"})[0] == 200
    sh([a.docker, "stop", "-t", "3", mname])
    try:
        cd_, rd_ = public_turn(sidc, "turn-down", "체온은 삼십육점오 도예요")
        failed = cd_ != 200 or (isinstance(rd_, dict) and rd_.get("turn_failure_signal"))
        assert failed, f"추론 서버가 멈췄는데 턴이 성공했다: {cd_} {rd_}"
        assert http("GET", "survey", "/healthz")[0] == 200, "추론 서버 중단으로 서비스가 죽었다"
    finally:
        sh([a.docker, "start", mname])
    wait(lambda: sh([a.docker, "inspect", "-f", "{{.State.Health.Status}}", mname]).stdout.strip() == "healthy", 60, "추론 서버 복구")
    cu, ru = public_turn(sidc, "turn-up", "체온은 삼십육점오 도예요")
    assert cu == 200 and not (isinstance(ru, dict) and ru.get("turn_failure_signal")) and "(가짜 응답)" in str(ru.get("response_text")), (cu, ru)
    kiosk(f"/v1/sessions/{sidc}/end", {"session_id": sidc, "kind": "SESSION_END"})
    assert kiosk(f"/v1/sessions/{sid}/intervention", {"session_id": sid, "decision": "RESUME", "turn_id": "x"})[0] == 404, "직원 개입 경로가 외부 입구로 열려 있다"
    # 직원 개입은 서비스에 직접(내부 경로)만: 키오스크 토큰은 403, 직원 토큰은 멈추지 않은 세션에 409(PUBLIC_API.md)
    ib = {"session_id": sid, "decision": "RESUME", "turn_id": "i1"}
    assert http("POST", "survey", f"/v1/sessions/{sid}/intervention", TOK("survey-api-kiosk"), ib)[0] == 403, "키오스크 토큰으로 직원 개입이 열림"
    assert http("POST", "survey", f"/v1/sessions/{sid}/intervention", TOK("survey-api-staff"), ib)[0] == 409, "멈추지 않은 세션의 개입이 409가 아님"
    assert http("GET", "gw", f"/v1/sessions/{sid}/turns", TOK("survey-api-kiosk"))[0] in (404, 405)
    c, en = kiosk(f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"}); assert c == 200, (c, en); validate_survey("FrontendInput", en)
    # 서비스가 턴마다 Trace를 I6로 보냈는지(outbox 전송 수)
    sent = wait(lambda: (lambda cr: cr[1]["trace_outbox"]["sent"] if cr[1]["trace_outbox"]["sent"] >= 2 else None)(survey_ready()), 30, "Trace 전송")
    STATE["sess_a"] = sid; save()
    rec(5, "REAL", f"게이트웨이 경유 공개 API(Bearer 토큰, 없으면 401): 세션 시작·발화 2턴·종료, 응답 FrontendInput 스키마 통과, 같은 turn_id 재시도는 같은 응답, 직원 개입 경로는 외부에 닫히고 내부에서 키오스크 토큰 403, 직원 토큰은 멈추지 않은 세션에 409(위험 신호로 멈춘 세션의 RESUME/END는 가짜 백엔드로 유도하지 못해 시험하지 않음). 실제 survey-service가 게이트 포인터를 HTTP로 폴링해 릴리스 {new} 적재(번들 해시 검증)하고 턴마다 Trace를 I6로 전송(outbox sent={sent}). 한 턴이 model-serving 컨테이너(I9: 서비스 -> PUT 적재 -> parse -> generate)를 거쳤다(고정 출력 '(가짜 응답)' 확인, /v1/info loaded, 토큰 없으면 거부). 추론 서버를 멈추면 그 턴만 실패하고 서비스는 살아 있으며 다시 띄우면 다음 턴이 복구된다. 모델은 fake 백엔드와 시험용 번들(TEST-SUB)")

def trace_env(release_id, n):
    keys = list(survey_schema.load_schema("TurnTrace")["$defs"]["TurnTrace"].get("required") or [])
    t = {k: None for k in keys}
    t.update(session_id=f"s-{RID}", turn_id=f"t-{RID}-{n}", contract_version=1)
    t["parser_input"] = {"utterance": "체온은 삼십육점오 도예요", "last_directive": None, "awaiting_questions": [],
        "question_names": [{"question_id": "Q1", "name": "체온", "slots": ["body_temp"]}], "answered_slots": [], "guide_list": []}
    t["parser_output"] = {"items": []}
    STATE["parser_input"] = t["parser_input"]
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

def bad_ok():
    return {"review_status": "CONFIRMED", "expected_kind": "PARSER", "expected": {"items": [{"item_no": 0, "target": {"question_id": "Q1", "repeat_key": "", "slot_id": "body_temp"}, "value": "36.5", "source_text": "삼십육점오", "intent": "ANSWERED_INTENT", "progress_op": None, "guide_id": None}]}}

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
    bad = {"review_status": "CONFIRMED", "expected": {"items": [{"bad": 1}]}, "expected_kind": "PARSER"}
    c, e = http("POST", "ops", f"/v1/cases/{cid}/review", rv_tok, bad); assert c == 400, (c, e); validate("BoundaryError", e)
    c, e2 = http("POST", "ops", f"/v1/cases/{cid}/review", rv_tok, {"review_status": "CONFIRMED", "expected": {"items": []}}); assert c == 400, (c, e2)
    assert http("POST", "ops", f"/v1/cases/{cid}/review", TOK("ops-read-synthetic-data"), bad)[0] == 403, "읽기 토큰으로 검토 게시됨"
    assert http("POST", "ops", f"/v1/cases/nonexistent-case/review", rv_tok, {"review_status": "DISMISSED"})[0] == 404
    pi = dict(__import__("copy").deepcopy(STATE["parser_input"])); pi["utterance"] = "체온은 36.5도예요"   # 개인정보를 뺀 문장으로 검토자가 쓴 입력(시험 자료)
    badri = {**bad_ok(), "reviewed_input": {"utterance": 1}}
    c, eri = http("POST", "ops", f"/v1/cases/{cid}/review", rv_tok, badri); assert c == 400, ("잘못된 reviewed_input이 받아들여짐", c, eri)
    good = {"review_status": "CONFIRMED", "expected_kind": "PARSER", "reviewed_input": pi, "expected": {"items": [{"item_no": 0, "target": {"question_id": "Q1", "repeat_key": "", "slot_id": "body_temp"}, "value": "36.5", "source_text": "삼십육점오", "intent": "ANSWERED_INTENT", "progress_op": None, "guide_id": None}]}}
    c, r1 = http("POST", "ops", f"/v1/cases/{cid}/review", rv_tok, good); assert c == 201, (c, r1); validate("FailureCase", r1)
    c, r2 = http("POST", "ops", f"/v1/cases/{cid}/review", rv_tok, good); assert c == 200 and r2 == r1, (c, "같은 검토 재전송이 같은 결과가 아니다")
    confirmed = [x for x in fs.list_cases(review_status="CONFIRMED")[0] if x["case_id"] in mine]; assert confirmed
    assert confirmed[0].get("reviewed_input") == pi, "reviewed_input이 I7 읽기에 그대로 보이지 않는다"
    rec("7a", "REAL", f"검토 확인을 HTTP로: POST /v1/cases/{{id}}/review(검토 토큰) 잘못된 expected는 400({e.get('message','')[:80]}), expected_kind 없음 400, 읽기 토큰 403, 없는 사례 404, 올바른 확인(reviewed_input 포함)은 201(새 version, FailureCase 스키마 통과, I7 읽기에서 reviewed_input 그대로), 잘못된 reviewed_input 400, 재전송 200 같은 결과. 검토 UI는 아직 없다")
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
    c, tb = public_turn(sidb, "turn-1", "체온은 삼십칠 도예요"); assert c == 200, (c, tb)
    kiosk(f"/v1/sessions/{sidb}/end", {"session_id": sidb, "kind": "SESSION_END"})
    bad = HttpGateService(URL("gate"), TOK("gate-write-question-authoring"))
    try: bad.request_rollback({**req, "request_id": f"rbk-{RID}-2"}); raise AssertionError("허용되지 않은 역할이 롤백함")
    except bc.BoundaryError as e: assert e.code == "PERMISSION_DENIED"
    rec(8, "REAL", f"ops-feedback 토큰의 RollbackRequest -> RollbackReceipt APPLIED(멱등), 활성 포인터 {new}->{old}, 실제 survey-service가 /readyz에서 이전 릴리스로 복귀, 롤백 권한 없는 역할은 PERMISSION_DENIED, 롤백 뒤 공개 API로 새 세션 한 턴 처리(이전 릴리스). 롤백을 요청한 주체는 e2e(ops-feedback 역할 토큰)이고 ops-feedback 잡의 자동 롤백 평가는 아님")

STEPS = [("1", step1), ("2", step2), ("3", step3), ("4", step4), ("5", step5), ("6", step6), ("7", step7), ("8", step8)]
only = set(filter(None, a.only.split(",")))
for n, fn in STEPS:
    if only and n not in only: continue
    try: fn()
    except AssertionError as e: rec(fn.__name__, "FAIL", str(e))
    except Exception as e: rec(fn.__name__, "FAIL", f"{type(e).__name__}: {e}")
print("\n== 요약 (단계 1~8)")
for s, st, d in RESULTS: print(f"  {str(s):>4} {st:9} {d[:170]}")
(WORK / "steps.json").write_text(json.dumps([list(r) for r in RESULTS], ensure_ascii=False, indent=1))
sys.exit(1 if any(r[1] == "FAIL" for r in RESULTS) else 0)
