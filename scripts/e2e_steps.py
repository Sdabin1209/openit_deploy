#!/usr/bin/env python3
"""합격 시나리오(docs/E2E.md) 1~8단계를 실행하고 레코드를 계약 스키마와 해시로 검증한다. 9단계는 scripts/e2e.sh.

각 단계 상태:
  REAL        실제 서비스(이미지)가 실제 인터페이스로 처리한 것
  TEST-SUB    시험 대역으로 대신한 것(이름에 test가 들어간 자료, 가짜 백엔드). 운영 설정으로 흘러가지 않는다
  BLOCKED     지금 영역들의 구현으로는 이어지지 않아 하지 못한 것(이유는 change-requests/)
검증 실패는 FAIL이고 종료 코드 1이다.
"""
import argparse, json, pathlib, subprocess, sys, urllib.request, urllib.error, tempfile, hashlib

import boundary_contracts as bc
from boundary_contracts import canonical
import survey_schema
import jsonschema

ap = argparse.ArgumentParser()
ap.add_argument("--project", required=True)
ap.add_argument("--secrets", required=True)
ap.add_argument("--ports", required=True, help="JSON {qa,gate,ops,survey: host port}")
ap.add_argument("--images", required=True, help="JSON {survey-service,question-authoring,...: image ref}")
ap.add_argument("--docker", default="docker")
ap.add_argument("--hostpath-prefix", default="", help="docker.exe용 경로 변환 명령(wslpath -w)")
ap.add_argument("--root", required=True)
a = ap.parse_args()
PORTS = json.loads(a.ports); IMAGES = json.loads(a.images)
ROOT = pathlib.Path(a.root)
TOK = lambda n: (pathlib.Path(a.secrets) / "tokens" / n).read_text().strip()
RESULTS = []


def rec(step, status, detail):
    RESULTS.append((step, status, detail)); print(f"  [{status}] {detail}", flush=True)


def hostpath(p):
    if a.hostpath_prefix:
        return subprocess.check_output([a.hostpath_prefix, "-w", str(p)], text=True).strip()
    return str(p)


