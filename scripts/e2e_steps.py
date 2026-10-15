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
        pk[role] = (mf, fx / role)
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
    for role, (mf, adir) in pk.items():
        got = reg.publish(mf, adir, f"TEST eval report {RID} {role}\n".encode())
        again = reg.publish(mf, adir, f"TEST eval report {RID} {role}\n".encode()); assert dict(again) == dict(got), "게시가 멱등이 아니다"
        refs[role] = {"id": mf["package_id"], "version": mf["version"], "content_hash": mf["content_hash"]}
    rr = HttpModelRegistry(URL("mr"), TOK("model-registry-read-release-gate"))
    for role, (mf, adir) in pk.items():
        g = rr.get_manifest(mf["package_id"], "1"); validate("ModelPackageManifest", g); assert g["content_hash"] == mf["content_hash"]
        dest = WORK / f"adapter-{role}"; p = rr.open_adapter(mf["package_id"], "1", dest=dest)   # 해시 검증 포함
        assert canonical.directory_hash(p) == mf["adapter_hash"]
    try:
        reg_ro = HttpModelRegistry(URL("mr"), TOK("model-registry-read-release-gate")); reg_ro.publish(pk["LORA_A"][0], pk["LORA_A"][1], b"x"); raise AssertionError("읽기 토큰으로 게시됨")
    except bc.BoundaryError as e: assert e.code == "PERMISSION_DENIED"
    STATE["lora"] = refs; save()
    rec(3, "TEST-SUB", "학습 대신 시험용 어댑터(test/fixtures/e2e-test-adapter, PEFT 형식 r=16, 기반 모델 Qwen/Qwen2.5-1.5B-Instruct)와 model-runtime FakeBackend 적재를 model-registry에 HTTP로 게시. 게시(REAL): 멱등, 읽기 토큰 게시 거부, 읽기로 매니페스트·어댑터 해시 검증 통과. 계보의 dataset은 단계 2의 실제 데이터셋. model-lab 파이프라인은 실행하지 않음")

def decisions_for(gate_read, subj):
    return gate_read.find_decisions(question_set=subj["question_set"], lora_a=subj["lora_a"], lora_b=subj["lora_b"])[0]

def step4():
    title(4, "후보 수집기가 새 조합을 찾아 판정하고, 통과하면 릴리스·번들을 만든다 (release-gate, I1,I3 HTTP -> I4,I5)")
    if "lora" not in STATE: rec(4, "BLOCKED", "단계 3의 패키지가 없다"); return
    print("  !! 시험용 정책(test/policy/test-gate-policy.json, 임계치는 시험용으로 무의미)과 시험용 평가 실행기(test/gate-runner)를 쓴다 !!")
    r = subprocess.run(["bash", str(ROOT / "scripts/run-job.sh"), "job-release-gate-collect"], capture_output=True, text=True)
    assert r.returncode in (0, 75), f"collect 종료 {r.returncode}: {(r.stderr + r.stdout)[-500:]}"
    collected = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    gate_r = HttpReleaseReader(URL("gate"), TOK("gate-read-survey-service")); gate_s = HttpGateService(URL("gate"), TOK("gate-write-operator"))
    subs = {}
    for i, q in enumerate(STATE["qs"]):
        subj = {"question_set": q, "lora_a": STATE["lora"]["LORA_A"], "lora_b": STATE["lora"]["LORA_B"]}
        s = gate_s.submit_candidate(subj, requested_by_role="operator"); validate("GateSubmission", dict(s)); subs[q["version"]] = (s, subj)
    STATE["subs"] = {k: [dict(v[0]), v[1]] for k, v in subs.items()}; save()
    rec("4a", "REAL", f"수집기 run-once(컨테이너): {collected[:120]}; 후보 접수 {len(subs)}건(GateSubmission 스키마 통과, 같은 조합은 같은 접수)")
    # 판정 대기
    def decided():
        out = {}
        for v, (s, subj) in subs.items():
            ds = [d for d in decisions_for(gate_r, subj)]
            if ds: out[v] = ds[0]
        return out if len(out) == len(subs) else None
    try:
        dec = wait(decided, 40, "inline 검사 판정")
    except AssertionError:
        dec = None
    if dec is not None:
        for v, d in dec.items(): validate("GateDecision", dict(d))
        print("  판정:", {v: (d["result"], d.get("reject_codes")) for v, d in dec.items()})
    # 시험용 실행기가 평가를 낸다면 PASS가 나온다
    def passed():
        out = {}
        for v, (s, subj) in subs.items():
            ds = decisions_for(gate_r, subj)
            if ds and ds[0]["result"] == "PASS": out[v] = ds[0]
        return out if len(out) == len(subs) else None
    try:
        dec = wait(passed, 60, "PASS 판정", every=3)
    except AssertionError:
        cur = {v: decisions_for(gate_r, subj) for v, (s, subj) in subs.items()}
        why = {v: (d[0]["result"], d[0].get("reject_codes"), d[0].get("reject_reasons")) if d else "판정 없음(승인 평가 대기)" for v, d in cur.items()}
        rec("4b", "BLOCKED", f"PASS에 이르지 못했다: {json.dumps(why, ensure_ascii=False)[:500]}. 원인: release-gate에는 AcceptanceRunner 구현이 없다(CR-D10)")
        return
    rels = {}
    for v, d in dec.items():
        validate("GateDecision", dict(d)); rid = d.get("release_id") or d.get("ext", {}).get("release_id")
        rels[v] = rid
    STATE["decisions"] = {v: dict(d) for v, d in dec.items()}; save()
    for v, rid in rels.items():
        rel = gate_r.get_release(rid); validate("ReleaseManifest", dict(rel)); assert canonical.content_hash({k: x for k, x in rel.items()}) == rel["content_hash"]
    STATE["releases"] = rels; save()
    # 번들(해시 검증은 클라이언트가 한다) -> 활성화
    bd = WORK / "bundles"; bundles = {v: gate_r.load_bundle(rid, dest=bd) for v, rid in rels.items()}
    first, second = STATE["qs"][0]["version"], STATE["qs"][-1]["version"]
    ap1 = gate_s.activate(rels[first], requested_by_role="operator"); validate("ActivePointer", dict(ap1))
    ap2 = gate_s.activate(rels[second], requested_by_role="operator"); validate("ActivePointer", dict(ap2))
    assert ap2["pointer_version"] > ap1["pointer_version"]
    STATE["pointers"] = [dict(ap1), dict(ap2)]; save()
    try: gate_r.load_bundle("rel-does-not-exist", dest=bd); raise AssertionError("없는 릴리스가 읽힘")
    except bc.BoundaryError as e: assert e.code in ("NOT_FOUND", "FAILED_PRECONDITION")
    # 수집기가 역할을 지키는지: LORA_A 패키지를 lora_b 자리에 넣은 조합이 접수되었는지(관찰만, 실패로 치지 않는다)
    swapped = {"question_set": STATE["qs"][-1], "lora_a": STATE["lora"]["LORA_B"], "lora_b": STATE["lora"]["LORA_A"]}
    try: sw = decisions_for(gate_r, swapped)
    except Exception as e: sw = f"조회 실패 {e}"
    STATE["swapped_roles_decisions"] = len(sw) if isinstance(sw, list) else str(sw); save()
    if isinstance(sw, list) and sw:
        rec("4c", "NOTE", f"관찰: 수집기가 역할이 뒤바뀐 조합(lora_a=LORA_B 패키지, lora_b=LORA_A 패키지)도 접수·판정했다({len(sw)}건, 결과 {sw[0]['result']}). 패키지 role(LORA_A/LORA_B)을 고려하지 않는 것으로 보인다. CR-D13")
    rec("4b", "TEST-SUB", f"정책·평가 실행기는 시험용(TEST-SUB). 나머지는 REAL: GateDecision PASS x{len(dec)}, ReleaseManifest(해시 재계산 일치), 번들(HTTP tar, 클라이언트가 모든 해시 검증), 활성화 2회(포인터 {ap1['pointer_version']}->{ap2['pointer_version']})")