def http(method, port, path, token=None, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    if token: req.add_header("Authorization", f"Bearer {token}")
    if data is not None: req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: return e.code, json.loads(raw)
        except Exception: return e.code, raw.decode(errors="replace")


def validate(name, obj):
    errs = list(bc.validator(name).iter_errors(obj))
    assert not errs, f"{name} 스키마 위반: {errs[0].message}"


def validate_survey(name, obj):
    schema = survey_schema.load_schema(name)
    d = survey_schema.schema_dir()
    from referencing import Registry, Resource
    reg = Registry()
    for f in pathlib.Path(d).glob("*.json"):
        reg = reg.with_resource(f.name, Resource.from_contents(json.loads(f.read_text())))
    v = jsonschema.validators.validator_for(schema)(schema, registry=reg)
    errs = list(v.iter_errors(obj))
    assert not errs, f"문진 스키마 {name} 위반: {errs[0].message}"


def docker_py(image, code, mounts=(), network=None):
    """이미지 안에서 python 코드를 한 번 실행한다. 볼륨/폴더는 읽기 전용으로만 붙인다."""
    cmd = [a.docker, "run", "--rm", "-i"]
    for src, dst in mounts: cmd += ["-v", f"{src}:{dst}:ro"]
    cmd += [image, "python", "-"]
    out = subprocess.run(cmd, input=code, capture_output=True, text=True)
    assert out.returncode == 0, f"이미지 안 실행 실패: {out.stderr[-500:]}"
    return out.stdout


def step(n, title):
    print(f"\n== 단계 {n}: {title}", flush=True)


def run(fn):
    try: fn()
    except AssertionError as e: rec(fn.__name__, "FAIL", str(e))
    except Exception as e: rec(fn.__name__, "FAIL", f"{type(e).__name__}: {e}")


STATE = {}

def step1():
    step(1, "저자가 문항 자료를 올리고 미리보기를 확인한다 (question-authoring, I1)")
    qa, tok = PORTS["qa"], TOK("qa-author-e2e")
    form = ROOT / "build/ctx/question-authoring/examples/question_form.txt"
    refs = []
    for ver, text in ((1, form.read_text()), (2, form.read_text().replace("오늘 체온이 얼마였나요?", "오늘 측정한 체온이 얼마였나요?"))):
        raw = text.encode()
        code, d = http("POST", qa, f"/v1/materials?question_set_id=qs-e2e-test&filename=form{ver}.txt", tok, raw=raw, ctype="text/plain")
        assert code == 200 or code == 201, f"자료 등록 {code} {d}"
        code, pv = http("GET", qa, f"/v1/drafts/{d['draft_id']}/preview", tok)
        assert code == 200 and pv["ready_to_confirm"], f"미리보기 {code}"
        code, ref = http("POST", qa, f"/v1/drafts/{d['draft_id']}/confirm", tok, body={"preview_hash": pv["preview_hash"]})
        assert code == 200, f"확인 {code} {ref}"
        refs.append((ref, raw)); 
    code, _ = http("GET", qa, "/v1/drafts")
    assert code == 403, f"인증 없는 요청이 거부되지 않음 {code}"
    # I1은 SDK다. 운영 사용법(읽기 전용 연결)대로 이미지 안에서 qa-data 볼륨을 읽기 전용으로 붙여 읽는다.
    code = '''
import json
from question_authoring.store import SqliteQuestionStore
r = SqliteQuestionStore("/data/questions.sqlite3", read_only=True).reader()
out = {"ids": list(r.list_ids()[0])}
vers = r.list_versions("qs-e2e-test")[0]
out["versions"] = [dict(v) for v in vers]
out["latest"] = dict(r.latest("qs-e2e-test", reviewed_only=True))
out["banks"] = {v["version"]: r.get_question_bank(v) for v in vers}
out["reviews"] = {v["version"]: [dict(x) for x in r.get_reviews(v)] for v in vers}
out["changes"] = {v["version"]: (dict(r.get_change(v)) if r.get_change(v) else None) for v in vers}
print(json.dumps(out, ensure_ascii=False))
'''
    data = json.loads(docker_py(IMAGES["question-authoring"], code, [(f"{a.project}_qa-data", "/data")]))
    assert [v["version"] for v in data["versions"]] == ["1", "2"], data["versions"]
    assert data["latest"]["version"] == "2"
    for v in data["versions"]:
        bank = data["banks"][v["version"]]
        assert canonical.content_hash(bank) == v["content_hash"], "QuestionBank 해시 불일치"
        assert str(bank["version"]) == v["version"]
        validate_survey("QuestionBank", bank)
        (rv,) = data["reviews"][v["version"]]
        validate("ReviewRecord", rv)
        assert rv["decision"] == "APPROVED" and rv["clinical_basis_approved"] is True
        assert rv["question_set"] == v
    # 원본 해시 출처
    src_hash = data["reviews"]["1"][0]["ext"]["question-authoring"]["source"]["source_hash"]
    assert src_hash == "sha256:" + hashlib.sha256(refs[0][1]).hexdigest(), "원본 해시 출처 불일치"
    cc = data["changes"]["2"]; validate("ChangeClassification", cc)
    assert data["changes"]["1"] is None and cc["from"]["version"] == "1" and cc["to"]["version"] == "2"
    STATE["qs_v1"], STATE["qs_v2"] = data["versions"]
    rec(1, "REAL", f"QuestionBank v1, v2 (해시 검증), ReviewRecord x2 (clinical_basis_approved), ChangeClassification {cc['change_kinds']} {cc['affected_slots']}, 원본 해시 출처 일치. 모두 스키마 통과")

def step2():
    step(2, "문항을 읽어 학습·평가 데이터를 만든다 (synthetic-data, I1->I2)")
    rec(2, "BLOCKED", "synthetic-data는 이 구성에 서비스·잡이 없다(run-once 명령, 이미지, 설정을 deploy가 알 수 없음). LLM 생성은 GPU 서버 몫(D40). CR-D04")

def step3():
    step(3, "설정 하나로 학습·평가·패키징·게시가 돈다 (model-lab, I2->I3) -- 시험 대역")
    fx = ROOT / "test/fixtures"
    code = '''
import json, pathlib, model_runtime as m, survey_schema
from boundary_contracts import canonical as c
cfgs = m.fake_serving_configs()
hashes = {r: m.serving_config_hash(v) for r, v in cfgs.items()}
ad = {r: pathlib.Path("/mnt/fx/e2e-test-adapter")/r for r in ("LORA_A", "LORA_B")}
m.load(ad, cfgs, schema_dir=survey_schema.schema_dir(), expected_serving_config_hashes=hashes, backend=m.FakeBackend())
print(json.dumps({"cfgs": cfgs, "hashes": hashes, "adapter_hash": {r: c.directory_hash(p) for r, p in ad.items()},
                  "runtime": m.RUNTIME_VERSION}))
'''
    d = json.loads(docker_py(IMAGES["survey-service"], code, [(hostpath(fx), "/mnt/fx")]))
    # 같은 입력으로 다시 계산해도 같다(재현)
    assert d["adapter_hash"]["LORA_A"] == canonical.directory_hash(fx / "e2e-test-adapter/LORA_A"), "어댑터 해시가 컨테이너 밖 계산과 다르다"
    STATE["adapters"] = {}
    for role in ("LORA_A", "LORA_B"):
        mf = {
            "pipeline_schema_version": "1.1", "package_id": f"pkg-test-{role.lower().replace('_','-')}", "version": "1", "role": role,
            "created_at": "2026-10-15T00:00:00Z", "runtime_contract_version": 1,
            "base_model": {"id": "base-test-tiny", "revision": "test-0"},
            "adapter_hash": d["adapter_hash"][role], "serving_config": d["cfgs"][role], "serving_config_hash": d["hashes"][role],
            "lineage": {"dataset": {"id": "ds-test", "version": "1", "content_hash": "sha256:" + "0" * 64},
                        "training_run_id": "run-test-1", "turn_engine_version": "0.2.0", "model_runtime_version": d["runtime"],
                        "question_sets": [STATE["qs_v2"]]},
            "eval_report_ref": "eval-test-1",
        }
        mf["content_hash"] = canonical.content_hash(mf)
        validate("ModelPackageManifest", mf)
        assert canonical.sha256_hash(mf["serving_config"]) == mf["serving_config_hash"]
        STATE["adapters"][role] = {"id": mf["package_id"], "version": "1", "content_hash": mf["content_hash"]}
    rec(3, "TEST-SUB", "학습 대신 시험용 어댑터 디렉터리(test/fixtures/e2e-test-adapter)와 model-runtime FakeBackend 적재(load 성공), "
        "ModelPackageManifest 2건(어댑터 해시=directory_hash, serving_config_hash 일치) 스키마 통과. model-lab 파이프라인은 실행하지 않았다(대신함, 게시 I3 없음)")

def step4():
    step(4, "후보 수집기가 새 조합을 찾아 판정하고 릴리스·번들을 만든다 (release-gate, I1,I3->I4,I5)")
    gate = PORTS["gate"]
    subj = {"question_set": STATE["qs_v2"], "lora_a": STATE["adapters"]["LORA_A"], "lora_b": STATE["adapters"]["LORA_B"]}
    code, s1 = http("POST", gate, "/v1/submissions", TOK("gate-write-question-authoring"), {"subject": subj, "requested_by_role": "question-authoring"})
    assert code == 202, f"접수 {code} {s1}"
    validate("GateSubmission", s1)
    code, s2 = http("POST", gate, "/v1/submissions", TOK("gate-write-question-authoring"), {"subject": subj, "requested_by_role": "question-authoring"})
    assert s2["submission_id"] == s1["submission_id"], "같은 조합의 중복 접수가 다른 접수를 만들었다"
    code, d = http("POST", gate, "/v1/submissions", TOK("gate-write-operator"), {"subject": subj, "requested_by_role": "question-authoring"})
    assert code == 403, f"토큰 역할과 다른 역할 주장이 거부되지 않음 {code}"
    validate("BoundaryError", d)
    code, rd = http("GET", gate, "/readyz")
    assert rd["can_pass"] is False
    rec("4a", "REAL", f"접수 202 {s1['submission_id']} (GateSubmission 스키마 통과, 중복 접수는 같은 접수, 역할 불일치 토큰은 403 PERMISSION_DENIED)")
    rec("4b", "BLOCKED", "판정·ReleaseManifest·번들은 못 만든다: 게이트 이미지에 I1·I3 클라이언트가 없고(판정 '" + str(rd.get("judging")) + "'), 승인 평가 워커는 GPU 서버 몫이며, 통과 정책(O11)이 비어 있다. CR-D01, CR-D02")

def step5():
    step(5, "서비스가 새 포인터를 보고 새 세션부터 새 릴리스로 한 턴 이상을 처리한다 (survey-service, I4,I8,I9->I6)")
    code, rd = http("GET", PORTS["survey"], "/readyz")
    assert code == 200 and rd["ready"], rd
    code, _ = http("POST", PORTS["survey"], "/v1/turns", body={})
    assert code == 404, f"공개 API(O06 대기)가 있으면 안 된다: {code}"
    rec(5, "BLOCKED", f"survey-service는 시험 대역 I4/I6(survey 리포지토리 smoke_fakes, 릴리스 {rd['active_release']})으로 /readyz 200만 확인했다. 실제 게이트 포인터를 읽는 클라이언트가 이미지에 없고(CR-D01), 턴을 받는 공개 API는 O06 대기라 턴을 서비스에 넣을 수 없다. 개발용 CLI는 TraceEnvelope를 내지 않는다")

def step6():
    step(6, "Trace를 수집·비식별해 실패 사례를 만든다 (ops-feedback, I6->I7)")
    ops = PORTS["ops"]
    keys = bc_survey_trace_keys()
    trace = {k: None for k in keys}; trace.update(session_id="s-e2e-test", turn_id="t-e2e-test-1", contract_version=1)
    env = {"pipeline_schema_version": "1.1", "release_id": "rel-e2e-test", "runtime_contract_version": 1, "session_id": "s-e2e-test",
           "turn_id": "t-e2e-test-1", "sent_at": "2026-10-15T00:00:00Z", "trace": trace}
    validate("TraceEnvelope", env)
    tok = TOK("ops-ingest-survey-service")
    c1, r1 = http("POST", ops, "/v1/traces", tok, env); c2, r2 = http("POST", ops, "/v1/traces", tok, env)
    assert (c1, r1["status"], c2, r2["status"]) == (200, "ACCEPTED", 200, "DUPLICATE"), (c1, r1, c2, r2)
    validate("IngestResult", r1); validate("IngestResult", r2)
    c3, r3 = http("POST", ops, "/v1/traces", None, env); assert c3 == 403
    c4, r4 = http("POST", ops, "/v1/traces", tok, {**env, "trace": {"x": 1}}); assert c4 == 400, (c4, r4)
    validate("BoundaryError", r4)
    rec("6a", "TEST-SUB", "봉투는 e2e가 survey-service 대신 만들어 보냈다(공개 API가 없어 서비스가 턴을 못 만든다). 수집(REAL): ACCEPTED -> DUPLICATE, 토큰 없음 403, 스키마 위반 400. IngestResult·BoundaryError 스키마 통과")
    rec("6b", "BLOCKED", "비식별 잡 실행과 FailureCase 생성은 못 했다: 잡 설정 파일(job.yaml)의 deploy용 예시와 형식 문서가 없다. CR-D05")

def bc_survey_trace_keys():
    sc = survey_schema.load_schema("TurnTrace")
    sc = sc["$defs"]["TurnTrace"] if "$defs" in sc and "TurnTrace" in sc.get("$defs", {}) else sc
    return list(sc.get("required") or sc["properties"])

def step7():
    step(7, "실패 사례가 데이터 생성·학습·저작으로 돌아간다 (I7)")
    rec(7, "BLOCKED", "FailureCase가 없고(6b) synthetic-data·model-lab 단계가 없어(2, 3) 이어지지 않는다")

def step8():
    step(8, "롤백 요청이 활성 릴리스를 되돌린다 (ops-feedback -> release-gate, I5)")
    gate = PORTS["gate"]
    code, ap_ = http("GET", gate, "/v1/active-pointer", TOK("gate-read-survey-service"))
    assert code == 200 and ap_["active_pointer"] is None
    req = {"pipeline_schema_version": "1.1", "request_id": "rbk-e2e-test-1", "requested_at": "2026-10-15T00:00:00Z",
           "from_release_id": "rel-e2e-test-new", "to_release_id": "rel-e2e-test-old", "reason": "E2E 시험",
           "evidence_refs": ["ev-e2e-test-1"], "requested_by_role": "ops-feedback"}
    validate("RollbackRequest", req)
    c1, r1 = http("POST", gate, "/v1/rollback", TOK("gate-write-ops-feedback"), req)
    assert c1 == 200 and r1["status"] == "REJECTED", (c1, r1)
    validate("RollbackReceipt", r1)
    c2, r2 = http("POST", gate, "/v1/rollback", TOK("gate-write-ops-feedback"), req)
    assert r2 == r1, "같은 request_id가 같은 결과를 내지 않았다"
    c3, r3 = http("POST", gate, "/v1/rollback", TOK("gate-write-question-authoring"), {**req, "request_id": "rbk-e2e-test-2", "requested_by_role": "ops-feedback"})
    assert c3 == 403, (c3, r3)
    rec("8a", "REAL", f"롤백 요청 경로: ops-feedback 토큰으로 요청 -> RollbackReceipt {r1['status']} (대상 릴리스가 없어 거부가 맞다), 같은 request_id는 같은 응답, 다른 역할 토큰은 403. 스키마 통과")
    rec("8b", "BLOCKED", "APPLIED(활성 릴리스를 되돌림)와 서비스가 새 세션부터 이전 릴리스를 쓰는 것은 릴리스가 없어(4b) 하지 못했다")


for fn in (step1, step2, step3, step4, step5, step6, step7, step8):
    run(fn)
print("\n== 요약 (단계 1~8)")
for s, st, d in RESULTS: print(f"  {str(s):>4} {st:9} {d[:160]}")
fails = [r for r in RESULTS if r[1] == "FAIL"]
pathlib.Path(ROOT / "state").mkdir(exist_ok=True)
json.dump([list(r) for r in RESULTS], open(a.secrets + "/../e2e-steps.json", "w"), ensure_ascii=False, indent=1)
sys.exit(1 if fails else 0)