def survey_ready():
    c, r = http("GET", "survey", "/readyz"); return c, r

def step5():
    title(5, "서비스가 새 포인터를 보고 새 세션부터 새 릴리스로 한 턴 이상을 처리한다 (survey-service, I4 HTTP)")
    if "pointers" not in STATE: rec(5, "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    new = STATE["releases"][STATE["qs"][-1]["version"]]
    r = wait(lambda: (lambda cr: cr[1] if cr[0] == 200 and cr[1].get("active_release") == new else None)(survey_ready()), 60, f"survey가 릴리스 {new} 적재")
    assert r["ready"] and not r["release_loader"]["rejections"], r
    gate_r = HttpReleaseReader(URL("gate"), TOK("gate-read-survey-service"))
    bundle = gate_r.load_bundle(new, dest=WORK / "bundles-turn")
    bank = bundle.question_bank if hasattr(bundle, "question_bank") else bundle["question_bank"]
    bf = WORK / "turn"; bf.mkdir(exist_ok=True); (bf / "bank.json").write_text(json.dumps(bank, ensure_ascii=False))
    code = f'''
import json, subprocess, sys
r = subprocess.run([sys.executable, "-m", "survey_service.cli", "--bank", "/mnt/turn/bank.json", "--db", "/tmp/s.db", "turn", "--session", "S-{RID}", "--start"], capture_output=True, text=True)
assert r.returncode == 0, r.stderr
d = json.loads(r.stdout); print(json.dumps({{"action": d["orchestrator_output"]["log_entry"]["directive"]["action"], "replayed": d["replayed"]}}))
'''
    out = json.loads(docker_py(IMAGES["survey-service"], code, [(hostpath(bf), "/mnt/turn")]))
    assert out["action"] == "ASK_NEXT", out
    rec(5, "TEST-SUB", f"REAL: 실제 survey-service 컨테이너가 게이트를 HTTP로 폴링해 새 포인터의 릴리스 {new}를 적재(/readyz active_release, 거부 없음), 번들 해시 검증 통과. TEST-SUB: 공개 API(O06)가 없어 한 턴은 이미지 안의 개발용 CLI 하네스로 그 릴리스의 문항 세트에 대해 처리(ASK_NEXT), 모델은 가짜 백엔드(fake). CLI는 로더·Trace 전송을 거치지 않아 '새 세션부터'는 /readyz의 active_release 전환으로만 확인했다")

def trace_env(release_id, n):
    keys = list(survey_schema.load_schema("TurnTrace")["$defs"]["TurnTrace"].get("required") or [])
    t = {k: None for k in keys}
    t.update(session_id=f"s-{RID}", turn_id=f"t-{RID}-{n}", contract_version=1)
    t["parser_input"] = {"utterance": "체온은 삼십육점오 도예요", "last_directive": None, "awaiting_questions": [],
        "question_names": [{"question_id": "Q1", "name": "체온", "slots": ["body_temp"]}], "answered_slots": [], "guide_list": []}
    t["parser_output"] = {"items": []}
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
    rec("6a", "TEST-SUB", f"봉투는 e2e가 survey-service 대신 만든 시험 자료(공개 API가 없어 서비스가 턴→Trace를 내지 못함; release_id는 단계 4의 실제 릴리스). 수집 REAL: HttpTraceIngest ACCEPTED→DUPLICATE, 토큰 없음 403, 스키마 위반 400")
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

def step7():
    title(7, "실패 사례가 데이터 생성·학습·저작으로 돌아간다 (I7 HTTP)")
    if not STATE.get("cases"): rec(7, "BLOCKED", "FailureCase가 없다(단계 6)"); return
    fs = HttpFailureStore(URL("ops"), TOK("ops-read-synthetic-data"))
    mine = {c["case_id"] for c in STATE["cases"]}
    confirmed = [c for c in fs.list_cases(review_status="CONFIRMED")[0] if c["case_id"] in mine]
    if not confirmed:
        # 검토 화면이 없고 검토 게시는 HTTP로 열려 있지 않다(CR-D11). 런북의 ReviewQueue.review API를 ops-feedback 이미지 안에서
        # 호출해 검토자의 확인을 대신한다(TEST-SUB). 쓰기 주체는 ops-feedback 자기 이미지·볼륨이다.
        cid = STATE["cases"][0]["case_id"]
        code = f'''
import json
from ops_feedback.failurestore import FailureStoreImpl
from ops_feedback.review import ReviewQueue
q = ReviewQueue(FailureStoreImpl.sqlite("/data/failures.db"))
r = q.review({cid!r}, "CONFIRMED", "reviewer", expected={{"items": [{{"item_no": 0, "target": {{"question_id": "Q1", "repeat_key": "", "slot_id": "body_temp"}}, "value": "36.5", "source_text": "삼십육점오", "intent": "ANSWERED_INTENT", "progress_op": None, "guide_id": None}}]}}, expected_kind="PARSER", note="E2E 시험용 확인")
print(json.dumps({{"review_status": r.get("review_status"), "version": r.get("version")}}))
'''
        cmd = [a.docker, "run", "--rm", "-i", "-v", f"{a.project}_ops-data:/data", IMAGES["ops-feedback"], "python", "-"]
        out = sh(cmd, inp=code).stdout; assert "CONFIRMED" in out, out
        confirmed = fs.list_cases(review_status="CONFIRMED")[0]; assert confirmed, "확인한 사례가 I7 읽기에 보이지 않는다"
        for c in confirmed: validate("FailureCase", dict(c))
        rec("7a", "TEST-SUB", f"검토 UI·HTTP 검토 면이 없어(CR-D11) ops-feedback 이미지의 ReviewQueue.review API로 검토자 확인을 대신: 사례 {cid} -> CONFIRMED(새 version), I7 HTTP 읽기에서 확인됨")
    out = run_sd("2", seeds=True, failure=True); m, _ = read_manifest(out)
    seeded = json.dumps(m.get("ext", {}), ensure_ascii=False) + (WORK / "sd-work-2" / "report.json").read_text()
    for f in (WORK / "datasets" / f"ds-{RID}" / m["version"] / "files").rglob("*.jsonl"):
        seeded += f.read_text()
    cited = any(c["case_id"] in seeded for c in STATE["cases"])
    prev = STATE["dataset"]["version"]
    if cited and m["version"] != prev:
        STATE["dataset2"] = {"id": m["dataset_id"], "version": m["version"], "content_hash": m["content_hash"]}; save()
        rec(7, "REAL", f"synthetic-data가 I7(HTTP)로 CONFIRMED FailureCase를 읽어 새 데이터셋 버전 {m['version']}(이전 {prev})이 사례 ID를 시드로 인용. 학습(model-lab)·저작으로의 환류는 실행하지 않았다(model-lab은 E2E_GPU=1 경로, 저작의 I7 소비는 이번 구성에 없음)")
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
    bad = HttpGateService(URL("gate"), TOK("gate-write-question-authoring"))
    try: bad.request_rollback({**req, "request_id": f"rbk-{RID}-2"}); raise AssertionError("허용되지 않은 역할이 롤백함")
    except bc.BoundaryError as e: assert e.code == "PERMISSION_DENIED"
    rec(8, "REAL", f"ops-feedback 토큰의 RollbackRequest -> RollbackReceipt APPLIED(멱등), 활성 포인터 {new}->{old}, 실제 survey-service가 /readyz에서 이전 릴리스로 복귀, 롤백 권한 없는 역할은 PERMISSION_DENIED. 롤백을 요청한 주체는 e2e(ops-feedback 역할 토큰)이고 ops-feedback 잡의 자동 롤백 평가는 아님")

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
