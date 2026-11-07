#!/usr/bin/env python3
"""합격 시나리오(docs/E2E.md) 1~8단계. 영역 사이는 실제 서비스의 HTTP(openit_link.clients; D49·D118)로 잇는다.
모든 레코드는 boundary_contracts.validator(또는 문진 스키마)와 해시로 검증한다. 9단계(인프라)는 scripts/e2e.sh.

상태: REAL(실제 서비스·잡) / TEST-SUB(시험 대역으로 대신함) / BLOCKED(지금 구현으로는 이어지지 않음) / FAIL(검증 실패)
"""
import argparse, traceback, collections.abc, hashlib, json, os, pathlib, subprocess, sys, tempfile, time, urllib.request, urllib.error, urllib.parse

import boundary_contracts as bc
from boundary_contracts import canonical
from openit_link.clients import (HttpFailureStore, HttpGateService, HttpModelRegistry, HttpQuestionReader,   # 이웃 호출은 통신 기반 라이브러리 link 의 클라이언트로만(D118)
                                 HttpReleaseReader, HttpTraceIngest)
import survey_schema, jsonschema
import e2e_asserts as EA
import sd_jobs
from boundary_contracts.action_rules import load_rules
ACTION_RULES_VERSION = load_rules()["rules_version"]   # 매니페스트·잡 설정의 규칙 세대 표지(3.0, D109): 값은 설치된 계약의 ActionExtractionRules.rules_version 에서 읽는다(리터럴을 적지 않는다)


# ---- 단계 선언의 유일한 자리(e2e_plan.py 와 verify_area.py 가 이 파일을 ast 로 읽는다. 다른 곳에 같은 선언을 쓰지 않는다)
# repos: 결과가 의존하는 소스 리포('deploy:경로,...' 는 deploy 안의 그 경로만). deps: 앞 단계의 STATE 를 읽으면 그 단계(None 은 미확인). why: 근거.
# deps 는 STATE[...] 읽기·쓰기를 ast 로 분석한 값과 같아야 한다(test_e2e_steps_decl.py).
STEP_REGISTRY = {}
def metric_registry():
    """계약의 지표 레지스트리 목록(설치된 계약 패키지의 metrics())."""
    ms = list(bc.metrics().values()); src = "boundary_contracts.metrics()"   # 계약 패키지(판은 lib.sh 기준표)가 지표 레지스트리를 준다. 옆 폴더의 파일을 읽지 않는다
    need = {"name", "group", "higher_is_better", "status", "applies_to"}
    if not isinstance(ms, list) or not ms or any(not isinstance(m, collections.abc.Mapping) or not need <= set(m) for m in ms):
        raise SystemExit(f"{src}: metrics[] 의 각 항목에 {sorted(need)} 가 있어야 한다")
    return ms


def status_www(status, headers):   # (상태, WWW-Authenticate 첫 토큰). headers 는 대소문자 무관 매핑
    h = {str(k).lower(): v for k, v in dict(headers or {}).items()}
    return status, (h.get("www-authenticate") or "").split(" ")[0].rstrip(",")

def assert_401_bearer(what, status, headers):
    """인증 없는 호출의 기대: 401 + WWW-Authenticate: Bearer (계약 CONVENTIONS 6절, RFC 9110 15.5.2·RFC 6750 3절). 403 이나 머리글 없는 401, 다른 인증 방식(Basic 등) 안내는 거부한다.
    샌드박스(D123)에서는 요청을 호출자가 게이트웨이(SB.gw_request) 또는 컨테이너 안에서 하고, 이 함수는 그 결과만 판정한다."""
    st, scheme = status_www(status, headers)
    assert st == 401 and scheme == "Bearer", f"{what}: 401 + WWW-Authenticate: Bearer 여야 한다 (실제 {st}, {scheme or '머리글 없음'})"

def sample_metrics(role):
    """EvaluationReport 샘플 지표: 레지스트리에서 ACTIVE 이고 역할(LORA_A->A, LORA_B->B)에 맞는(applies_to 가 그 역할이거나 both) 방향이 정해진 지표만. 이름은 여기에 적지 않는다."""
    r = {"LORA_A": "A", "LORA_B": "B"}[role]
    rows = [(m["name"], m["group"], 1.0 if m["higher_is_better"] else 0.0, m["higher_is_better"]) for m in metric_registry()
            if m["status"] == "ACTIVE" and m["applies_to"] in (r, "both") and isinstance(m["higher_is_better"], bool) and m.get("unit") == "ratio"]
    assert rows, f"레지스트리에 {role} 용 ACTIVE ratio 지표가 없다"
    by = {m["name"]: m for m in metric_registry()}
    assert all(by[n]["status"] == "ACTIVE" and by[n]["applies_to"] in (r, "both") for n, *_ in rows)   # 단계가 쓰는 이름은 ACTIVE 이고 역할에 맞아야 한다
    return rows


def step(name, repos, deps, why, also=None):   # also: repos 에 없어도 이 단계가 호출 경계를 보는 영역 {영역: 어느 경계인지}
    def deco(fn):
        STEP_REGISTRY[name] = fn; return fn
    return deco
_GW = ("deploy:config,compose.yaml,compose.inference.yaml,compose.external-inference.yaml,scripts/e2e_sandbox.py,test",)   # e2e_plan.py 의 _GW_SEC 와 같아야 한다(샌드박스 D123: 시험 입력은 운영 compose·추론 서버 compose·접근 계층)   # 게이트웨이(Caddyfile·계정)를 거치는 단계는 deploy 의 설정도 입력이다
_P4 = "step4 가 STATE['pointers']/['releases'] 를 쓰고 이 단계가 '\"pointers\" not in STATE' 로 BLOCKED 처리한다(e2e_steps.py 의 같은 이름 함수 앞부분)"

ap = argparse.ArgumentParser()
ap.add_argument("--project", required=True); ap.add_argument("--secrets", required=True)
ap.add_argument("--ports", required=True); ap.add_argument("--images", required=True)
ap.add_argument("--docker", default="docker"); ap.add_argument("--root", required=True)
ap.add_argument("--forms-dir", default="", help="문진표 양식 폴더(question-authoring 의 forms/). 문진표 시나리오(단계 1)가 읽는다")
ap.add_argument("--work", required=True, help="이번 실행의 임시 작업 폴더")
ap.add_argument("--run-id", default="e2e-test")
ap.add_argument("--demo-stop", action="store_true", help="demo4: 승인 대기까지만 만든다(사람이 /admin/ 에서 승인)")
ap.add_argument("--gw-ca", default="", help="gateway(HTTPS)의 내부 CA 루트 인증서 파일(시험용 CA). 있으면 gw 주소는 https 이고 이 CA만 신뢰한다")
ap.add_argument("--only", default="", help="쉼표로 구분한 단계(예: 1,2). 비우면 전부")
ap.add_argument("--ms-url", default="", help="추론 서버를 다른 곳에 둔 경우 그 주소(예: https://gpu-host). 비우면 이 프로젝트의 model-serving 컨테이너")
ap.add_argument("--ms-container", default="", help="추론 서버 컨테이너 이름(멈춤·재시작 시험용). 기본 <프로젝트>-model-serving-1")
ap.add_argument("--out-file", default="", help="compose 밖 호출자(다른 호스트 역할의 추론 서버)에게 준 OUT-FILE 폴더(RUNTIME R1.5: root_ca.crt, hosts, SHA256SUMS). e2e.sh 가 export-out-files.sh 로 만든다. 단계 5L 이 읽는다")
ap.add_argument("--ms-token-file", default="", help="외부 추론 서버의 호출자 토큰 파일(내용이 토큰 하나). 비우면 이 구성이 만든 토큰")
ap.add_argument("--llm-package", default="", help="실제 LLM 데모: make_neutral_package.py 가 만든 폴더(LORA_A, LORA_B). 단계 3이 시험용 fake 어댑터 대신 이 중립 LoRA 패키지(vllm 서빙 설정)를 게시한다")
ap.add_argument("--fail-fast", action="store_true", help="첫 FAIL 에서 중단한다(뒤 단계는 돌리지 않는다). 전체 합격이 아니다")
ap.add_argument("--changed-only", action="store_true", help="입력 해시가 마지막 PASS 와 다른 단계와 그에 의존하는 단계(+상태 재구성에 필요한 상류)만 돌린다. 단독 실행이 증명되지 않은 단계는 항상 포함(e2e_plan.py)")
ap.add_argument("--skip-ms-restart", action="store_true", help="5단계의 추론 서버 중단·복구를 건너뛴다(서버 호스트 포트가 Docker 배정이라 재시작 뒤 주소가 바뀌는 별도 프로젝트 시험용)")
a = ap.parse_args()
import e2e_sandbox as SB   # 샌드박스 접근 계층(D123): 단계는 게이트웨이·docker exec/run·다른 호스트 역할 컨테이너로만 닿는다
SB.init(project=a.project, secrets=a.secrets, gw_ca=a.gw_ca, docker=a.docker, root=a.root)
import ssl
if a.gw_ca:   # 게이트웨이 호출(urlopen)이 HTTPS 이고 이 CA 만 신뢰한다. boundary_contracts 클라이언트는 gateway 를 거치지 않아 영향 없다
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=a.gw_ca))))
PORTS = json.loads(a.ports); IMAGES = json.loads(a.images); ROOT = pathlib.Path(a.root); WORK = pathlib.Path(a.work)
WORK.mkdir(parents=True, exist_ok=True)
RID = a.run_id
_tokpath = lambda n: pathlib.Path(a.secrets) / "tokens" / pathlib.Path(n)   # 서비스 토큰 파일. 기기에는 토큰이 없다: 기기 인증은 mTLS 클라이언트 인증서 하나(계약 PUBLIC_API F절, D136)
TOK = lambda n: _tokpath(n).read_text().strip()
def INF_TOK():   # 추론 서버가 호출자(survey-service)에게 기대하는 토큰
    if a.ms_token_file:
        t = pathlib.Path(a.ms_token_file).read_text().strip()
        if not t or t.startswith("EXTERNAL_INFERENCE_TOKEN="): raise SystemExit("--ms-token-file 은 토큰 값 하나가 든 파일이어야 한다(D84)")
        return t
    return TOK("inference-survey-service")
MS_CONTAINER = a.ms_container or f"{a.project}-model-serving-1"
def _ms_port():   # 추론 서버는 멈췄다 다시 뜨면 호스트 포트가 바뀔 수 있어 매번 Docker에게 묻는다
    out = subprocess.run([a.docker, "port", MS_CONTAINER, "443/tcp"], capture_output=True, text=True).stdout
    return out.splitlines()[0].strip().rsplit(":", 1)[1] if out.strip() else PORTS["ms"]
def URL(k):   # 샌드박스(D123): 호스트에서 닿을 수 있는 주소는 게이트웨이(gw)와 다른 호스트 역할의 추론 서버(ms)뿐이다. 내부 서비스 키는 시험용 문이었으므로 실패시킨다
    if k == "ms":
        return a.ms_url.rstrip("/") if a.ms_url else (SB.inference_url() or f"https://localhost:{_ms_port()}")
    if k == "gw":
        return SB.gw_url()
    raise RuntimeError(f"샌드박스 위반: 내부 서비스 '{k}' 를 호스트에서 직접 부를 수 없다(게이트웨이·SB.exec_in/exec_py 를 쓴다, D123)")
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
    if basic: raise RuntimeError("http(basic=…) 는 없어졌다(U82): 사람 계정은 SB.gw_request(account=…) 의 OIDC 세션 쿠키")
    if data is not None: req.add_header("Content-Type", ctype)
    for hk, hv in (headers or {}).items(): req.add_header(hk, hv)
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        b = e.read()
        try: return e.code, json.loads(b)
        except Exception: return e.code, b.decode(errors="replace")
# 승인(POST /v1/approvals)은 계약 ApprovalRequest 본문을 직접 보낸다: 계약 클라이언트 HttpGateService.decide() 는 approver_id 를 본문에 싣고 report_hash 를 빠뜨릴 수 있어
# ApprovalRequest(approver_id 금지, report_hash 필수)와 어긋난다(클라이언트 수정은 계약 3.0.3). 행위자는 X-Openit-User 헤더가 유일한 길이다(D88).
APPROVER = {"ap": ("gate-write-release-approver", "trainer-test"), "op": ("gate-write-operator", "op-test")}
_REPORT_HASH = {}   # 제출 -> 처음 읽은 보고서 해시(결정 뒤에는 보고서 상태가 달라질 수 있어 같은 제출의 재전송·번복은 처음 값을 쓴다)

_CODE_OF_STATUS = {400: "INVALID_RECORD", 401: "PERMISSION_DENIED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND", 409: "CONFLICT"}

RVH = {"X-Openit-User": "reviewer-direct-e2e"}   # 검토 게시는 X-Openit-User(gateway 가 붙이는 인증 사용자)가 없으면 401(계약 6절·HTTP.md I7; 이전에는 403). gateway 를 거치지 않는 직접 호출에 시험용 값을 붙인다
OPERATOR_ID = "operator-e2e-script"   # 시험용 운영자 ID: 게이트웨이가 계정 ID를 X-Openit-User 로 붙이는 것을 스크립트가 직접 흉내 낸다
def sh(cmd, env=None, inp=None, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True, input=inp, env={**os.environ, **(env or {})})
    if check: assert r.returncode == 0, f"{cmd[:3]} 실패({r.returncode}): {(r.stderr or r.stdout)[-600:]}"
    return r
def wait(fn, timeout, what, every=2):
    # timeout 인자의 숫자(30/60/90/120/180/200/300/600)는 대부분 측정하지 않은 시작값이다(D125: 측정 최악 + 여유가 되려면 이 호스트에서 재야 한다. 값을 지어내지 않고 측정 안 함으로 적는다). 근거가 있는 것(_c1_gw 70초, _c2_gw 200초)만 그 자리에 근거가 있다.
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v: return v
        time.sleep(every)
    raise AssertionError(f"시간 초과({timeout}s): {what}")

def settled(read, timeout=30, every=1.0, what="값이 안정"):
    """R4.3: 고정 sleep 대신 '값이 더는 바뀌지 않을 때까지' 기다린다. read() 를 every 초 간격으로 읽어 연속 두 번 같으면 그 값을 돌려준다."""
    prev = read(); t = time.time()
    while time.time() - t < timeout:
        time.sleep(every); cur = read()
        if cur == prev: return cur
        prev = cur
    raise AssertionError(f"시간 초과({timeout}s): {what}")

def decision_text(dec):
    """GateDecision 요약: 결과, reject_codes, checks 각 항목(kind, result, detail), reject_reasons. 토큰·비밀은 없다."""
    out = [f"결과 {dec.get('result')} reject_codes={dec.get('reject_codes')}"]
    for c in dec.get("checks", []):
        d = c.get("detail"); out.append(f"  - {c.get('kind')}: {c.get('result')}" + (f" -- {str(d)[:400]}" if d else ""))
    for r in dec.get("reject_reasons") or []: out.append(f"  * 사유: {str(r)[:400]}")
    return "\n".join(out)

def explain_submission(sid):   # 진단용(시간 초과 메시지): 승인자 계정으로 게이트웨이의 제출 조회만 읽는다(샌드박스 D123). 판정 본문은 게이트웨이에 열리지 않아 ID 만 적는다
    """(상태, 설명 문자열). 상태를 못 읽으면 (None, 이유)."""
    try:
        v = dict(SB.gw_client(HttpGateService, account="trainer-e2e").get_submission(sid)); st = v.get("status"); txt = f"제출 {sid} 상태 {st}"
        if v.get("decision_id"): txt += f" (판정 {v['decision_id']}: 본문은 release-gate 컨테이너 안 GET /v1/decisions/{v['decision_id']})"
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

# synthetic-data 잡은 dataset-store 이미지에서 이미지 라벨 io.openit.jobs(계약 JobsDeclaration)가 선언한 argv 로 돌린다(U43): 명령 조립은 scripts/sd_jobs.py.
# 설정 스키마가 survey_schema_dir 를 필수로 요구하지만 위치는 이미지가 정한다(이미지 환경 변수가 우선: synthetic-data ADR 0019, 설정 생략은 CR-009). 값은 쓰이지 않는다
SD_UNUSED_DIR = "image-env-takes-precedence"
# 문진표(계약 3.3.0): 저자가 문진표 둘을 올린다. 둘 다 question-authoring 리포의 forms/ 에 있는 제품 양식이다(wo-320). ID·제목은 양식이 정한다. 보지 못한 문진표(QSU)는 학습에 쓰이지 않는 평가용이라 실행 ID 로 만든다.
QS, QSB, QSU = "health-screening", "health-screening-b", f"qs-{RID}-unseen"
QS_TITLE, QSB_TITLE = "건강검진 문진표", "건강검진 문진표(순서 B)"
V2_FROM, V2_TO = "현재 약물 치료 중이십니까?", "현재 약물을 복용 중이십니까?"   # 양식 v1 의 Q1.D01 질문 문장(실제 양식에서 확인, 11곳 중 첫 곳만 바꾼다): 문구 하나가 다른 둘째 버전. test_e2e_scenario_shapes 가 같은 상수로 실제 양식에서 추출한다
QS_FIRST, QSB_FIRST = "Q1.D01", "Q3"   # 첫 문항: A 는 Q1.D01, B 는 Q3 블록이 먼저(순서는 문진표 자신의 order 에서 나온다)
FORMS_DIR = pathlib.Path(a.forms_dir)   # 양식 정본은 question-authoring 리포의 forms/ (읽기만). 위치는 e2e.sh 가 --forms-dir 로 넘긴다(드라이버는 이웃 폴더 위치를 짐작하지 않는다)
def read_form(name):
    f = FORMS_DIR / name
    assert f.is_file(), f"문진표 양식이 없다: {f} (question-authoring 리포의 forms/. 다른 위치면 E2E_FORMS_DIR)"
    return f.read_text()

def upload(set_id, text, fname):   # 샌드박스(D123): 저자 경로는 게이트웨이 저자·임상검수 계정으로. 구현은 단계 1 의 도우미 하나(_c1_upload)뿐이다(호출 시점에 풀린다)
    return _c1_upload(set_id, text, fname)

@step('1', repos=('question-authoring', 'survey-service', 'boundary-contracts') + _GW, deps=(),
      why="step1 은 STATE 를 읽지 않고 게이트웨이(저자·임상 검수자 계정)로 문항 자료를 올리고 I1 읽기는 release-gate 컨테이너 안에서 한다(STATE['qs'],['qsu'] 를 씀). 실행 중 스택의 question-authoring 은 필요하다")
def step1():
    title(1, "저자가 문항 자료를 올리고 미리보기를 확인한다 (question-authoring: 저자 경로는 게이트웨이 계정, I1 읽기는 release-gate 컨테이너 안)")
    form = read_form("health-screening-v1.txt"); form_b = read_form("health-screening-short-order.txt")
    form2 = form.replace(V2_FROM, V2_TO, 1); assert form2 != form, f"문진표 A 의 둘째 버전을 만들 문구({V2_FROM!r})가 양식에 없다"
    r1, raw1 = _c1_upload(QS, form, "form1.txt")
    r2, _ = _c1_upload(QS, form2, "form2.txt")
    rb, _ = _c1_upload(QSB, form_b, "form-b.txt")
    ru, _ = _c1_upload(QSU, form.replace("현재 약물 치료 중이십니까?", "지금 약물 치료 중이십니까?"), "unseen.txt")
    # 인증 없는 입구: 게이트웨이는 401, 서비스 자신은 401 + WWW-Authenticate: Bearer (계약 CONVENTIONS.md 6절, RFC 9110 15.5.2·RFC 6750 3절)
    assert _c1_gw("GET", "/v1/drafts")[0] == 401, "인증 없이 게이트웨이 저작 경로가 열려 있다"
    c0, _, h0 = _c1_in("question-authoring", "GET", "/v1/drafts")
    assert c0 == 401 and (h0.get("www-authenticate") or "").split(" ")[0].rstrip(",") == "Bearer", ("토큰 없는 저작 경로: 401 + WWW-Authenticate: Bearer (계약 CONVENTIONS.md 6절)", c0, h0.get("www-authenticate"))
    rtok = ("qa-read-tokens", "synthetic-data")   # 읽기 토큰은 question-authoring 컨테이너 안의 읽기 토큰 목록에서(서비스 자신의 역할 검사)
    assert _c1_in("question-authoring", "GET", "/v1/drafts", auth=rtok)[0] == 403, "읽기 토큰으로 저작 경로가 열리면 안 된다"
    assert _c1_in("question-authoring", "POST", "/v1/materials?question_set_id=x&filename=x.txt", auth=rtok, raw="x")[0] == 403
    d = _c1_i1_read(QS, QSU, QSB)   # HTTP I1, 읽기 토큰(release-gate 역할)
    vers = d["versions"]; assert [v["version"] for v in vers] == ["1", "2"], vers
    assert d["latest"]["version"] == "2"
    key = lambda v: v["id"] + "@" + v["version"]
    for v in vers + [d["latest_u"], d["latest_b"]]:
        bank = d["banks"][key(v)]
        assert canonical.content_hash(bank) == v["content_hash"]; assert str(bank["version"]) == v["version"]
        validate_survey("QuestionBank", bank)
        assert bank["question_set_id"] == v["id"], ("문진표 은행의 question_set_id 가 참조의 ID 와 다르다", bank["question_set_id"], v["id"])
        revs = d["reviews"][key(v)]; assert len(revs) == 1, ("1인 운영: 저자의 확정이 남긴 검수 하나여야 한다", len(revs))
        for r_ in revs: validate("ReviewRecord", r_)
        rv = revs[-1]
        assert rv["decision"] == "APPROVED" and rv["clinical_basis_approved"] is True and rv["question_set"] == v and rv["reviewer_id"] == "author-e2e", ("저자의 확정이 임상 근거 승인(clinical_basis_approved=true)을 함께 남겨야 한다", rv)
    assert d["reviews"][key(vers[0])][0]["ext"]["question-authoring"]["source"]["source_hash"] == "sha256:" + hashlib.sha256(raw1).hexdigest()
    cc = d["change"][key(vers[1])]; validate("ChangeClassification", cc); assert d["change"][key(vers[0])] is None
    assert d["banks"][key(vers[-1])]["title"] == QS_TITLE and d["banks"][key(d["latest_b"])]["title"] == QSB_TITLE, ("문진표 제목", d["banks"][key(vers[-1])]["title"], d["banks"][key(d["latest_b"])]["title"])
    assert d["latest_b"]["id"] == QSB and d["latest_b"]["version"] == "1", d["latest_b"]
    STATE["qs"] = [dict(v) for v in vers]; STATE["qsu"] = dict(d["latest_u"]); STATE["qsb"] = dict(d["latest_b"]); save()
    rec(1, "REAL", f"등록→미리보기→확인 x3(게이트웨이 저자 계정; 1인 운영이라 확정이 임상 근거 승인을 함께 남기고 검수 역할은 /v1/reviews 403), I1 읽기(release-gate 컨테이너 안, 읽기 토큰; 읽기 토큰은 저작 경로 403): QuestionBank 3건(해시·문진 스키마), ReviewRecord(clinical_basis_approved), ChangeClassification {cc['change_kinds']} {cc['affected_slots']}, 원본 해시 출처 일치")

# ===================== 단계 1~5 의 접근 계층 (샌드박스, wo-442) =====================
# 왜: E2E 는 제품 구성에 시험용 문(내부 서비스 호스트 포트)을 내고 그 문으로 들어가 "운영 입구만으로 되는가"를 증명하지 못했다.
# 이제 접근은 셋뿐이다: (a) 게이트웨이(계정·기기 토큰) (b) 제품 네트워크 안(docker compose exec/run, 그 일을 운영에서 하는 주체의 컨테이너) (c) 다른 호스트 역할의 추론 서버(inference_url).
# 새 도우미는 이름 앞에 _c1_ 을 붙인다. 이 구간 안의 옛 이름(gw_raw, gw_text, kiosk, state_of, gws, survey_ready, ms_call, decisions_for, ADMIN 등)은
# 뒤 단계가 같은 이름으로 부르므로 시그니처를 유지한 채 내용만 바꾼다.
import base64, e2e_sandbox as SB

_C1_AUTHOR, _C1_CLINICAL = "author-e2e", "clinical-e2e"            # 저자 / 임상 근거 검수자 계정(Keycloak 시험 사용자: test/gateway-oidc/accounts.test.conf 를 scripts/idp-test-users.sh 가 만든다)
_C1_APPROVER, _C1_OPERATOR = "trainer-e2e", "operator-e2e"         # release-approver / operator 계정. 게이트웨이가 계정 ID 를 X-Openit-User 로 붙인다(행위자 기록)
_C1_CODE = {400: "INVALID_RECORD", 401: "PERMISSION_DENIED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND", 409: "CONFLICT"}
_C1_RH = {}   # 제출 -> 처음 읽은 보고서 해시(결정 뒤에는 보고서 상태가 달라질 수 있어 같은 제출의 재전송·번복은 처음 값을 쓴다)

class _C1Hdr(dict):
    """대소문자 구분 없는 머리글 사전(원래 키 철자도 그대로 가진다: 호출하는 쪽이 'Cache-Control' 로도 'cache-control' 로도 찾는다)."""
    def get(self, k, d=None): return next((v for kk, v in self.items() if str(kk).lower() == str(k).lower()), d)
    def __getitem__(self, k):
        for kk, v in self.items():
            if str(kk).lower() == str(k).lower(): return v
        raise KeyError(k)
    def __contains__(self, k): return any(str(kk).lower() == str(k).lower() for kk in self.keys())

def _c1_dec(b):
    """응답 본문 -> JSON 이면 파싱한 값, 아니면 문자열(빈 본문은 None)."""
    if isinstance(b, (bytes, bytearray)): b = bytes(b).decode(errors="replace")
    if isinstance(b, str):
        try: return json.loads(b) if b.strip() else None
        except ValueError: return b
    return b

def _c1_gw(method, path, *, account=None, token=None, body=None, data=None, headers=None, timeout=70.0):   # 클라이언트 읽기 대기는 gateway 환자 경로 상한(56s)보다 길게(D125, 키오스크 대기 60s + 여유)
    """(a) 게이트웨이 입구. account=계정 ID(암호는 접근 계층이 안다), token=기기 토큰(Bearer). (상태, 본문, 머리글)."""
    kw = {}
    if body is not None: kw["json"] = body
    if data is not None: kw["data"] = data
    c, h, b = SB.gw_request(method, path, account=account, token=token, headers=(dict(headers) if headers else None), timeout=timeout, **kw)
    return c, _c1_dec(b), _C1Hdr(dict(h.items()) if hasattr(h, "items") else dict(h))

def _c1_tok(name):
    """게이트웨이에 내는 서비스 자격(기계 토큰). 서비스 내부 토큰은 읽지 않는다: 그것은 컨테이너 안에서만 읽는다."""
    return _tokpath(name).read_text().strip()

# 컨테이너 안에서 도는 코드의 앞부분. tok(): /run/secrets 의 비밀 파일(단일 토큰 또는 '역할=토큰,...' 목록)에서 토큰을 읽는다(값은 출력하지 않는다). call(): 표준 라이브러리 HTTP.
_C1_PRE = r'''
import json, os, sys, urllib.request, urllib.error
def tok(name, role=None):
    for p in open("/run/secrets/" + name).read().replace("\n", ",").split(","):
        p = p.strip()
        if not p: continue
        r, _, t = p.rpartition("=")
        if role is None or r == role: return t
    raise SystemExit("secret %s role %s not found" % (name, role))
def call(method, url, token=None, body=None, headers=None, raw=None, ctype="application/json", parse=True):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    rq = urllib.request.Request(url, data=data, method=method)
    if token: rq.add_header("Authorization", "Bearer " + token)
    if data is not None: rq.add_header("Content-Type", ctype)
    for k, v in (headers or {}).items(): rq.add_header(k, v)
    try:
        with urllib.request.urlopen(rq, timeout=30) as r: st, hd, b = r.status, r.headers, r.read()
    except urllib.error.HTTPError as e: st, hd, b = e.code, e.headers, e.read()
    if parse:
        try: pb = json.loads(b) if b else None
        except ValueError: pb = b.decode(errors="replace")
    else: pb = b.decode(errors="replace")
    return st, pb, {k.lower(): v for k, v in hd.items()}
def out(x): print("\n@@C1@@" + json.dumps(x, default=lambda o: dict(o)))
'''
_C1_RD = 'from openit_link.clients import HttpReleaseReader, HttpGateService\nrd = HttpReleaseReader("https://release-gate", tok("gate-read-survey-service"))\n'   # I4 읽기: survey-service 가 쓰는 읽기 토큰과 주소

def _c1_lit(obj): return f"json.loads({json.dumps(obj)!r})"   # 코드에 값을 싣는 법: JSON 문자열을 파이썬 리터럴로(비밀 값은 싣지 않는다)

def _c1_run(service, code, timeout=120):
    """(b) 제품 네트워크 안: service 컨테이너에서 파이썬을 돌리고 out() 으로 낸 JSON 한 개를 돌려준다."""
    txt = SB.exec_py(service, _C1_PRE + code, timeout=timeout)
    i = txt.rfind("@@C1@@")
    assert i >= 0, f"{service} 컨테이너의 스크립트가 결과를 내지 않았다: {txt[-300:]}"
    return json.loads(txt[i + 6:].strip().splitlines()[0])

def _c1_in(service, method, path, *, auth=None, headers=None, body=None, raw=None, base="@SELF@"):
    """그 서비스 컨테이너 안에서 자기 포트를 부른다(서비스 자신의 인증·역할 검사를 본다). auth=(비밀 파일 이름, 역할 또는 None). (상태, 본문, 소문자 머리글)."""
    arg = {"m": method, "u": base + path, "auth": list(auth) if auth else None, "h": headers or {}, "b": body, "raw": raw}
    st, pb, hd = _c1_run(service, f"A = {_c1_lit(arg)}\nt = tok(*A['auth']) if A['auth'] else None\n"
        "out(call(A['m'], A['u'], t, A['b'], A['h'], A['raw'].encode() if A['raw'] is not None else None, 'text/plain' if A['raw'] is not None else 'application/json'))\n")
    return st, pb, _C1Hdr(hd)

def _c1_job(job, args=()):
    """(b) docker compose run --rm <job-*>. (종료 코드, 표준 출력). 종료 코드가 0 이 아니어도 돌려준다(수집기는 75 도 정상 종료 중 하나)."""
    try: r = SB.run_job(job, args)
    except subprocess.CalledProcessError as e: r = e
    if isinstance(r, tuple): rc, o = r[0], (r[1] if len(r) > 1 else "")
    elif hasattr(r, "returncode"): rc, o = r.returncode, (r.stdout or "")
    else: rc, o = 0, r
    return rc, (o.decode(errors="replace") if isinstance(o, bytes) else str(o or ""))

# 계약 3.3.0: 후보의 문진표는 목록이다(subject.question_sets, 1개 이상). 이 E2E 의 릴리스는 문진표 둘(health-screening 버전 하나 + health-screening-b)을 함께 담는다.
# 제출을 문진표 버전으로 구분하려고 키는 주 문진표(QS)의 버전을 쓴다. 보지 못한 문진표(QSU)의 후보는 문진표 하나짜리다.
def _subj(v, a, b): return {"question_sets": [v, STATE["qsb"]], "lora_a": a, "lora_b": b}
def _subj_u(a, b): return {"question_sets": [STATE["qsu"]], "lora_a": a, "lora_b": b}

def _c1_decisions(subj):
    """I4 find_decisions(최신부터). survey-service 컨테이너 안에서 읽는다(운영에서 판정을 읽는 쪽)."""
    return _c1_run("survey-service", _C1_RD + f"A = {_c1_lit(subj)}\nout([dict(d) for d in rd.find_decisions(question_set=A['question_sets'][0], lora_a=A['lora_a'], lora_b=A['lora_b'])[0]])\n")

def _c1_release(rid):
    """ReleaseManifest 를 읽고 번들을 받아 해시를 검증한다(클라이언트가 검증). survey-service 컨테이너 안(운영에서 번들을 받는 쪽)."""
    return _c1_run("survey-service", _C1_RD + f"import pathlib, shutil, tempfile\nrid = {rid!r}\nrel = dict(rd.get_release(rid))\ntmp = tempfile.mkdtemp()\n"
        "try: rd.load_bundle(rid, dest=pathlib.Path(tmp) / 'b')\nfinally: shutil.rmtree(tmp, ignore_errors=True)\nout(rel)\n", timeout=180)

def _c1_pointer():
    """활성 포인터: 운영자 계정으로 게이트웨이 GET /v1/active-pointer -> {'item': ActivePointer|null}."""
    c, b, _ = _c1_gw("GET", "/v1/active-pointer", account=_C1_OPERATOR); assert c == 200, ("active-pointer 조회 실패", c, str(b)[:100])
    return (b or {}).get("item")

def _c1_activate(rid):
    c, b, _ = _c1_gw("POST", "/v1/activate", account=_C1_OPERATOR, body={"requested_by_role": "operator", "release_id": rid})
    return c, b

def form_for(set_id, text):
    """양식 머리의 `문진표 ID:`·`문진표 제목:`(question-authoring ADR 0027)을 올리는 ID 와 맞춘다: 서버는 쿼리의 question_set_id 와 머리의 ID 가 다르면 거절한다. 머리가 있으면 ID 만 바꾸고 제목은 둔다, 없으면 앞에 붙인다."""
    import re
    if re.search(r"^문진표 ID:", text, re.M): return re.sub(r"^문진표 ID:.*$", f"문진표 ID: {set_id}", text, count=1, flags=re.M)
    return f"문진표 ID: {set_id}\n문진표 제목: 시험 문진표 {set_id}\n" + text

def _c1_upload(set_id, text, fname):
    """저자 경로(게이트웨이, 저자 계정)로 자료 등록 -> 미리보기 -> 확인, 임상 검수자 계정이 임상 근거를 승인한다(4-eyes). (문항 세트 참조, 원본 바이트)."""
    raw = form_for(set_id, text).encode()
    c, d, _ = _c1_gw("POST", f"/v1/materials?question_set_id={set_id}&filename={fname}", account=_C1_AUTHOR, data=raw, headers={"Content-Type": "application/octet-stream"}); assert c == 200, f"자료 등록 {c} {d}"
    c, pv, _ = _c1_gw("GET", f"/v1/drafts/{d['draft_id']}/preview", account=_C1_AUTHOR); assert c == 200 and pv["ready_to_confirm"], pv
    c, ref, _ = _c1_gw("POST", f"/v1/drafts/{d['draft_id']}/confirm", account=_C1_AUTHOR, body={"preview_hash": pv["preview_hash"]}); assert c == 200, ref
    # 1인 운영(QA_REQUIRE_TWO_PERSON=false, 사용자 결정 L13, 서비스 기본): 저자의 확정(confirm_finalize)이 clinical_basis_approved=true 를 함께 남긴다. 별도 임상 검수 호출은 없다
    # 설계 확인: 이 모드에서 임상 검수 역할에는 검수 경로(/v1/reviews)가 열리지 않는다(access_policy: reviewer_ok 와 require_two_person 이 모두 참일 때만) -> 403
    c, rv, _ = _c1_gw("POST", "/v1/reviews", account=_C1_CLINICAL, body={"question_set": ref, "decision": "APPROVED", "clinical_basis_approved": True, "reason": "E2E: 1인 운영에서 검수 역할은 거부돼야 한다"}); assert c == 403 and rv.get("code") == "PERMISSION_DENIED", ("1인 운영에서 임상 검수 역할이 /v1/reviews 를 통과했다", c, rv)
    return ref, raw

def _c1_i1_read(qs, qsu, qsb):
    """I1 읽기(문항 세트 버전·본문·검수·변경 분류). 읽는 주체는 release-gate(읽기 토큰 qa-read-release-gate): 그 컨테이너 안에서 한다."""
    return _c1_run("release-gate", f"A = {_c1_lit({'qs': qs, 'qsu': qsu, 'qsb': qsb})}\nfrom openit_link.clients import HttpQuestionReader\n"
        "rd = HttpQuestionReader('https://question-authoring', tok('qa-read-release-gate'))\n"
        "vers = [dict(v) for v in rd.list_versions(A['qs'])[0]]\nlatest = dict(rd.latest(A['qs'], reviewed_only=True))\nlatest_u = dict(rd.latest(A['qsu'], reviewed_only=True))\nlatest_b = dict(rd.latest(A['qsb'], reviewed_only=True))\n"
        "banks, revs, chg = {}, {}, {}\nfor v in vers + [latest_u, latest_b]:\n    k = v['id'] + '@' + v['version']\n    banks[k] = rd.get_question_bank(v); revs[k] = [dict(r) for r in rd.get_reviews(v)]; c = rd.get_change(v); chg[k] = dict(c) if c is not None else None\n"
        "out({'versions': vers, 'latest': latest, 'latest_u': latest_u, 'latest_b': latest_b, 'banks': banks, 'reviews': revs, 'change': chg})\n")

def _c1_pack(pk):
    """게시 대상(패키지 매니페스트, 평가 보고서, 어댑터 파일들)을 컨테이너에 실어 보낼 모양으로. 어댑터는 작은 파일 묶음이라 base64 로 코드에 싣는다."""
    items, total = [], 0
    for role, (mf, adir, rep) in pk.items():
        files = {str(p.relative_to(adir)): base64.b64encode(p.read_bytes()).decode() for p in sorted(pathlib.Path(adir).rglob("*")) if p.is_file()}
        total += sum(len(v) for v in files.values())
        items.append({"role": role, "manifest": mf, "report": json.dumps(rep, ensure_ascii=False, sort_keys=True), "files": files})
    assert total < 60 * 1024 * 1024, f"어댑터가 커서 코드에 실을 수 없다({total} 바이트): 큰 어댑터는 컨테이너로 복사하는 접근 계층 API 가 필요하다"
    return items

def decide_approval(who, sid, decision, *, reason=None, report_hash=None):
    """who: 'ap' = 승인자 계정(게이트웨이 POST /v1/approvals) | 'op' = operator 쓰기 토큰을 게이트 컨테이너 안에서(권한 시험: 서비스 자신의 역할 검사). 실패는 bc.BoundaryError 로."""
    body = {"submission_id": sid, "decision": decision, "approver_role": "release-approver", "report_hash": report_hash or _c1_report_hash(sid)}
    if reason is not None: body["reason"] = reason
    validate("ApprovalRequest", body)
    if who == "ap": c, b, _ = _c1_gw("POST", "/v1/approvals", account=_C1_APPROVER, body=body)
    else: c, b, _ = _c1_in("release-gate", "POST", "/v1/approvals", auth=("gate-write-tokens", "operator"), headers={"X-Openit-User": "op-test"}, body=body)
    if c in (200, 201): return b.get("approval", b) if isinstance(b, dict) else b
    j = b if isinstance(b, dict) else {}
    raise bc.BoundaryError(j.get("code") or _C1_CODE.get(c, "FAILED_PRECONDITION"), j.get("message") or f"HTTP {c}")

def _c1_report_hash(sid):
    """GET review-report 응답 머리글 X-Openit-Report-Hash 를 그대로 쓴다(화면은 계산하지 않는다)."""
    if sid not in _C1_RH:
        c, r, h = _c1_gw("GET", f"/v1/submissions/{sid}/review-report", account=_C1_APPROVER); assert c == 200, ("review-report 조회 실패", c, str(r)[:100])
        assert (h.get("x-openit-report-hash") or "").startswith("sha256:"), ("review-report 에 X-Openit-Report-Hash 가 없다", dict(h))
        _C1_RH[sid] = h.get("x-openit-report-hash")
    return _C1_RH[sid]

def _c1_explain(sid):
    """(상태, 설명 문자열). 상태를 못 읽으면 (None, 이유)."""
    try:
        c, v, _ = _c1_gw("GET", f"/v1/submissions/{sid}", account=_C1_APPROVER)
        if c != 200 or not isinstance(v, dict): return None, f"제출 {sid} 상태를 읽지 못했다: HTTP {c}"
        st = v.get("status"); txt = f"제출 {sid} 상태 {st}"
        if v.get("decision_id"): txt += "\n" + decision_text(_c1_run("survey-service", _C1_RD + f"out(dict(rd.get_decision({v['decision_id']!r})))\n"))
        return st, txt
    except Exception as e:
        return None, f"제출 {sid} 상태를 읽지 못했다: {type(e).__name__}: {str(e)[:120]}"

def _c1_wait_report(sid, label, timeout=60):
    """자동 검사 후 승인 요청 보고서를 기다린다(승인자 화면과 같은 경로). 제출이 반려(REJECTED_*)되면 시간 초과를 기다리지 않고 GateDecision 의 checks 를 보여 주며 실패한다."""
    t = time.time()
    while time.time() - t < timeout:
        c, r, _ = _c1_gw("GET", f"/v1/submissions/{sid}/review-report", account=_C1_APPROVER)
        if c == 200 and isinstance(r, dict): return r
        st, txt = _c1_explain(sid)
        if st in ("REJECTED_AUTO", "REJECTED_HUMAN"): raise AssertionError(f"제출 {label} 이(가) 반려되어 승인 요청 보고서가 생기지 않는다.\n{txt}")
        time.sleep(2)   # 폴링 간격(반려되면 즉시 중단, 종료 조건은 보고서 생성)
    raise AssertionError(f"시간 초과({timeout}s): 자동 검사 후 승인 요청 보고서 {label}.\n{_c1_explain(sid)[1]}")

def sd_config(name, seeds, failure=False, version=None):
    cfg = {"dataset_id": f"ds-{RID}", "seed": 20261015, "created_at": "2026-10-15T00:00:00Z",
           "action_rules_version": ACTION_RULES_VERSION, "survey_schema_dir": SD_UNUSED_DIR,
           "adapters": {"question_reader": {"kind": "http", "base_url": SD_QA_JOB_URL, "token_secret": "QUESTION_READER_TOKEN"}},   # 계약 HttpClientSettings(4.0.0, D135): 역할이 클라이언트를 정하고 설정은 주소·토큰 비밀 이름뿐이다(구현 모듈 경로 factory 없음)
           "question_sets": [{"id": QS, "version": STATE["qs"][-1]["version"], "usage": "TRAIN_POOL"}, {"id": QSU, "usage": "HELD_OUT_EVAL"}],
           "reviewed_only": True, "seeds": {"enabled": seeds},
           "split": {"ratios": {"TRAIN": 0.8, "VALIDATION": 0.1, "EVAL": 0.1}},
           "review": {"per_kind": 2}, "regeneration": {"mode": "full"},
           "output": {"work_dir": str(WORK / f"sd-work-{name}"), "store": {"kind": "file", "root": str(WORK / "datasets")}}}
    if failure:
        cfg["adapters"]["failure_store"] = {"kind": "http", "base_url": SD_OPS_JOB_URL, "token_secret": "FAILURE_STORE_TOKEN"}   # 계약 HttpClientSettings(D135)
        cfg["seeds"]["question_set_id"] = QS
    validate("SyntheticJobConfigRun", cfg)   # R7: 설정을 쓰기 전에 계약으로 검증한다(어기면 잡이 아니라 여기서 멈춘다)
    p = WORK / f"sd-{name}.job.json"; p.write_text(json.dumps(cfg, ensure_ascii=False, indent=1)); return p

# 실패 진단(사용자 지시: 검사가 실패하면 이유를 산출한다): $W/diag/ 에 남기면 e2e.sh 가 정리 전에 state/e2e-diag-<시각>/ 로 복사한다.
# 비밀 금지: 잡 명령에는 비밀 값이 없다(NAME_FILE 경로와 파일 마운트 경로뿐, D84). 환경 변수 목록(env, Config.Env)은 어디에도 남기지 않는다.
DIAG = WORK / "diag"
CUR_STEP = ["-"]   # 지금 도는 단계 이름(아래 단계 루프가 정한다)

def diag_write(name, text):
    try:
        DIAG.mkdir(parents=True, exist_ok=True)
        with open(DIAG / name, "a", encoding="utf-8") as f: f.write(text)
    except OSError: pass   # 진단을 못 남겨도 시험 결과를 바꾸지 않는다

def tail_lines(text, n=200):
    return "\n".join((text or "").splitlines()[-n:])

def run_job(job_name, cfg_path, *, network, extra_ro=(), environment=None):
    """network 는 호출자가 고른다(기본값 없음): 컨테이너 안에서 도는 잡은 compose 네트워크 + 서비스 이름 주소로 이웃에 닿는다."""
    """dataset-store 이미지의 라벨 io.openit.jobs 에서 잡 job_name 을 찾아 docker run 으로 돌린다(명령 조립: sd_jobs.docker_cmd)."""
    img = IMAGES["dataset-store"]
    labels = json.loads(sh([a.docker, "image", "inspect", img, "--format", "{{json .Config.Labels}}"]).stdout)
    job = sd_jobs.find_job(labels, job_name, bc.validator)
    inputs = json.loads(labels["io.openit.inputs"])
    bc.validator("ContainerInputs").validate(inputs)
    cfg = json.loads(pathlib.Path(cfg_path).read_text())
    if job.get("config", {}).get("schema"): validate(job["config"]["schema"], cfg)   # 영역이 선언한 설정 스키마(계약)로 deploy 가 만든 설정을 먼저 검사한다
    r = sd_jobs.execute_job(a.docker, img, job, cfg_path, WORK, a.secrets, os.getuid(), os.getgid(), extra_ro,
                            network=network, pki_root_volume=f"{a.project}_pki-root", declaration=inputs, environment=environment)
    if r.returncode != 0:   # 단계 4 처럼 종료 코드를 기대하는 호출(허용치 초과 4 등)도 남긴다: 기대한 실패인지는 읽는 사람이 판단한다
        diag_write(f"{CUR_STEP[0]}-{job_name}.log", f"## {job_name} 종료 코드 {r.returncode} (단계 {CUR_STEP[0]}, 네트워크 {network})\n## 명령(비밀 값 없음: 파일 경로만)\n{' '.join(r.args)}\n## stderr 끝 200줄\n{tail_lines(r.stderr)}\n## stdout 끝 50줄\n{tail_lines(r.stdout, 50)}\n\n")
    # 종료 코드 2 는 설정 오류다(계약 SyntheticJobError): 우리가 만든 설정이 거부된 것이므로 어떤 단계도 기대하지 않는다. 계약으로 읽어 사유를 보고한다
    assert r.returncode != 2, f"{job_name}: {sd_jobs.describe_failure(r.returncode, r.stderr, bc.validator)}"
    return r

def run_sd(name, seeds, failure=False):
    p = sd_config(name, seeds, failure)
    # 영역 pod(dataset-store-net) 안에서 돌아 자기 게이트웨이의 loopback 출구로 이웃을 부른다(R1.8, 운영의 백업 잡과 같은 방식). 망을 직접 잇지 않는다(2026-11-07 교차검증)
    r = run_job("synthetic-run", p, network=SD_RUN_NETWORK(), environment={"OPENIT_EGRESS_PROXY": SD_EGRESS_PROXY})
    assert r.returncode == 0, f"synthetic-data {sd_jobs.describe_failure(r.returncode, r.stderr, bc.validator)}"
    return json.loads(r.stdout.strip().splitlines()[-1])

def read_manifest(out):
    root = WORK / "datasets" / f"ds-{RID}" / out["version"]
    m = json.loads((root / "manifest.json").read_text()); validate("DatasetManifest", m); return m, root

IMPORT_DIR = ROOT / "test/import-v2"   # 이 E2E 를 위해 직접 만든 아주 작은 v2 형식 jsonl 6개(실제 학습 데이터가 아니다, test/import-v2/make_rows.py)
def imp_config(name, max_invalid_rows, store_root):
    q = STATE["qs"][-1]   # 문항 세트 출처: CR-006 미정이라 임시로 이 E2E 가 단계 1 에서 만든 문항 세트 참조를 적는다(deploy 가 정한 값이 아니다)
    cfg = {"dataset_id": f"ds-{RID}", "input_dir": str(IMPORT_DIR), "survey_schema_dir": SD_UNUSED_DIR,
           "question_sets": [{"id": QS, "version": q["version"], "content_hash": q["content_hash"]}],
           "source_label": "deploy-e2e-test-data", "action_rules_version": ACTION_RULES_VERSION, "created_at": "2026-10-27T00:00:00Z",
           "tolerance": {"max_invalid_rows": max_invalid_rows, "max_invalid_rate": 1.0},
           "output": {"work_dir": str(WORK / f"sd-import-{name}"), "store": store_root if isinstance(store_root, dict) else {"kind": "file", "root": str(store_root)}}}
    validate("SyntheticJobConfigImport", cfg)   # R7: 설정을 쓰기 전에 계약으로 검증한다
    p = WORK / f"sd-import-{name}.json"; p.write_text(json.dumps(cfg, ensure_ascii=False, indent=1)); return p

# synthetic-run 잡이 부르는 이웃(문항 읽기 question-authoring, 실패 사례 ops-feedback)은 compose 의 authoring 네트워크에 함께 붙어 있다(compose.yaml 이 정본, test_e2e_job_urls 가 대조).
def SD_RUN_NETWORK():
    """dataset-store 앱 컨테이너가 붙은 영역 pod 의 네트워크 공간(container:<pause>). 바깥에서 docker inspect 로 읽는다(영역 안에 들어가지 않는다)."""
    mode = sh([a.docker, "inspect", f"{a.project}-dataset-store-1", "--format", "{{.HostConfig.NetworkMode}}"]).stdout.strip()
    assert mode.startswith("container:"), f"dataset-store 가 영역 pod 공간에 붙어 있지 않다: {mode}"
    return mode
SD_EGRESS_PROXY = "http://127.0.0.1:3128"   # 계약 CommonEnv.OPENIT_EGRESS_PROXY: 영역 게이트웨이의 loopback CONNECT 출구(compose x-common-env 와 같은 값)
SD_QA_JOB_URL = "https://question-authoring"    # 서비스 이름·컨테이너 포트
SD_OPS_JOB_URL = "https://ops-feedback"
DS_JOB_NETWORK = lambda: f"{a.project}_datasets"   # dataset-store(I2) 전용 internal 네트워크(compose.yaml networks.datasets). 잡은 서비스 이름 dataset-store 로 닿는다
DS_JOB_URL = "https://dataset-store"   # 잡 컨테이너가 쓰는 dataset-store 주소(서비스 이름·컨테이너 포트). 호스트에서 부르는 URL("ds") 와 다르다

def run_import(name, max_invalid_rows, store_root):
    p = imp_config(name, max_invalid_rows, store_root)
    # 저장소가 http(dataset-store)면 잡은 컨테이너 안에서 도므로 호스트 주소(127.0.0.1)는 자기 자신이다: compose 의 datasets 네트워크에 붙이고 서비스 이름 주소를 쓴다
    net = DS_JOB_NETWORK() if isinstance(store_root, dict) and store_root.get("kind") == "http" else "none"   # 파일 저장소 게시는 닿을 이웃이 없다
    r = run_job("synthetic-import", p, network=net, extra_ro=[IMPORT_DIR])
    out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    return r.returncode, out, json.loads((WORK / f"sd-import-{name}" / "import_report.json").read_text())

@step('2', repos=('synthetic-data', 'survey-service') + _GW, deps=('1',),
      why="step2 는 run_import 로 STATE['qs'](step1 이 씀)를 읽는다(imp_config)")
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
            c, info_body, _ = ms_call("/v1/info", None, INF_TOK(), method="GET"); info = json.loads(info_body); ex = info.get("serving_config_expectation") or {}
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
        c, info_body, _ = ms_call("/v1/info", None, INF_TOK(), method="GET"); info = json.loads(info_body); assert c == 200, (c, info)
        ex = info["serving_config_expectation"]
        # LORA_A 는 제약 디코딩(ActionExtraction JSON), LORA_B 는 문장이라 제약 없음(model-runtime make_neutral_package.py 와 같은 규칙)
        mkcfg = lambda mode: {"prompt_template_version": ex["prompt_template_version_default"],
               "decoding": {"constraint_mode": mode, "temperature": 0, "retry_temperature": 0.7, "seed": 1000, "max_tokens": 512}, "max_attempts": 3,
               "constraint": ex["constraint"], "output_contract": ex["output_contract"], "protection_policy_version": ex["protection_policy_versions"][-1]}
        cfgs = {"LORA_A": mkcfg("constrained"), "LORA_B": mkcfg("none")}
        # 대조: survey 이미지(model-runtime)의 fake_serving_configs 와 일치하는지
        probe = "import json, model_runtime as m\nprint(json.dumps(m.fake_serving_configs()['LORA_A']))\n"
        try:
            ref = json.loads(SB.exec_py("survey-service", probe).strip().splitlines()[-1])
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
              "lineage": {"dataset": STATE["dataset"], "training_run_id": f"run-{RID}-1", "action_rules_version": ACTION_RULES_VERSION,
                          "model_runtime_version": d["runtime"], "question_sets": STATE["qs"][-1:]},
              "eval_report_ref": f"eval-{RID}-{role.lower().replace('_', '-')}"}
        mf["system_prompt"] = d["system_prompt"][role]   # 모델 패키지의 일부(D75): 어댑터 디렉터리 안 파일의 {path, sha256}
        if a.llm_package: mf["ext"] = gm[role].get("ext", {})   # 중립(학습하지 않은) 패키지 표시
        mf["content_hash"] = canonical.content_hash(mf); validate("ModelPackageManifest", mf)
        ref = {"id": mf["package_id"], "version": mf["version"], "content_hash": mf["content_hash"]}
        # 시험용 EvaluationReport: 지표 값은 고정된 시험 값이다(실제 평가가 아니다). METRICS.md의 이름을 쓴다
        rows = sample_metrics(role)   # 이름은 계약의 지표 레지스트리에서만 읽는다
        rep = {"pipeline_schema_version": bc.PIPELINE_SCHEMA_VERSION, "report_id": mf["eval_report_ref"], "created_at": "2026-10-15T00:00:00Z", "role": role,
               "package": ref, "dataset": STATE["dataset"], "question_sets": STATE["qs"][-1:],
               "evaluation_backend": {"name": "test-fixed-metrics", "version": "1", "constrained_decoding": False}, "decoding": {"temperature": 0, "seed": 1},
               "metrics": [{"name": n, "group": g, "value": v, "n": 40, "higher_is_better": h, "unit": "ratio", "slice": {"kind": "ALL", "value": "ALL"}} for n, g, v, h in rows],
               "notes": ["TEST: 시험용 고정 지표. 실제 평가가 아니다(E2E 단계 3 대역)"]}
        rep["content_hash"] = canonical.content_hash(rep); validate("EvaluationReport", rep)
        pk[role] = (mf, adir[role], rep)
    return pk

def publish_packages(pk):
    """make_packages() 의 패키지 2건을 model-registry 에 HTTP 로 게시(멱등 확인)하고 읽기 토큰으로 다시 읽어 해시를 검증한다. 단계 3 과 demo.sh swap-adapters 가 같이 쓴다. {역할: 참조} 를 돌려준다.
    게시 주체(model-lab)의 쓰기 토큰은 model-registry 가 아는 쓰기 토큰 목록의 model-lab 항목이다: 쓰기는 model-registry 컨테이너 안에서, 읽기 검증은 release-gate 컨테이너 안(읽기 토큰 release-gate)에서 한다."""
    refs = _c1_run("model-registry", f"A = {_c1_lit(_c1_pack(pk))}\nimport base64, pathlib, shutil, tempfile\nfrom openit_link.clients import HttpModelRegistry\n"
        "reg = HttpModelRegistry('@SELF@', tok('model-registry-write-tokens', 'model-lab'))\nroot = pathlib.Path(tempfile.mkdtemp()); refs = {}\ntry:\n"
        "    for it in A:\n        d = root / it['role']\n        for rel, b in it['files'].items():\n            p = d / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(base64.b64decode(b))\n"
        "        mf = it['manifest']; rb = it['report'].encode()\n        got = reg.publish(mf, d, rb); again = reg.publish(mf, d, rb)\n        assert dict(again) == dict(got), 'publish is not idempotent'\n"
        "        refs[it['role']] = {'id': mf['package_id'], 'version': mf['version'], 'content_hash': mf['content_hash']}\nfinally: shutil.rmtree(root, ignore_errors=True)\nout(refs)\n", timeout=180)
    want = {role: {"id": mf["package_id"], "version": mf["version"], "content_hash": mf["content_hash"]} for role, (mf, adir, rep) in pk.items()}
    assert refs == want, ("게시 결과 참조가 매니페스트와 다르다", refs, want)
    got = _c1_run("release-gate", f"A = {_c1_lit([dict(role=r, **want[r]) for r in want])}\nimport pathlib, shutil, tempfile\nfrom boundary_contracts import canonical\nfrom openit_link.clients import HttpModelRegistry\n"
        "rr = HttpModelRegistry('https://model-registry', tok('model-registry-read-release-gate'))\nroot = pathlib.Path(tempfile.mkdtemp()); res = {}\ntry:\n"
        "    for it in A:\n        g = dict(rr.get_manifest(it['id'], it['version'])); rep = rr.get_eval_report(g['eval_report_ref'])\n"
        "        p = rr.open_adapter(it['id'], it['version'], dest=root / it['role'])   # 해시 검증 포함\n"
        "        res[it['role']] = {'manifest': g, 'report': rep.decode(), 'adapter_ok': canonical.directory_hash(p) == g['adapter_hash']}\nfinally: shutil.rmtree(root, ignore_errors=True)\nout(res)\n", timeout=180)
    for role, (mf, adir, rep) in pk.items():
        g = got[role]["manifest"]; validate("ModelPackageManifest", g); assert g["content_hash"] == mf["content_hash"]
        got_rep = json.loads(got[role]["report"]); validate("EvaluationReport", got_rep); assert got_rep["content_hash"] == rep["content_hash"] == canonical.content_hash({k: v for k, v in got_rep.items()})
        assert got[role]["adapter_ok"], f"{role} 어댑터 해시가 매니페스트와 다르다"
    return refs

def _c1_registry_publish_code_with_read_token(pk):
    """읽기 토큰(release-gate)으로 게시하면 거부되는가: 거부 코드(없으면 None)."""
    it = _c1_pack({"LORA_A": pk["LORA_A"]})[0]
    return _c1_run("release-gate", f"A = {_c1_lit(it)}\nimport base64, pathlib, shutil, tempfile\nfrom boundary_contracts import BoundaryError\nfrom openit_link.clients import HttpModelRegistry\n"
        "rr = HttpModelRegistry('https://model-registry', tok('model-registry-read-release-gate'))\nroot = pathlib.Path(tempfile.mkdtemp())\ntry:\n"
        "    for rel, b in A['files'].items():\n        p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(base64.b64decode(b))\n"
        "    try: rr.publish(A['manifest'], root, A['report'].encode()); code = None\n    except BoundaryError as e: code = e.code\nfinally: shutil.rmtree(root, ignore_errors=True)\nout(code)\n", timeout=120)

@step('3', repos=('model-lab', 'model-runtime', 'survey-service', 'boundary-contracts') + _GW, deps=('1', '2'),
      why="step3 는 make_packages 에서 STATE['dataset'](step2)·['qs'](step1)를 읽는다")
def step3():
    title(3, "설정 하나로 학습·평가·패키징·게시가 돈다 (model-lab, I3) -- 시험 대역")
    if os.environ.get("E2E_GPU") == "1":
        raise AssertionError("경계 결함: E2E_GPU=1 경로(GPU 호스트의 model-lab 이 model-registry 에 게시)는 아직 열리지 않는다. 계약 길은 R1.5(OUT-FILE `<주소> model-registry` + 학습 서버에 둔 model-lab 영역 게이트웨이 출구 R1.8 + model-registry 가 쓰기 토큰 직접 대조)이고 공개 입구에는 기계 게시 경로가 없다(R3.23). 받는 쪽은 scripts/test-registry-publish-reach.sh 가 확인하지만, model-lab 의 Exposure.egress 에 model-registry 가 없어 출구가 403 으로 막는다(ADR 0071, docs/change-requests/CR-450-model-lab-egress-model-registry.md; 기본 경로는 영향 없음)")
    pk = make_packages(); refs = publish_packages(pk)
    assert _c1_registry_publish_code_with_read_token(pk) == "PERMISSION_DENIED", "읽기 토큰으로 게시됨"
    STATE["lora"] = refs; STATE["system_prompt"] = {r: pk[r][0]["system_prompt"]["sha256"] for r in pk}; save()

    src_desc = ("학습 서버에서 가져온 LoRA-A/B(model-runtime 설정 + 가져온 어댑터, 평가하지 않음)" if a.llm_package and pk["LORA_A"][0].get("ext", {}).get("deploy", {}).get("attached") else "학습하지 않은 중립 LoRA(model-runtime make_neutral_package.py + 학습 데이터 system 메시지 프롬프트, vllm 서빙 설정, lora_B=0이라 출력은 기반 모델과 같다)" if a.llm_package
                else "시험용 어댑터(test/fixtures/e2e-test-adapter, PEFT 형식 r=16, 기반 모델 Qwen/Qwen2.5-1.5B-Instruct; fake 백엔드는 기반 모델을 적재하지 않는다)")
    rec(3, "TEST-SUB", f"학습 대신 {src_desc}와 시험용 EvaluationReport(METRICS.md 이름의 고정 지표, 실제 평가 아님)를 model-registry에 HTTP로 게시. serving_config는 추론 서버 /v1/info의 serving_config_expectation으로 만들었다(survey 이미지 fake_serving_configs와 다른 키: {STATE.get('fake_cfg_vs_survey_image')}). 게시(REAL): 멱등, 읽기 토큰 게시 거부, 읽기로 매니페스트·어댑터 해시 검증 통과. 계보의 dataset은 단계 2가 게시한 실제 데이터셋(단계 2가 BLOCKED이면 자리표시 참조, TEST-SUB). 시스템 프롬프트는 어댑터 디렉터리의 system_prompt.txt와 ModelPackageManifest.system_prompt(path, sha256)로 패키지에 들어 있다(시험용 자리표시 문장). model-lab 파이프라인·패키징 코드는 실행하지 않음(이웃 코드를 가져오지 않는다)")


def decisions_for(gate_read, subj):   # gate_read 는 옛 인자(직접 클라이언트): 이제 판정은 survey-service 컨테이너 안에서 읽는다. 호출하는 뒤 단계의 시그니처를 유지한다
    return _c1_decisions(subj)

ADMIN = lambda: (_C1_APPROVER, None)   # 개별 계정(Keycloak 시험 사용자: test/gateway-oidc/accounts.test.conf 를 scripts/idp-test-users.sh 가 만든다, 시험 계정, D85 E절). (계정 ID, 암호): 암호는 접근 계층(e2e_sandbox)이 안다
OPERATOR = lambda: (_C1_OPERATOR, None)   # 역할 operator: /v1/activate, /v1/rollback
REVIEWER = lambda: ("reviewer-e2e", None)   # 실패 사례 검토 화면 계정(역할 reviewer)

def gw_raw(method, path, body=None, basic=None, headers=None):
    """게이트웨이(HTTPS)로 부른다. basic=(계정 ID, _) 이면 그 계정으로. (상태, 본문(JSON 또는 문자열), 머리글)."""
    return _c1_gw(method, path, account=(basic[0] if basic else None), body=body, headers=headers)

def reject_via_gateway(sid):
    """승인 화면이 하는 경로를 게이트웨이를 거쳐 한 번 탄다: 목록(AWAITING_APPROVAL) -> review-report(헤더 해시) -> POST approvals(그 해시)."""
    c, _, _ = gw_raw("GET", "/v1/submissions?status=AWAITING_APPROVAL"); assert c == 401, f"인증 없이 /v1/submissions 가 열려 있다 {c}"
    assert gw_text("/admin/")[0] == 302, "인증 없이 /admin/ 이 열려 있다(화면 경로는 로그인으로 302)"
    c, page, _ = gw_raw("GET", "/v1/submissions?status=AWAITING_APPROVAL", basic=ADMIN()); assert c == 200, (c, page)
    assert any(x.get("submission_id") == sid for x in page["items"]), "대기 목록에 제출이 없다"
    c, one, _ = gw_raw("GET", f"/v1/submissions/{sid}", basic=ADMIN()); assert c == 200, (c, one)
    c, rep, hd = gw_raw("GET", f"/v1/submissions/{sid}/review-report", basic=ADMIN()); assert c == 200, (c, rep)
    h = {k.lower(): v for k, v in hd.items()}
    rh = h.get("x-openit-report-hash"); assert rh and rh.startswith("sha256:"), f"X-Openit-Report-Hash 헤더가 게이트웨이를 통과하지 않았다: {hd}"
    assert "no-store" in h.get("cache-control", ""), f"Cache-Control: no-store 가 유지되지 않았다: {h.get('cache-control')}"
    # 계약 ApprovalRequest: 본문에 approver_id·pipeline_schema_version 이 없다(additionalProperties false). 행위자는 X-Openit-User 가 유일한 길이다(D88).
    # 클라이언트가 보낸(위조) X-Openit-User 는 gateway 가 인증 계정으로 덮어쓰고, 기록되는 승인자는 인증 계정이다.
    body = {"submission_id": sid, "decision": "REJECT", "approver_role": "release-approver", "reason": "시험: 게이트웨이 경유 반려", "report_hash": rh}
    validate("ApprovalRequest", body)
    # 스키마 위반 한 줄: 본문에 approver_id 를 실으면 계약 위반이라 400 이다(본문 값을 받아들이지도 조용히 무시하지도 않는다)
    c, bad_, _ = gw_raw("POST", "/v1/approvals", {**body, "approver_id": "body-claimed-id"}, basic=ADMIN(), headers={"X-Openit-User": "spoofed-user"}); assert c == 400, ("본문에 approver_id 를 실은 요청이 400이 아니다", c, bad_)
    c, ap_, _ = gw_raw("POST", "/v1/approvals", body, basic=ADMIN(), headers={"X-Openit-User": "spoofed-user"})
    assert c == 201, (c, ap_)
    ap_ = ap_.get("approval", ap_) if isinstance(ap_, dict) else ap_   # 응답은 {"approval": GateApproval, ...} 로 한 겹 싸여 있을 수 있다
    assert ap_["approver_id"] == ADMIN()[0], f"승인자 ID가 인증된 계정이 아니다(위조 머리글이 덮어써지지 않았다): {ap_['approver_id']}"
    # 열지 않을 경로
    for m, pth in (("POST", "/v1/activate"), ("POST", "/v1/rollback"), ("POST", "/v1/submissions"), ("GET", "/v1/releases"), ("GET", "/v1/decisions")):
        cc = gw_raw(m, pth, {} if m == "POST" else None, basic=ADMIN())[0]; assert cc in (404, 403), f"{m} {pth} 가 게이트웨이에서 열려 있다 {cc}"
    c2, body2, hd2 = gw_text("/admin/", ADMIN()); assert c2 == 200 and "app.js" in body2, (c2, body2[:100])
    assert gw_text("/admin/app.js", ADMIN())[0] == 200
    STATE["admin_gateway"] = {"approver": ap_["approver_id"], "report_hash": rh}; save()
    rec("4g", "REAL", f"승인 화면 경로를 게이트웨이 경유로 한 번 탔다: 인증 없이 /admin/·/v1/submissions 401, OIDC 로그인(시험 사용자 {ADMIN()[0]}) 뒤 목록(AWAITING_APPROVAL)·제출 조회·review-report(X-Openit-Report-Hash 헤더 통과, Cache-Control no-store 유지)·POST /v1/approvals(헤더 해시 사용) 201, 승인 기록의 approver_id가 인증 계정으로 찍힘(클라이언트가 보낸 X-Openit-User·본문 approver_id는 무시), /v1/activate·rollback·POST submissions·releases 는 게이트웨이에서 404. 화면 렌더링은 BLOCKED")
    rec("4x", "BLOCKED", "승인 화면(/admin/)의 브라우저 렌더링·조작은 E2E에서 볼 수 없다. /config.json 은 절대 경로라 /admin/ 아래에서는 kiosk-frontend로 가서 404가 된다(화면은 없는 것으로 처리하므로 영향 없음, admin-console CR-003 후보)")
    return ap_

@step('4', repos=('release-gate', 'question-authoring', 'survey-service', 'model-lab', 'boundary-contracts') + _GW, deps=('1', '3'),
      why="step4 는 STATE['lora'](step3)·['qs'],['qsu'](step1)를 읽고 'lora' 가 없으면 BLOCKED 한다(e2e_steps.py step4 앞부분)",
      also={'admin-console': '승인 화면이 쓰는 release-gate API 계약(브라우저 렌더링은 E2E에서 볼 수 없다: 4x BLOCKED)'})
def step4():
    title(4, "후보 수집기가 새 조합을 찾아 자동 검사하고, 사람 승인으로 릴리스·번들을 만든다 (release-gate, D53)")
    if "lora" not in STATE: rec(4, "BLOCKED", "단계 3의 패키지가 없다"); return
    print("  !! 승인자는 사람이 아니라 이 스크립트가 시험용 승인자 계정(게이트웨이)으로 대신한다(TEST-SUB). 시험용 정책·실행기는 없다 !!")
    rc, collected_out = _c1_job("job-release-gate-collect")
    assert rc in (0, 75), f"collect 종료 {rc}: {collected_out[-500:]}"
    collected = collected_out.strip().splitlines()[-1] if collected_out.strip() else ""
    A, B = STATE["lora"]["LORA_A"], STATE["lora"]["LORA_B"]
    subj = {v["version"]: _subj(v, A, B) for v in STATE["qs"]}
    subj_u = _subj_u(A, B)
    # 접수: 운영에서는 수집기 잡이 한다(위 job). 같은 조합 접수가 멱등인지는 게이트 컨테이너 안에서 접수 면(operator 쓰기 토큰)을 두 번 불러 본다 -- 게이트웨이는 POST /v1/submissions 를 열지 않는다(수집기 전용)
    allsubj = {**subj, "u": subj_u}
    got = _c1_run("release-gate", f"A = {_c1_lit(allsubj)}\nfrom openit_link.clients import HttpGateService\n"
        "gs = HttpGateService('@SELF@', tok('gate-write-tokens', 'operator'), user='op-test')\nres = {}\n"
        "for k, sj in A.items():\n    s1 = dict(gs.submit_candidate(sj, requested_by_role='operator')); s2 = dict(gs.submit_candidate(sj, requested_by_role='operator'))\n"
        "    res[k] = [s1, s2]\nout(res)\n")
    subs = {k: got[k][0] for k in subj}; sub_u = got["u"][0]
    for x in list(subs.values()) + [sub_u]: validate("GateSubmission", x)
    assert all(v[0]["submission_id"] == v[1]["submission_id"] for v in got.values()), "같은 조합이 같은 접수가 아니다"
    # 승인자 화면과 같은 경로(게이트웨이, 승인자 계정)에서도 그 접수가 보인다
    c, pg, _ = _c1_gw("GET", "/v1/submissions?limit=100", account=_C1_APPROVER); assert c == 200 and isinstance(pg, dict), (c, str(pg)[:100])
    seen = {x.get("submission_id") for x in pg.get("items", [])}
    assert {x["submission_id"] for x in list(subs.values()) + [sub_u]} <= seen, ("승인자 목록에 접수가 없다", sorted(seen)[:5])
    STATE["subs"] = {"by_version": subs, "unseen": sub_u}; save()
    rec("4a", "REAL", f"수집기 run-once(컨테이너): {collected[:100]}; 후보 접수 3건(GateSubmission 스키마 통과, 같은 조합은 같은 접수, 승인자 계정 목록에서 보임)")
    reps = {}
    for k, sub in list(subs.items()) + [("u", sub_u)]:
        reps[k] = _c1_wait_report(sub["submission_id"], k)
        validate("ReviewReport", reps[k])
    assert all(c["result"] in ("PASS", "SKIPPED") for c in reps["1"]["checks"]), reps["1"]["checks"]
    # 승인 전에는 PASS가 없다
    for k, sj in list(subj.items()) + [("u", subj_u)]:
        assert not any(d["result"] == "PASS" for d in _c1_decisions(sj)), f"승인 전에 PASS 판정이 있다 {k}"
    rc_, rd = SB.readyz("release-gate"); assert rc_ == 200 and rd.get("awaiting_approval", 0) >= 3, (rc_, rd)
    # 권한: 승인은 release-approver만 -- 게이트웨이는 operator 계정을 403 으로 막고, 게이트 자신도 operator 쓰기 토큰의 승인을 거부한다
    sid_ = subs["1"]["submission_id"]
    c, b, _ = _c1_gw("POST", "/v1/approvals", account=_C1_OPERATOR, body={"submission_id": sid_, "decision": "APPROVE", "approver_role": "release-approver", "reason": "시험", "report_hash": _c1_report_hash(sid_)})
    assert c == 403, ("operator 계정이 게이트웨이로 승인함", c, str(b)[:100])
    try: decide_approval("op", sid_, "APPROVE", reason="시험"); raise AssertionError("operator가 승인함")
    except bc.BoundaryError as e: assert e.code == "PERMISSION_DENIED", e.code
    try: decide_approval("ap", sid_, "APPROVE", reason="시험", report_hash="sha256:" + "0" * 64); raise AssertionError("낡은 보고서 해시로 승인됨")
    except bc.BoundaryError as e: assert e.code == "CONFLICT", e.code
    # 반려(REJECT) -> FAIL 판정
    ru = reject_via_gateway(sub_u["submission_id"]); validate("GateApproval", ru)
    du = wait(lambda: next(iter(_c1_decisions(subj_u)), None), 30, "반려 판정"); validate("GateDecision", dict(du))
    hu = [c for c in du["checks"] if c["kind"] == "HUMAN_APPROVAL"]
    assert du["result"] == "REJECT" and hu and hu[0]["result"] == "FAIL" and "CHECK_FAILED" in du["reject_codes"], dict(du)
    # 승인(APPROVE) 멱등, 다른 결정 충돌
    sid1 = subs["1"]["submission_id"]
    a1 = dict(decide_approval("ap", sid1, "APPROVE", reason="시험: 지표 검토함")); validate("GateApproval", a1)
    a1b = dict(decide_approval("ap", sid1, "APPROVE", reason="시험: 지표 검토함"))
    assert a1b == a1, "같은 결정 재전송이 같은 결과가 아니다"
    try: decide_approval("ap", sid1, "REJECT", reason="번복"); raise AssertionError("다른 결정이 받아들여짐")
    except bc.BoundaryError as e: assert e.code == "CONFLICT", e.code
    d1 = wait(lambda: next((d for d in _c1_decisions(subj["1"]) if d["result"] == "PASS"), None), 30, "승인 뒤 PASS 판정")
    validate("GateDecision", dict(d1)); assert any(c["kind"] == "HUMAN_APPROVAL" and c["result"] == "PASS" for c in d1["checks"])
    rid1 = d1.get("release_id"); rel1 = _c1_release(rid1); validate("ReleaseManifest", rel1); assert canonical.content_hash(rel1) == rel1["content_hash"]   # 번들(해시 검증 포함)도 같은 호출에서 받았다
    c401, b401, _ = _c1_in("release-gate", "POST", "/v1/activate", auth=("gate-write-tokens", "operator"), body={"requested_by_role": "operator", "release_id": rid1})   # 게이트웨이는 항상 행위자 머리글을 붙이므로 머리글 없는 호출은 게이트 컨테이너 안에서만 만들 수 있다
    assert c401 == 401, f"헤더 없이 operator 토큰으로 activate 하면 401이어야 한다: {c401} {str(b401)[:100]}"
    assert dict(_c1_pointer() or {}).get("release_id") != rid1, "401인데 활성 포인터가 바뀌었다"
    c_, ap1 = _c1_activate(rid1); assert c_ == 200, f"activate {rid1} 실패 {c_}: {str(ap1)[:200]}"; ap1 = dict(ap1); validate("ActivePointer", ap1)
    cur = dict(_c1_pointer()); assert cur["ext"]["release-gate"]["requested_by"] == _C1_OPERATOR, f"활성 포인터 조회의 requested_by 가 게이트웨이가 붙인 계정 ID가 아니다: {cur.get('ext')}"
    # 둘째 후보: 활성 릴리스와 같은 지표끼리 맞댄 보고서(comparisons), 활성화로 보고서가 바뀌면 이전 해시는 낡은 것
    sid2 = subs["2"]["submission_id"]
    c, rep2, _ = _c1_gw("GET", f"/v1/submissions/{sid2}/review-report", account=_C1_APPROVER); assert c == 200, (c, str(rep2)[:100]); validate("ReviewReport", rep2)
    assert rep2["comparisons"], "활성 릴리스와의 비교가 비어 있다"
    a2 = dict(decide_approval("ap", sid2, "APPROVE", reason="시험: 둘째 후보 검토함")); validate("GateApproval", a2)
    d2 = wait(lambda: next((d for d in _c1_decisions(subj["2"]) if d["result"] == "PASS"), None), 30, "둘째 PASS 판정"); validate("GateDecision", dict(d2))
    rid2 = d2.get("release_id"); rel2 = _c1_release(rid2); validate("ReleaseManifest", rel2)
    for rel_, qv_ in ((rel1, STATE["qs"][0]), (rel2, STATE["qs"][-1])):   # 3.3.0: 릴리스는 제출한 문진표 목록 그대로(ID·버전·제목) 담는다
        assert sorted((x["id"], str(x["version"])) for x in rel_["question_sets"]) == sorted([(QS, str(qv_["version"])), (QSB, str(STATE["qsb"]["version"]))]), ("릴리스의 문진표", rel_["question_sets"])
        assert {x["id"]: x["title"] for x in rel_["question_sets"]} == {QS: QS_TITLE, QSB: QSB_TITLE}, rel_["question_sets"]
    STATE["containers_before_swap"] = container_ids(); save()   # 포인터 1 -> 2 활성화 직전(StartedAt, ID 만 읽는다)
    c_, ap2 = _c1_activate(rid2); assert c_ == 200, f"activate {rid2} 실패 {c_}: {str(ap2)[:200]}"; ap2 = dict(ap2); validate("ActivePointer", ap2); assert ap2["pointer_version"] > ap1["pointer_version"]
    cx, bx = _c1_activate(du.get("release_id") or "rel-none-x"); assert cx != 200 and isinstance(bx, dict) and bx.get("code") in ("NOT_FOUND", "FAILED_PRECONDITION"), ("PASS가 아닌 릴리스가 활성화됨", cx, str(bx)[:100])
    STATE["releases"] = {"1": rid1, "2": rid2}; STATE["pointers"] = [ap1, ap2]; save()
    rec("4b", "TEST-SUB", f"승인자를 스크립트가 대신한다(TEST-SUB). REAL: 자동 검사 통과 후 승인 요청 보고서(ReviewReport, 활성 릴리스와 비교), 승인 전 PASS 없음, operator의 승인 403(게이트웨이 계정·게이트 쓰기 토큰 둘 다), 낡은 report_hash 409, REJECT -> REJECT 판정(HUMAN_APPROVAL FAIL, CHECK_FAILED), APPROVE 재전송 멱등·번복 409, 승인 뒤 PASS(HUMAN_APPROVAL PASS)·ReleaseManifest(해시)·번들(해시)·활성화 x2(포인터 {ap1['pointer_version']}->{ap2['pointer_version']})")
def survey_ready():
    return SB.readyz("survey-service")   # (상태, /readyz JSON)

def kiosk(path, body):
    # 키오스크 기기처럼 TLS 클라이언트 인증서(기기 e2e)로 공개 입구를 부른다: 입구가 인증서 CN·일련번호를 허용 목록과 대조한다(계약 PUBLIC_API F절, D136)
    c, b, _ = _c1_gw("POST", path, token=KDEV(), body=body); return c, b

def _assert_denied(what, c, b):
    """기기 인증서 없음·허용 목록 밖의 기대: 403 + BoundaryError(code PERMISSION_DENIED)(계약 PUBLIC_API F절). 401 은 아니다: TLS 인증서는 HTTP 인증 challenge 로 다시 낼 수 없는 자격이다."""
    assert c == 403 and isinstance(b, dict) and b.get("code") == "PERMISSION_DENIED", (f"{what}: 403 PERMISSION_DENIED 여야 한다", c, str(b)[:120])
    validate("BoundaryError", b)

def _sid(c, st):
    """세션 시작 응답에서 서버가 발급한 session_id 를 읽는다(계약 4.0.0 SessionStartBody: 요청에 session_id 가 없다). 이후 턴·종료·상태·개입·직원 호출은 이 값을 쓴다."""
    assert c == 200 and isinstance(st, dict) and st.get("session_id"), ("세션 시작", c, str(st)[:150])
    return st["session_id"]

KDEV = lambda: SB.DeviceId("e2e")   # 시험 기기 e2e 의 인증서(secrets/device-certs/e2e.crt·.key, scripts/gen-secrets.sh --test-fixtures)
STAFF = lambda: ("staff-e2e", None)   # 직원 콘솔 계정(개발/E2E용, 역할 staff)
def state_of(sid):
    """GET /v1/sessions/{id}/state. 서버가 0.5초보다 잦은 조회를 429(UNAVAILABLE)로 막으므로 간격을 두고 재시도한다(키오스크는 2초 간격 폴링)."""
    for _ in range(8):
        time.sleep(0.7)
        c, r, _h = _c1_gw("GET", f"/v1/sessions/{sid}/state", token=KDEV())
        if c != 429: return c, r
    return c, r

def gws(method, path, body=None):
    c, b, _ = _c1_gw(method, path, account=STAFF()[0], body=body); return c, b

def gw_text(path, basic=None):
    c, b, h = _c1_gw("GET", path, account=(basic[0] if basic else None), timeout=20.0)
    return c, (b if isinstance(b, str) else json.dumps(b, ensure_ascii=False) if b is not None else ""), h

def public_turn(sid, tid, text):
    c, r = kiosk(f"/v1/sessions/{sid}/turns", {"session_id": sid, "kind": "UTTERANCE", "utterance": text, "turn_id": tid}); return c, r

def ms_call(path, body, token, method="POST"):
    """추론 서버 직접 호출(v2): (상태, 본문 문자열, 소문자 헤더). (c) 다른 호스트 역할의 추론 서버를 inference_url() 로. 서비스를 거치지 않고 extract(JSON)·respond(text)의 계약을 확인하려는 것. token 이 없으면 Authorization 을 붙이지 않는다."""
    base = a.ms_url.rstrip("/") if a.ms_url else SB.inference_url()   # 외부 주소(--ms-url) > 다른 호스트 역할 프로젝트 > 없으면 제품 안 model-serving 컨테이너에서(데모처럼 추론 서버가 제품 안에 있을 때; 호스트 포트는 없다, D123)
    if base is None: return _c2_in("model-serving", method, path, token, body)
    req = urllib.request.Request(base + path, data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None, method=method)
    if token: req.add_header("Authorization", f"Bearer {token}")
    if body is not None: req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, r.read().decode(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e: return e.code, e.read().decode(errors="replace"), {k.lower(): v for k, v in e.headers.items()}

FAKE_EXTRACTION = {"action": "NEXT", "next_item": "Q1.D04", "values": [{"key": "Q1.D03.diagnosed", "precision": "exact", "save": True, "status": "ANSWERED", "value": True}]}
FAKE_RESPONSE_TEXT = "(가짜 응답)"

def ereq_of(ein):
    """I9 요청 본문 ExtractRequest{input, flow, fields}(계약 3.0, flow·fields 필수). 가짜 백엔드의 흐름 파일(test/fake-model/question_flow.json)에서 문항 순서표(order·skips)와 칸 규격(slots -> QuestionFieldSpec)을 만든다.
    칸 규격은 이 시험 구성이 정한 값이다(범위는 두지 않는다: 값 규칙 시험은 5o 가 자기 fields 로 한다)."""
    ff = json.loads((pathlib.Path(__file__).resolve().parents[1] / "test" / "fake-model" / "question_flow.json").read_text(encoding="utf-8"))
    fields = {"fields": [{"slot": sl["key"], "data_type": sl["type"]} for v in ff["slots"].values() for sl in v]}
    req = {"input": ein, "flow": {"order": ff["order"], "skips": ff["skips"]}, "fields": fields}
    validate("ExtractRequest", req); return req

def model_server_v2_check(new, tok):
    """PUT 적재(서비스가 이미 함) 뒤 extract(JSON) -> respond(text) 를 직접 한 번씩 부른다."""
    ein = {"question_id": "Q1.D03", "current_question": "다음은 고혈압입니다. 진단받은 적이 있으신지, 지금 약을 드시는지 알려 주세요.", "user_utterance": "십 년 전에 고혈압 진단을 받았어요.",
           "state": {"Q1.D02.diagnosed": {"value": False, "status": "ANSWERED"}}}
    validate("ActionExtractionInput", ein)
    # 3.0: 옛 본문(ActionExtractionInput 그대로)과 fields 없는 요청은 400 INVALID_RECORD 다. 정상 호출은 ExtractRequest{input, flow, fields}뿐이다
    c, old, _ = ms_call(f"/v1/releases/{new}/extract", ein, tok); assert c == 400, ("옛 본문(ActionExtractionInput)이 400이 아니다", c, old[:100])
    ereq = ereq_of(ein)
    c, body, h = ms_call(f"/v1/releases/{new}/extract", ereq, tok); assert c == 200, (c, body[:200])
    out = json.loads(body); validate("ActionExtraction", out); assert out == FAKE_EXTRACTION, out
    assert h.get("content-type", "").startswith("application/json") and h.get("x-openit-outcome") == "ok", h
    rin = {"action": "START", "topic": "고혈압 진단과 복약", "next": {"type": "NEXT", "question_id": "Q1.D01", "text": "혹시 고혈압으로 진단받으셨나요?"}}
    validate("ResponseRequest", rin)
    c, body, h = ms_call(f"/v1/releases/{new}/respond", rin, tok); assert c == 200, (c, body[:200])
    assert body == FAKE_RESPONSE_TEXT and h.get("content-type", "").startswith("text/plain") and h.get("x-openit-outcome") == "ok", (body[:80], h)
    # I9 ExtractRequest{input, flow, fields}(계약 3.0, D108·D115): flow·fields 가 항상 있으니 서버가 규칙과 값 규칙을 보증한다. 불완전한 본문(fields 없음, skips 없는 flow)은 400이다.
    c, bad1, _ = ms_call(f"/v1/releases/{new}/extract", {"input": ein, "flow": ereq["flow"]}, tok); assert c == 400, ("fields 없는 요청이 400이 아니다", c, bad1[:100])
    c, bad2, _ = ms_call(f"/v1/releases/{new}/extract", {"input": ein, "flow": {"order": ereq["flow"]["order"]}, "fields": ereq["fields"]}, tok); assert c == 400, ("skips 없는 flow 가 400이 아니다", c, bad2[:100])
    c, bad, _ = ms_call(f"/v1/releases/{new}/extract", {"question_id": "Q1"}, tok); assert c == 400, ("계약 위반 입력이 400이 아니다", c, bad[:100])
    c, nf, _ = ms_call("/v1/releases/rel-none-x/extract", ereq, tok); assert c == 404  # 본문은 유효한 ExtractRequest: link 가 본문 검증(400)을 처리 함수보다 먼저 하므로 틀린 본문이면 404 를 시험하지 못한다, ("적재되지 않은 릴리스가 404가 아니다", c)
    c, info_body, _ = ms_call("/v1/info", None, tok, method="GET"); info = json.loads(info_body)
    assert info.get("system_prompt_sha256") == STATE.get("system_prompt"), f"서버가 쓰는 시스템 프롬프트 해시가 패키지와 다르다: {info.get('system_prompt_sha256')} / {STATE.get('system_prompt')}"
    return "extract(ExtractRequest{input, flow, fields} 200·JSON ActionExtraction 스키마·X-Openit-Outcome ok; 옛 본문·fields 없음·skips 없는 flow 는 400) -> respond(text/plain 문장, ok), 계약 위반 입력 400, 미적재 릴리스 404, /v1/info 의 system_prompt_sha256 이 패키지(ModelPackageManifest.system_prompt)와 일치"

SWAP_SERVICES = ["survey-service", "release-gate", "model-registry", "ops-feedback", "question-authoring", "gateway"]
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
        c, body, h = ms_call(f"/v1/releases/{new}/extract", ereq_of(ein), tok); assert c == 200, (qid, c, body[:200])
        out = json.loads(body); validate("ActionExtraction", out)
        EA.check_fake_extraction(out, key, val, nxt, f"[{qid} '{utt}']")
    return f"{len(cases)}건(Q4 아니요 -> Q4.answer=false·Q4_1 건너뜀, Q7 -> Q8_1, Q8_1 없어요 -> days=0·Q8_2 건너뜀 등)"

@step('5', repos=('survey-service', 'model-runtime', 'kiosk-frontend') + _GW, deps=('3', '4'),
      why="step5 는 STATE['pointers'],['releases'](step4)·['system_prompt'](step3)를 읽는다. " + _P4,
      also={'release-gate': '활성화된 릴리스 번들을 survey-service와 model-serving이 읽는다(I4)'})
def step5():
    title(5, "서비스가 새 포인터를 보고 새 세션부터 새 릴리스로 한 턴 이상을 처리한다 (공개 API, 게이트웨이 경유)")
    if "pointers" not in STATE: rec(5, "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    new = STATE["releases"]["2"]
    r = wait(lambda: (lambda cr: cr[1] if cr[0] == 200 and cr[1].get("active_release") == new else None)(survey_ready()), 60, f"survey가 릴리스 {new} 적재")
    assert r["ready"] and not r["release_loader"]["rejections"], r
    sid = f"sess-{RID}-a"
    assert _c1_in("survey-service", "POST", "/v1/sessions", body={"kind": "SESSION_START", "question_set_id": QS})[0] == 401, "survey-service가 토큰 없는 요청을 받아들임"   # 서비스 자신의 인증(게이트웨이 뒤가 아니라 서비스 컨테이너 안)
    c, st = kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}); sid = _sid(c, st)
    validate_survey("FrontendInput", st); assert st["response_text"], st
    c, t1 = public_turn(sid, "turn-1", "뇌졸중은 없고 약도 안 먹어요"); assert c == 200, (c, t1); validate_survey("FrontendInput", t1)
    c, t1b = public_turn(sid, "turn-1", "뇌졸중은 없고 약도 안 먹어요"); assert c == 200 and t1b == t1, "같은 turn_id 재시도가 같은 응답이 아니다"
    c, t2 = public_turn(sid, "turn-2", "약도 안 먹어요"); assert c == 200, (c, t2)
    # 한 턴이 추론 서버(model-serving)를 거쳤다: 서버의 가짜 백엔드는 출력이 고정이라 생성기 문장이 "(가짜 응답)" 이다
    texts = " ".join(str(x.get("response_text")) for x in (t1, t2))
    assert "(가짜 응답)" in texts, f"model-serving의 고정 출력이 아니다(서비스 내부 가짜?): {texts[:200]}"
    ms_tok = INF_TOK()
    c, info_body, _ = ms_call("/v1/info", None, ms_tok, method="GET"); info = json.loads(info_body) if c == 200 else {}
    assert c == 200 and new in info.get("loaded", []), (c, info)
    assert info["backend"] == "fake", info
    c401, _b401, h401 = ms_call("/v1/info", None, None, method="GET")
    assert c401 == 401 and (h401.get("www-authenticate") or "").split(" ")[0].rstrip(",") == "Bearer", ("토큰 없는 추론 서버 /v1/info: 401 + WWW-Authenticate: Bearer (계약 CONVENTIONS.md 6절)", c401, h401.get("www-authenticate"))
    c2, stxt, _ = ms_call(f"/v1/releases/{new}", None, ms_tok, method="GET"); st_ = json.loads(stxt) if c2 == 200 else {}; assert c2 == 200 and st_["state"] == "LOADED", (c2, stxt[:100])
    v2chk = model_server_v2_check(new, ms_tok)
    fvc = fake_values_check(new, ms_tok)
    # 서비스를 거친 값 있는 턴: 가짜 A 가 매 턴 값(ANSWERED)을 내고, 서비스의 검증·저장을 통과해야 한다(실패 신호 없음, 추론 실패·형식 위반 증가 없음, Trace 전송)
    sv = _sid(*kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}))
    rb = survey_ready()[1]; replies = []
    for i, text in enumerate(("네 있어요", "아니요 없어요", "네 있어요"), 1):
        c, rp = public_turn(sv, f"val-{i}", text); assert c == 200, (c, rp); validate_survey("FrontendInput", rp); replies.append(rp)
    wait(lambda: survey_ready()[1]["trace_outbox"]["sent"] - rb["trace_outbox"]["sent"] >= len(replies) or None, 30, "값 있는 턴의 Trace 전송")
    EA.check_turns_clean(replies, rb, survey_ready()[1])
    kiosk(f"/v1/sessions/{sv}/end", {"session_id": sv, "kind": "SESSION_END"})
    rec("5g", "REAL", f"가짜 A 의 값 추출(흐름 파일 slots/skips): 직접 호출 {fvc}. 서비스 경유 값 있는 3턴(Q1.D01~: '네 있어요','아니요 없어요','네 있어요'): 실패 신호 없음(검증 통과·쓰기 확정), /readyz inference 의 failures·output_invalid·retries·timeouts·outcome_fallback 증가 0, 턴마다 Trace 전송. 모델은 가짜(정확성 아님, 시험 구성 확인). 한계: 저장된 값을 돌려주는 공개 읽기 경로가 없고(PUBLIC_API 에 없음) ops-feedback 은 실패 사례만 노출하므로 저장 값 자체는 단언하지 않았다. 가짜 A 는 CORRECT 를 내지 않아 정정은 시험하지 않았다")
    rd = survey_ready()[1]; inf = rd.get("inference") or {}
    if not a.skip_ms_restart:
        # 추론 서버가 응답하지 않는다: 그 턴만 실패하고 서비스는 산다, 되살리면 다음 턴이 복구된다.
        # 왜 stop/start 가 아니라 pause/unpause 인가: 추론 서버는 별도 프로젝트(다른 호스트 역할)이고 호스트 포트를 Docker 가 배정한다. 다시 띄우면 포트가 바뀌어 제품(survey-service)의 추론 서버 주소가
        # 어긋나 이후 모든 단계가 깨진다(운영의 추론 서버는 고정 주소). 그래서 연결 거부(stop) 경로는 이 구성에서 시험하지 못하고 무응답(pause) 경로만 본다. 연결 거부는 5m 이전 시험이 보던 경로였다.
        mname = MS_CONTAINER
        sidc = _sid(*kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}))
        sh([a.docker, "pause", mname])
        try:
            cd_, rd_ = public_turn(sidc, "turn-down", "뇌졸중은 없고 약도 안 먹어요")
            failed = cd_ != 200 or (isinstance(rd_, dict) and rd_.get("turn_failure_signal"))
            assert failed, f"추론 서버가 응답하지 않는데 턴이 성공했다: {cd_} {rd_}"
            assert _c1_in("survey-service", "GET", "/healthz")[0] == 200, "추론 서버 무응답으로 서비스가 죽었다"
        finally:
            sh([a.docker, "unpause", mname])
        # 같은 세션에서 연속 실패가 쌓이면 서비스가 직원 호출로 세션을 멈추므로(응답 문장 없음) 새 세션·새 turn_id 로 첫 턴을 보내 제한 시간 안에 성공하는지 본다. 걸린 시도 수는 단계 출력에 남긴다
        tries_up = []
        def recovered():
            c_u, st_u = kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS})
            if c_u != 200: tries_up.append(None); return None
            sid_u = _sid(c_u, st_u)
            cu_, ru_ = public_turn(sid_u, "turn-up", "뇌졸중은 없고 약도 안 먹어요"); tries_up.append((cu_, ru_))
            kiosk(f"/v1/sessions/{sid_u}/end", {"session_id": sid_u, "kind": "SESSION_END"})
            return (cu_, ru_) if cu_ == 200 and not (isinstance(ru_, dict) and ru_.get("turn_failure_signal")) else None
        cu, ru = wait(recovered, 60, "추론 서버가 되살아난 뒤 서비스가 복구해 턴이 성공한다", every=3)
        assert "(가짜 응답)" in str(ru.get("response_text")), (cu, ru)
        print(f"  추론 서버 무응답 뒤 복구: {len(tries_up)}번째 시도에서 성공(앞선 {len(tries_up) - 1}번은 실패)", flush=True)
        kiosk(f"/v1/sessions/{sidc}/end", {"session_id": sidc, "kind": "SESSION_END"})
    assert kiosk(f"/v1/sessions/{sid}/intervention", {"session_id": sid, "decision": "RESUME", "turn_id": "x"})[0] == 401, "직원 개입이 인증 없이 열려 있다"
    # F절(D136): 기기 인증서 없이 키오스크 경로를 부르면 403 PERMISSION_DENIED(BoundaryError 본문). Bearer 는 기기 자격이 아니다(토큰이 있어도 인증서가 없으면 같다)
    for lab, tk in (("인증서 없음", None), ("틀린 Bearer", "0" * 48), ("서비스 kiosk 토큰", _c1_tok("survey-api-kiosk"))):
        c_nd, b_nd, _h = _c1_gw("POST", "/v1/sessions", token=tk, body={"kind": "SESSION_START", "question_set_id": QS})
        _assert_denied(f"기기 인증서 없이 키오스크 API({lab})", c_nd, b_nd)
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
    # 직원 개입은 서비스 컨테이너 안(내부 경로)에서만: 키오스크 토큰은 403, 직원 토큰은 멈추지 않은 세션에 409(PUBLIC_API.md)
    ib = {"session_id": sid, "decision": "RESUME", "turn_id": "i1"}
    assert _c1_in("survey-service", "POST", f"/v1/sessions/{sid}/intervention", auth=("survey-api-kiosk", None), body=ib)[0] == 403, "키오스크 토큰으로 직원 개입이 열림"
    # D85: 서비스는 개입의 행위자를 게이트웨이가 붙인 X-Openit-User 로 정한다(없으면 401). 게이트웨이를 거치지 않는 서비스 컨테이너 안 호출에는 헤더를 직접 붙인다
    def survey_intervene(user):
        c_, b_, _ = _c1_in("survey-service", "POST", f"/v1/sessions/{sid}/intervention", auth=("survey-api-staff", None), headers=({"X-Openit-User": user} if user is not None else None), body=ib)
        return c_, str(b_)[:200]
    c0, b0 = survey_intervene(None); assert c0 == 401, f"헤더 없는 직원 개입이 401이 아님: {c0} {b0}"
    c1, b1 = survey_intervene(STAFF()[0]); assert c1 == 409, f"멈추지 않은 세션의 개입이 409가 아님: {c1} {b1}"
    assert _c1_gw("GET", f"/v1/sessions/{sid}/turns", token=KDEV())[0] in (404, 405)
    c, en = kiosk(f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"}); assert c == 200, (c, en); validate_survey("FrontendInput", en)
    # 서비스가 턴마다 Trace를 I6로 보냈는지(outbox 전송 수)
    sent = wait(lambda: (lambda cr: cr[1]["trace_outbox"]["sent"] if cr[1]["trace_outbox"]["sent"] >= 2 else None)(survey_ready()), 30, "Trace 전송")
    STATE["sess_a"] = sid; save()
    rec(5, "REAL", f"게이트웨이 경유 공개 API(Bearer 토큰, 없으면 401): 세션 시작·발화 2턴·종료, 응답 FrontendInput 스키마 통과, 같은 turn_id 재시도는 같은 응답, 게이트웨이는 토큰 없이 부른 키오스크 요청에 kiosk 토큰을 붙이고(survey 직접 호출은 토큰 없으면 401), 직원 개입은 인증 없으면 401, survey에서 키오스크 토큰은 403·직원 토큰은 멈추지 않은 세션에 409. 실제 survey-service가 게이트 포인터를 HTTP로 폴링해 릴리스 {new} 적재(번들 해시 검증)하고 턴마다 Trace를 I6로 전송(outbox sent={sent}). 한 턴이 model-serving 컨테이너(I9 v2: 서비스 -> PUT 적재 -> extract(JSON) -> respond(text))를 거쳤다(고정 출력 '(가짜 응답)' 확인, /v1/info loaded, 토큰 없으면 거부). 서버 직접 호출: {v2chk}. 추론 서버가 응답하지 않으면(pause) 그 턴만 실패하고 서비스는 살아 있으며 되살리면 다음 턴이 복구된다. 모델은 fake 백엔드와 시험용 번들(TEST-SUB)")

# ---- 접근 계층(wo-443, docs/adr/0048-e2e-sandbox.md): 아래 5c~5f 단계는 제품에 SB(scripts/e2e_sandbox.py)로만 닿는다. 내부 서비스의 호스트 포트는 없다.
# (a) 게이트웨이(HTTPS): 사람 역할은 계정, 키오스크는 기기 토큰. (b) 제품 컨테이너 안(_c2_in): 운영에서 그 일을 하는 주체(위험 신호 감지기, 병원 결과 조회, 이웃 읽기)가 제품 네트워크 안에 있는 호출.
# (c) 추론 서버는 다른 호스트 역할이라 SB.inference_url(). 왜 따로 _c2_ 도우미를 두나: 다른 범위의 옛 도우미(URL/http/gws/kiosk)는 내부 포트를 전제로 했고, 이 범위가 그 모양에 기대지 않게 한다.
_C2_ADMIN, _C2_OPERATOR, _C2_REVIEWER = "trainer-e2e", "operator-e2e", "reviewer-e2e"   # 계정 ID(비밀 폴더 tokens/account-<ID>-password, gen-secrets.sh 의 시험 계정)
_C2_STAFF, _C2_AUTHOR, _C2_CLINICAL, _C2_CLINICIAN = "staff-e2e", "author-e2e", "clinical-e2e", "clinician-e2e"   # clinician: 문진 결과를 보는 의사(U83)

def _c2_dec(raw):
    if isinstance(raw, str): raw = raw.encode()
    try: return json.loads(raw or b"null")
    except ValueError: return raw.decode(errors="replace")

def _c2_gw(method, path, body=None, *, account=None, token=None, raw=None, ctype=None, headers=None, timeout=70):   # 70 = 키오스크 대기 60s + 여유(D125): 무응답 상류에서 gateway 504 를 받을 때까지 기다린다
    """게이트웨이 한 요청 -> (상태, 본문(JSON 이면 파싱, 아니면 문자열), 소문자 헤더). 4xx/5xx 도 돌려준다."""
    h = dict(headers or {})
    if ctype: h["Content-Type"] = ctype
    s, hd, b = SB.gw_request(method, path, account=account, token=token, json=body, data=raw, headers=h or None, timeout=timeout)
    return s, _c2_dec(b), hd

def _c2_raw(method, path, body=None, basic=None, headers=None):
    """사람 계정(basic=계정 ID 문자열) 또는 헤더로 직접 만든 자격으로 게이트웨이를 부른다. basic 이 튜플이면 쓸 수 없다(Basic 인증이 없어졌다, U82: 위조 자격 시험은 Cookie 머리글로)."""
    h = dict(headers or {})
    if isinstance(basic, tuple): raise RuntimeError("튜플 자격(Basic)은 없어졌다(U82): 사람 계정은 계정 ID 문자열, 위조 자격은 headers={'Cookie': …}")
    return _c2_gw(method, path, body, account=basic, headers=h, timeout=200)   # 200 = release-gate 상한 181s(연결 1s + 헤더 180s) + 여유(D125)

def _c2_text(path, basic=None):
    c, b, h = _c2_raw("GET", path, basic=basic)
    return c, (b if isinstance(b, str) else json.dumps(b, ensure_ascii=False)), h

def _c2_kiosk(path, body, method="POST"):
    c, b, _h = _c2_gw(method, path, body, token=_c2_kdev()); return c, b
def _c2_kdev(): return SB.DeviceId("e2e")   # 시험 기기 e2e 의 클라이언트 인증서(mTLS)
def _c2_turn(sid, tid, text): return _c2_kiosk(f"/v1/sessions/{sid}/turns", {"session_id": sid, "kind": "UTTERANCE", "utterance": text, "turn_id": tid})
def _c2_staff(method, path, body=None):
    c, b, _h = _c2_gw(method, path, body, account=_C2_STAFF); return c, b
def _c2_state(sid):
    """GET /v1/sessions/{id}/state. 서버가 0.5초보다 잦은 조회를 429(UNAVAILABLE)로 막으므로 간격을 두고 재시도한다(키오스크는 2초 간격 폴링)."""
    for _ in range(8):
        time.sleep(0.7)
        c, r = _c2_kiosk(f"/v1/sessions/{sid}/state", None, "GET")
        if c != 429: return c, r
    return c, r
def _c2_ready(): return SB.readyz("survey-service")   # 상태 관찰: 컨테이너 안 /readyz (게이트웨이의 /readyz 는 요약뿐이라 세부 필드를 못 준다)

_C2_IN_PY = ("import json,urllib.request,urllib.error\nP=json.loads(@@P@@)\n"
             "d=json.dumps(P['b']).encode() if P['b'] is not None else None\n"
             "r=urllib.request.Request('@SELF@'+P['path'],data=d,method=P['m'])\n"
             "if P['t']: r.add_header('Authorization','Bearer '+P['t'])\n"
             "if d is not None: r.add_header('Content-Type','application/json')\n"
             "try:\n x=urllib.request.urlopen(r,timeout=P['to']); c,b,h=x.status,x.read(),dict(x.headers)\n"
             "except urllib.error.HTTPError as e: c,b,h=e.code,e.read(),dict(e.headers)\n"
             "print(json.dumps([c,b.decode(errors='replace'),{k.lower():v for k,v in h.items()}]))\n")
def _c2_in(service, method, path, token=None, body=None, timeout=30):
    """제품 컨테이너 안에서 그 서비스 자신의 API(127.0.0.1:8080)를 부른다 -> (상태, 본문 문자열, 소문자 헤더). 토큰은 표준 입력(코드)으로만 넘어가고 인자·출력에 남지 않는다."""
    code = _C2_IN_PY.replace("@@P@@", repr(json.dumps({"m": method, "path": path, "t": token, "b": body, "to": timeout})))
    c, b, h = json.loads(SB.exec_py(service, code, timeout=timeout + 30).strip().splitlines()[-1]); return c, b, h
def _c2_in_json(service, method, path, token=None, body=None):
    c, b, h = _c2_in(service, method, path, token, body); return c, _c2_dec(b), h

def _c2_ms_call(path, body, token, method="POST"):
    """추론 서버 호출 -> (상태, 본문 문자열, 소문자 헤더). 별도 호스트 역할로 띄운 추론 서버(SB.inference_url())가 있으면 그 주소로, 없으면 제품 안 model-serving 컨테이너 안에서."""
    base = SB.inference_url()
    if base is None: return _c2_in("model-serving", method, path, token, body)
    req = urllib.request.Request(base + path, data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None, method=method)
    if token: req.add_header("Authorization", f"Bearer {token}")
    if body is not None: req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, r.read().decode(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e: return e.code, e.read().decode(errors="replace"), {k.lower(): v for k, v in e.headers.items()}

@step('5c', repos=('survey-service', 'model-runtime') + _GW, deps=('4',),
      why="STATE['pointers'],['releases'] 를 읽는다. " + _P4)
def step5c():
    title("5c", "정정(CORRECT) 흐름: 값이 있는 턴 뒤 정정 발화 -> 서비스가 CORRECT 를 처리한다 (가짜 A 의 corrections, model-runtime 0.7.2)")
    if "pointers" not in STATE: rec("5c", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    new = STATE["releases"]["2"]
    wait(lambda: (lambda cr: cr[0] == 200 and cr[1].get("active_release") == new)(_c2_ready()), 300, f"survey가 릴리스 {new} 적재", every=3)
    # (1) 추론 서버 직접: 정정 발화는 at 문항(Q1.D02)에서만 CORRECT, 다른 문항에서는 일반 값 추출
    tok = INF_TOK(); utt = "아까 말한 거 아니에요"
    def ext(qid, text, state):
        ein = {"question_id": qid, "current_question": f"시험 문항 {qid}입니다.", "user_utterance": text, "state": state}
        validate("ActionExtractionInput", ein)
        c, body, _ = _c2_ms_call(f"/v1/releases/{new}/extract", ereq_of(ein), tok); assert c == 200, (qid, c, body[:200])
        out = json.loads(body); validate("ActionExtraction", out); return out
    o1 = ext("Q1.D02", utt, {"Q1.D01.diagnosed": {"value": True, "status": "ANSWERED"}})
    assert o1["action"] == "CORRECT" and o1["next_item"] == "Q1.D02", o1
    (cv,) = o1["values"]; assert (cv["key"], cv["value"], cv["status"], cv["save"]) == ("Q1.D01.diagnosed", False, "CORRECTION", True), cv
    o2 = ext("Q1.D03", utt, {}); assert o2["action"] == "NEXT" and o2["values"][0]["status"] == "ANSWERED", ("at 가 다른 문항인데 CORRECT 가 나왔다", o2)
    # (2) 서비스 경유: Q1.D01 에 '네' -> 저장, 다음 턴에 정정 발화
    sid = _sid(*_c2_kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}))
    rb = _c2_ready()[1]
    c, r1 = _c2_turn(sid, "cor-1", "네 있어요"); assert c == 200, (c, r1); validate_survey("FrontendInput", r1)
    v1 = {v["key"]: v for v in _c2_staff("GET", f"/v1/staff/sessions/{sid}")[1]["values"]}
    assert v1["Q1.D01.diagnosed"]["value"] is True and v1["Q1.D01.diagnosed"]["status"] == "ANSWERED", v1
    c, r2 = _c2_turn(sid, "cor-2", utt); assert c == 200, (c, r2); validate_survey("FrontendInput", r2)
    wait(lambda: _c2_ready()[1]["trace_outbox"]["sent"] - rb["trace_outbox"]["sent"] >= 2 or None, 30, "정정 턴의 Trace 전송")
    EA.check_turns_clean([r1, r2], rb, _c2_ready()[1])
    c, sv = _c2_staff("GET", f"/v1/staff/sessions/{sid}"); assert c == 200, (c, sv); validate_survey("StaffSessionView", sv)
    said = [t for t in sv["turns"] if t["utterance"]]
    assert [t["action"] for t in said] == ["NEXT", "CORRECT"], ("턴 기록의 action", [(t["turn_id"], t["action"]) for t in said])
    v2 = {v["key"]: v for v in sv["values"]}
    assert v2["Q1.D01.diagnosed"]["value"] is False and v2["Q1.D01.diagnosed"]["status"] == "CORRECTION", ("정정이 저장 값에 반영되지 않았다", v2["Q1.D01.diagnosed"])
    assert sv["status"] == "IN_PROGRESS", sv["status"]
    # (3) 대조: 같은 발화가 at 이 아닌 문항(Q1.D01)에서는 정정이 아니다
    sid2 = _sid(*_c2_kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}))
    c, r3 = _c2_turn(sid2, "ctl-1", utt); assert c == 200, (c, r3)
    sv3 = _c2_staff("GET", f"/v1/staff/sessions/{sid2}")[1]; said3 = [t for t in sv3["turns"] if t["utterance"]]
    assert [t["action"] for t in said3] == ["NEXT"] and all(v["status"] == "ANSWERED" for v in sv3["values"]), ("at 밖의 발화가 정정으로 처리됨", said3, sv3["values"])
    for s_ in (sid, sid2): _c2_kiosk(f"/v1/sessions/{s_}/end", {"session_id": s_, "kind": "SESSION_END"})
    rec("5c", "REAL", "정정 흐름(가짜 A corrections: '아까 말'+at Q1.D02, 키 Q1.D01.diagnosed). 추론 서버 직접: Q1.D02 에서 CORRECT(CORRECTION, 값 false, next_item Q1.D02), Q1.D03 에서는 NEXT. 서비스 경유: 'cor-1' 뒤 직원 세션 조회에서 Q1.D01.diagnosed=true ANSWERED -> 'cor-2' 뒤 턴 기록 action [NEXT, CORRECT], 값 false·status CORRECTION, 세션 IN_PROGRESS, 실패 신호 없음, Trace 전송. 대조 세션(Q1.D01 에서 같은 발화)은 NEXT·ANSWERED. 못 보는 것: 이력의 이전 값(NEW_REVISION)과 다음 질문 문항(공개 조회에 없음)")

@step('5o', repos=('survey-service', 'model-runtime', 'question-authoring', 'boundary-contracts') + _GW, deps=('4',),
      why="STATE['pointers'],['releases'] 를 읽는다. " + _P4,
      also={'question-authoring': '작성 양식의 칸 규격 줄(최소·최대)이 문항 은행의 칸 규격이 되어 extract 의 fields 로 간다(U24)'})
def step5o():
    title("5o", "칸 규격(일수 0~7)을 가진 문항에서 범위 밖 값(8일)이 REASK/OUT_OF_RANGE 로 바뀌어 저장되지 않는다 (model-runtime 0.10.0 값 규칙, 계약 2.4.0, D115)")
    if "pointers" not in STATE: rec("5o", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    new = STATE["releases"]["2"]
    wait(lambda: (lambda cr: cr[0] == 200 and cr[1].get("active_release") == new)(_c2_ready()), 300, f"survey가 릴리스 {new} 적재", every=3)
    ff = json.loads((pathlib.Path(__file__).resolve().parents[1] / "test" / "fake-model" / "question_flow.json").read_text(encoding="utf-8"))
    flow = {"order": ff["order"], "skips": ff["skips"]}
    fields = {"fields": [{"slot": "Q8_1.days", "data_type": "integer", "unit": "day/week", "minimum": 0, "maximum": 7}]}   # 시험 문항지(test/fixtures/question-form-v2.txt)의 Q8_1 칸 규격과 같다
    validate("QuestionFieldSpec", fields)
    tok = INF_TOK()
    def ext(text):
        ein = {"question_id": "Q8_1", "current_question": "시험 문항 Q8_1입니다.", "user_utterance": text, "state": {}}
        ereq = {"input": ein, "flow": flow, "fields": fields}; validate("ExtractRequest", ereq)
        c, body, h = _c2_ms_call(f"/v1/releases/{new}/extract", ereq, tok); assert c == 200, (text, c, body[:200]); out = json.loads(body); validate("ActionExtraction", out); return out
    # (1) 추론 서버 직접: fields 가 있으면 범위·값 규칙을 서버가 보증한다. 경계(0, 7)는 통과, 8 은 REASK/OUT_OF_RANGE
    EA.check_out_of_range_reask(ext("8일이요"), "Q8_1", "Q8_1.days", "[8일]")
    EA.check_fake_extraction(ext("7일이요"), "Q8_1.days", 7, "Q8_2", "[7일: 최대 포함]")
    EA.check_fake_extraction(ext("없어요"), "Q8_1.days", 0, "Q9_1", "[0일: 최소 포함]")
    # (2) 서비스 경유: 문항 은행에 칸 규격이 있으면 서비스가 extract 에 fields 를 싣는다(U24). Q8_1 까지 가짜 A 가 값을 내는 발화로 진행한 뒤 '8일이요'
    sid = _sid(*_c2_kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}))
    types = {k: v[0]["type"] for k, v in ff["slots"].items()}; answers = {}
    def skipped(item): return any(s["skip_item"] == item and s["slot"] in answers and type(answers[s["slot"]]) is type(s["value"]) and answers[s["slot"]] == s["value"] for s in ff["skips"])
    idx, turns = 0, 0
    while ff["order"][idx] != "Q8_1":
        q = ff["order"][idx]; qt = types.get(q)   # 칸이 없는 문항(Q3, Q4_1 …)은 값 없이 NEXT 만 낸다
        text = "3일이요" if qt == "integer" else "네 있어요"
        turns += 1; c, rp = _c2_turn(sid, f"rng-{turns}", text); assert c == 200, (q, c, rp); validate_survey("FrontendInput", rp)
        if qt: answers[ff["slots"][q][0]["key"]] = 3 if qt == "integer" else True
        idx += 1
        while idx < len(ff["order"]) and skipped(ff["order"][idx]): idx += 1
    sv0 = staff_sv(sid); got = {v["key"] for v in sv0["values"]}
    assert "Q7.does_not_drink" in got and "Q8_1.days" not in got, ("Q8_1 에 도달하지 못했다(진행 시뮬레이션이 서비스와 어긋남)", sorted(got)[-5:])
    c, bad = _c2_turn(sid, "rng-out-of-range", "8일이요"); assert c == 200, (c, bad); validate_survey("FrontendInput", bad)
    sv1 = staff_sv(sid); said = [t for t in sv1["turns"] if t["utterance"]]
    vals = {v["key"]: v for v in sv1["values"]}
    assert said[-1]["action"] == "REASK", ("범위 밖 값 뒤의 턴 action 이 REASK 가 아니다", said[-1])
    assert "Q8_1.days" not in vals or vals["Q8_1.days"].get("value") != 8, ("범위 밖 값 8 이 저장됐다", vals.get("Q8_1.days"))
    c, ok_ = _c2_turn(sid, "rng-retry", "3일이요"); assert c == 200, (c, ok_)
    sv2 = staff_sv(sid); v2 = {v["key"]: v for v in sv2["values"]}
    assert v2["Q8_1.days"]["value"] == 3 and v2["Q8_1.days"]["status"] == "ANSWERED", ("다시 답한 3일이 저장되지 않았다", v2.get("Q8_1.days"))
    _c2_kiosk(f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"})
    rec("5o", "REAL", f"일수 칸 규격(0~7, 값 단위 day/week). 추론 서버 직접(ExtractRequest{{input, flow, fields}}): 8일 -> REASK/OUT_OF_RANGE(같은 문항, 저장 안 하는 UNCLEAR, targets Q8_1.days), 7일·0일 -> NEXT(경계 포함). 서비스 경유: {turns}턴으로 Q8_1 도달 뒤 '8일이요' -> 턴 action REASK, Q8_1.days=8 저장 없음 -> '3일이요' -> 3 저장(ANSWERED).")

# ---- 시간 단언의 상수: 설정(config/Caddyfile, 서비스 문서)에서 도출한 값과 측정 환경별 관찰값을 이름으로 둔다. 단언의 의미(상한 안에 들어와야 한다)는 그대로이고, 한 환경의 측정값을 불변식처럼 쓰지 않는다.
ADMIN_CONSOLE_WAIT_S = {'release-gate': 190.0, 'question-authoring': 130.0, 'ops-feedback': 70.0, 'admin-console': 70.0}   # 관리 화면(admin-console 영역)의 경로별 대기(CONVENTIONS 시간표 D125): 각 경로의 gateway 상한(연결 + 헤더)이 이보다 짧아야 한다(ADR 0051)
STAFF_SCREEN_WAIT_S = 60.0   # 직원 화면(kiosk-frontend REQUEST_TIMEOUT_MS)의 대기: 직원 API 경로(@staffapi)의 gateway 상한이 이보다 짧고 서버 턴 마감보다 길어야 한다
KIOSK_WAIT_S = 60.0          # 키오스크 대기(kiosk-frontend 영역, 계약 CONVENTIONS 시간표 D125: 프록시·LB 표준 60초)
SURVEY_TURN_DEADLINE_S = 50.0 # survey-service 서버 턴 총 마감(SURVEY_TURN_DEADLINE_SECONDS, config/survey.env 가 정본이고 scripts/test_time_chain.py 가 같음을 본다)
GW_DIAL_PROXY_S = 1.0        # 사람용 프록시(proxy_limits) 연결 상한 dial_timeout
GW_READYZ_CAP_S = 3.0        # gateway /readyz 프록시 = 연결 1s + 응답 헤더 2s (Caddyfile)
GW_HDR_GATE_S, GW_HDR_OPS_S = 180.0, 60.0   # 사람용 프록시 응답 헤더 상한: release-gate / ops-feedback (proxy_limits, D125: 측정 최악 승인 128초·프록시 표준 60초 위의 여유)
DOCKER_DNS_FAIL_S = 3.0      # 멈춘 컨테이너 이름을 Docker 내부 DNS가 해석하지 못하는 지연. 근거: 설정 없는 Caddy가 이름 해석 실패 502를 3.0s 뒤에 냈다(docs/E2E.md 관찰, 한 환경에서 측정)
BASIC_AUTH_S = 2.0           # gateway 사람 인증 확인 시간의 여유(예전 basic_auth bcrypt 확인에서 정한 값을 forward_auth 왕복에도 그대로 둔다: 더 짧아져 여유가 늘 뿐이다). 관찰: 이 PC 약 0.9s(검토 목록 pause 가 설정 10s 에 10.87s). 근거 기록 없음 이상의 일반화는 하지 않는다
CLIENT_EXTRA_S = 2.0         # 호스트 클라이언트가 gateway 응답을 더 늦게 받는 정도. 관찰: gpu-dev(Docker Desktop 4.50) +0.5~1.9s, 이 PC 0 (docs/E2E.md 5w 계측)
# 연결 거부(상류 stop)가 걸리는 시간의 상한 = dial + Docker DNS 실패 지연 + 여유. 응답 헤더 상한(release-gate 180s)까지 매달리지 않고 그보다 충분히 짧게 끝나야 한다.
# 관찰값: 이 PC 2.7~3.8s, gpu-dev 4.6s. 한 환경의 측정이 아니라 위 설정·관찰에서 도출하되 헤더 상한의 절반 아래(90s)로 둔다.
CONN_REFUSED_MAX_S = GW_DIAL_PROXY_S + DOCKER_DNS_FAIL_S + 1.5
assert CONN_REFUSED_MAX_S < GW_HDR_GATE_S / 2, "연결 거부 상한이 응답 헤더 상한에 가까우면 단언이 의미가 없다"
READYZ_PAUSED_MAX_S = GW_READYZ_CAP_S + CLIENT_EXTRA_S   # gateway /readyz 가 무응답 상류에서 504 를 주기까지(클라이언트가 본 시간)
TURN_CLIENT_MAX_S = SURVEY_TURN_DEADLINE_S + CLIENT_EXTRA_S   # 클라이언트가 본 환자 턴 상한(서버 마감 + 호스트 전달 지연), 키오스크 대기(60s) 아래(gateway 상한 56s 는 호스트 전달 지연 여유 안)

def gwk(method, path, body=None, timeout=70, auth=True):
    """게이트웨이 경유 호출(키오스크 기기 토큰). (상태, 본문, 소문자 헤더, 걸린 초). 연결 오류는 상태 0."""
    t0 = time.time()
    try: c, b, hd = _c2_gw(method, path, body, token=_c2_kdev() if auth else None, timeout=timeout)
    except Exception as e: return 0, type(e).__name__, {}, time.time() - t0
    return c, b, hd, time.time() - t0

def gk_turn(sid, tid, text, timeout=70):
    return gwk("POST", f"/v1/sessions/{sid}/turns", {"session_id": sid, "kind": "UTTERANCE", "utterance": text, "turn_id": tid}, timeout)

def staff_sv(sid):
    c, sv = _c2_staff("GET", f"/v1/staff/sessions/{sid}"); assert c == 200, (c, sv); return sv

def utt_count(sv, text): return sum(1 for t in sv["turns"] if t["utterance"] == text)

def policy(step, waits, name, fn):
    """정책 단언: FAULT_POLICY 가 정한 기대인데 지금 영역 코드로는 통과하지 않을 수 있는 것. 통과하면 REAL, 아니면 POLICY-PENDING(실패가 아니다, 기다리는 변경과 지금 값을 적는다). 약화하지 않는다."""
    try: fn(); rec(f"{step}-policy", "REAL", f"정책 단언 통과: {name}")
    except AssertionError as e: rec(f"{step}-policy", "POLICY-PENDING", f"{name} -- 기다리는 변경: {waits}. 지금 값: {e}")

def gw_ready_seconds(timeout=60):
    """앱이 healthy 가 된 시점부터 게이트웨이 /readyz 가 200 + status ok 가 되기까지 걸린 초(0.25초 간격으로 확인). R4.1 의 "Retry-After 이내"를 재는 데 쓴다."""
    t0 = time.time(); wait_gw_ready(timeout, every=0.25); return time.time() - t0

def wait_gw_ready(timeout, every=2):
    def ready():   # R4.3·R5.1: 상태 코드 200 이고 본문 status 가 ok (빈 200·다른 본문은 준비가 아니다)
        c, b, _h, _t = gwk("GET", "/readyz", auth=False)
        return c == 200 and isinstance(b, dict) and b.get("status") == "ok"
    wait(ready, timeout, "gateway /readyz 200 + {\"status\":\"ok\"}(survey-service 가 활성 릴리스까지 적재)", every=every)

def upstream_503_json(c, b, h, what):
    assert c == 503 and b == {"code": "UPSTREAM_UNAVAILABLE"}, f"{what}: 503 UPSTREAM_UNAVAILABLE 이 아니다: {c} {str(b)[:120]}"
    assert h.get("content-type", "").startswith("application/json") and h.get("retry-after"), f"{what}: Content-Type/Retry-After 헤더 {h.get('content-type')} {h.get('retry-after')}"
    assert "survey" not in json.dumps(b) and ":8080" not in json.dumps(b), f"{what}: 본문에 내부 주소"

@step('5q', repos=('survey-service', 'kiosk-frontend') + _GW, deps=('4',),
      why="STATE['pointers'] 를 읽고 survey-service 를 stop/start 한다(끝에 되돌린다). " + _P4)
def step5q():
    title("5q", "survey-service 컨테이너 중지 -> gateway 경유 환자 API 503 UPSTREAM_UNAVAILABLE, gateway /readyz 비정상, /healthz 200 -> 기동 -> 복구, 세션 보존 (FAULT_POLICY 6)")
    if "pointers" not in STATE: rec("5q", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    wait_gw_ready(300)
    svc = f"{a.project}-survey-service-1"; sid = f"sess-{RID}-outq"
    sid = _sid(*_c2_kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}))
    c, r1 = _c2_turn(sid, "q-1", "네 있어요"); assert c == 200, (c, r1)
    sh([a.docker, "stop", "-t", "3", svc]); obs = {}
    try:
        c, b, h, el = gk_turn(sid, "q-2", "아니요 없어요"); obs["turn"] = (c, round(el, 2)); upstream_503_json(c, b, h, "환자 턴")
        obs["retry_after"] = float(h.get("retry-after", "2") or 2)
        rc, rb_, rh, rel = gwk("GET", "/readyz", auth=False); obs["readyz"] = (rc, round(rel, 2)); assert rc != 200, "survey-service 가 없는데 gateway /readyz 가 200"
        assert "survey" not in json.dumps(rb_) and ":8080" not in json.dumps(rb_), f"gateway /readyz 본문에 내부 정보: {rb_}"
        hc = gwk("GET", "/healthz", auth=False); obs["healthz"] = hc[0]; assert hc[0] == 200, hc[:2]
    finally: sh([a.docker, "start", svc])
    wait(lambda: sh([a.docker, "inspect", "-f", "{{.State.Health.Status}}", svc]).stdout.strip() == "healthy", 120, "survey-service healthy", every=2)
    wait(lambda: SB.readyz("survey-service")[0] == 200, 180, "survey-service /readyz 200(중계 경유, 활성 릴리스 적재까지)", every=0.5)   # R4.1 은 앱의 /readyz 가 200 이 된 뒤부터 센다
    t_rec = gw_ready_seconds(300)
    assert t_rec <= obs["retry_after"] + 0.5, f"R4.1: 앱이 healthy 가 된 뒤 게이트웨이가 다시 응답하기까지 {t_rec:.2f}s 가 Retry-After {obs['retry_after']}s 를 넘었다(0.5s 은 폴링 간격 여유)"
    sv = staff_sv(sid); vals = {v["key"]: v for v in sv["values"]}
    assert vals["Q1.D01.diagnosed"]["value"] is True, ("재시작 뒤 이전 값이 사라졌다", vals)
    assert utt_count(sv, "아니요 없어요") == 0 and "Q1.D02.diagnosed" not in vals, "상류에 닿지 못한 턴이 기록됐다"
    c, r2 = _c2_turn(sid, "q-2", "아니요 없어요"); assert c == 200, ("복구 뒤 같은 turn_id 재전송이 200이 아니다", c, r2)
    assert {v["key"]: v for v in staff_sv(sid)["values"]}["Q1.D02.diagnosed"]["value"] is False
    def idem():
        c, again = _c2_turn(sid, "q-1", "네 있어요"); assert c == 200 and again == r1, ("재시작 뒤 이미 확정된 turn_id 재전송이 저장된 응답과 다르다", c, str(again)[:100])
        assert utt_count(staff_sv(sid), "네 있어요") == 1, "같은 turn_id 가 두 번 기록됐다"
    policy("5q", "survey-service 의 turn_id 멱등(저장된 결과 재생)", "재시작 뒤 확정된 turn_id 재전송은 같은 응답이고 한 번만 기록된다", idem)
    # R3.1: 컨테이너를 멈추는 것(위)과 다른 경우 — 앱 프로세스가 죽는다(SIGKILL). restart 정책이 다시 올리는 동안 게이트웨이가 503 + UPSTREAM_UNAVAILABLE + Retry-After 를 주고(504·빈 502 아님),
    # 다시 올라오면 사람 손 없이 같은 주소로 응답한다(R4.1: 복구까지 걸린 시간을 Retry-After 와 비교하지 않고 준비 확인으로 기다린다, R4.3)
    sh([a.docker, "kill", "-s", "KILL", svc]); seen = None; t_kill = time.time()
    while time.time() - t_kill < 30 and seen is None:
        c, b, h = _c2_gw("GET", f"/v1/sessions/{sid}/state", None, token=_c2_kdev(), timeout=10)
        if c != 200: seen = (c, b, h)
        else: time.sleep(0.2)   # 폴링 간격(정지 구간 관찰 루프, 종료 조건은 비 200 응답)
    assert seen is not None, "프로세스를 죽였는데 30초 안에 정지 구간(비 200 응답)을 관찰하지 못했다"
    upstream_503_json(*seen, "프로세스 죽음 중 환자 세션 조회")
    wait(lambda: sh([a.docker, "inspect", "-f", "{{.State.Health.Status}}", svc]).stdout.strip() == "healthy", 120, "프로세스 죽음 뒤 survey-service healthy(restart 정책)", every=2)
    wait_gw_ready(300)
    assert _c2_gw("GET", f"/v1/sessions/{sid}/state", None, token=_c2_kdev(), timeout=20)[0] == 200, "프로세스 죽음에서 복구한 뒤 세션 조회가 200이 아니다"
    _c2_kiosk(f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"})
    rec("5q", "REAL", f"(프로세스 SIGKILL 도 503 JSON + restart 복구) survey-service stop 중 gateway 경유: 환자 턴 {obs['turn'][0]}({obs['turn'][1]}s) {{\"code\":\"UPSTREAM_UNAVAILABLE\"}} + Retry-After + JSON(본문에 내부 주소 없음), gateway /readyz {obs['readyz'][0]}({obs['readyz'][1]}s), /healthz {obs['healthz']}. start 뒤 gateway /readyz 200 까지 {t_rec:.0f}s. 세션 보존(Q1.D01 값 유지, 상류에 닿지 못한 턴은 기록 없음), 같은 turn_id 로 재전송하면 200 으로 확정")

def gw_log_duration(path_part, since):
    """gateway(Caddy) 접근 로그(JSON)에서 path_part 가 든 요청의 서버 쪽 처리 시간(duration, 초)과 상태를 (가장 최근 것으로) 읽는다. 클라이언트와 gateway 사이 전달 지연은 이 값에 들지 않는다."""
    # 왜 SB.logs: 게이트웨이 접근 로그는 컨테이너 밖 포트가 아니라 제품 프로젝트의 로그로 읽는다. --since 는 RFC3339(UTC)로 준다(docker compose logs 가 받는 표준 형식)
    best = None
    for ln in SB.logs("gateway", since=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(since) - 1))).splitlines():
        try: d = json.loads(ln)
        except ValueError: continue
        if path_part in d.get("request", {}).get("uri", "") and d.get("duration") is not None: best = (float(d["duration"]), d.get("status"))
    return best

@step('5w', repos=('survey-service', 'kiosk-frontend') + _GW, deps=('4',),
      why="STATE['pointers'] 를 읽고 survey-service 를 pause/unpause 한다. " + _P4)
def step5w():
    title("5w", "survey-service 무응답(docker pause) -> gateway 경유 환자 요청이 마감 안에 504 UPSTREAM_UNAVAILABLE -> unpause 후 복구 (FAULT_POLICY 6)")
    if "pointers" not in STATE: rec("5w", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    wait_gw_ready(300)
    svc = f"{a.project}-survey-service-1"; sid = f"sess-{RID}-outw"
    sid = _sid(*_c2_kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}))
    sh([a.docker, "pause", svc]); obs = {}
    try:
        t_req = time.time(); c, b, h, el = gk_turn(sid, "w-1", "네 있어요", timeout=70); obs["turn"] = (c, round(el, 2))
        assert c == 504 and b == {"code": "UPSTREAM_UNAVAILABLE"} and h.get("retry-after"), f"무응답 상류: 504 UPSTREAM_UNAVAILABLE 이 아니다: {c} {str(b)[:100]}"
        # 불변식: 키오스크 대기(60s) > gateway 처리 시간 > 서버 턴 총 마감(50s, SURVEY_TURN_DEADLINE_SECONDS). 설정은 연결 1s + 응답 헤더 55s(합 56s 상한, config/Caddyfile).
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
    policy("5w", "Docker Desktop(WSL2) 호스트 게시 포트 전달 지연(운영 서버의 gateway 직접 접속에서는 해당 없음, 미확인)", "호스트 클라이언트가 본 gateway 504 시간이 키오스크 대기(60s) 미만이다", client_seen)
    # 멈춘 사이 도착한 요청을 서비스가 풀린 뒤 처리했을 수 있다: 고정 3초가 아니라 발화 기록 수가 안정될 때까지 기다린다(R4.3)
    settled(lambda: utt_count(staff_sv(sid), "네 있어요"), 30, what="unpause 뒤 발화 기록 수 안정")
    sv = staff_sv(sid); n_after_unpause = utt_count(sv, "네 있어요")
    c, r = _c2_turn(sid, "w-1", "네 있어요"); assert c == 200, ("복구 뒤 같은 turn_id 재전송이 200이 아니다", c, r)
    n_final = utt_count(staff_sv(sid), "네 있어요")
    print(f"  관찰: 504 를 받은 턴 w-1 이 unpause 뒤 서비스에서 처리된 횟수 {n_after_unpause}, 같은 turn_id 재전송 뒤 기록 {n_final}회")
    policy("5w", "survey-service 의 turn_id 멱등(처리 중·확정 재전송은 새로 처리하지 않음)", "504 로 끝난 턴을 같은 turn_id 로 재전송해도 발화는 한 번만 기록된다", lambda: (_ for _ in ()).throw(AssertionError(f"기록 {n_final}회")) if n_final != 1 else None)
    _c2_kiosk(f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"})
    rec("5w", "REAL", f"survey-service pause 중 gateway 경유: 환자 턴 {obs['turn'][0]} 까지 클라이언트 {obs['turn'][1]}s / gateway 접근 로그 duration {obs['gw_duration']}s (설정: 연결 1s + 응답 헤더 55s), gateway /readyz {obs['readyz'][0]}({obs['readyz'][1]}s, 설정 2s), /healthz {obs['healthz']}. unpause 뒤 gateway /readyz 200 까지 {t_rec:.0f}s. 멈춘 사이 요청이 풀린 뒤 서비스에서 처리된 횟수 {n_after_unpause}")

@step('5u', repos=('release-gate', 'survey-service') + _GW, deps=(),
      why='step5u 는 STATE 를 읽지 않는다. 활성 릴리스가 있어야 하는지는 코드를 읽어 확정하지 못했다',
      also={'ops-feedback': 'ops-feedback 무응답 때 gateway의 검토 경로 상한'})
def step5u():
    title("5u", "사람이 쓰는 화면 경로(승인·운영·검토)의 gateway 상류 상한: release-gate 중지/무응답, ops-feedback 무응답 (FAULT_POLICY 6, config/Caddyfile proxy_limits)")
    gate, ops = f"{a.project}-release-gate-1", f"{a.project}-ops-feedback-1"
    def call(path, acct, who):
        t0 = time.time(); c, b, h = _c2_raw("GET", path, basic=acct); return c, b, time.time() - t0, t0
    def up503(c, b, what): assert c == 503 and b == {"code": "UPSTREAM_UNAVAILABLE"}, f"{what}: 503 UPSTREAM_UNAVAILABLE 이 아니다: {c} {str(b)[:100]}"
    obs = {}
    # (1) release-gate 중지: 승인 조회(C7, release-approver)와 운영자 읽기(C8, operator)가 빨리 503 JSON
    sh([a.docker, "stop", "-t", "3", gate])
    try:
        for lab, path, acct in (("승인 조회 C7", "/v1/submissions", _C2_ADMIN), ("운영자 active-pointer C8", "/v1/active-pointer", _C2_OPERATOR)):
            c, b, el, _ = call(path, acct, lab); up503(c, b, lab); assert el < CONN_REFUSED_MAX_S, f"{lab}: 연결 거부인데 {el:.1f}s 걸렸다(상한 {CONN_REFUSED_MAX_S:.1f}s = dial {GW_DIAL_PROXY_S}s + Docker DNS 실패 {DOCKER_DNS_FAIL_S}s + 여유, 응답 헤더 상한 {GW_HDR_GATE_S}s 까지 매달리면 안 된다)"; obs[lab] = (c, round(el, 2))
    finally: sh([a.docker, "start", gate])
    wait(lambda: sh([a.docker, "inspect", "-f", "{{.State.Health.Status}}", gate]).stdout.strip() == "healthy", 120, "release-gate healthy", every=2)
    wait(lambda: _c2_raw("GET", "/v1/submissions", basic=_C2_ADMIN)[0] == 200, 60, "승인 조회 복구(200)", every=2)
    # (2) release-gate 무응답(pause): gateway 상한(release-gate 연결 1s + 헤더 180s, ops-feedback 60s 설정; 접근 로그 duration 으로 잰다)
    def paused(svc, path, acct, lab, lo, hi):
        sh([a.docker, "pause", svc])
        try:
            c, b, el, t0 = call(path, acct, lab); assert c == 504 and b == {"code": "UPSTREAM_UNAVAILABLE"}, f"{lab}: 504 UPSTREAM_UNAVAILABLE 이 아니다: {c} {str(b)[:100]}"
            gd = gw_log_duration(path, t0); assert gd and gd[1] == 504, f"{lab}: gateway 로그에서 못 찾았다 {gd}"
            assert lo <= gd[0] < hi, f"{lab}: gateway 처리 시간 {gd[0]:.2f}s 가 설정 상한({lo}~{hi}s)과 다르다"
            obs[lab] = (c, round(el, 1), round(gd[0], 2))
        finally: sh([a.docker, "unpause", svc])
    paused(gate, "/v1/submissions", _C2_ADMIN, "승인 조회 pause", GW_HDR_GATE_S - 0.5, GW_HDR_GATE_S + BASIC_AUTH_S)
    wait(lambda: _c2_raw("GET", "/v1/submissions", basic=_C2_ADMIN)[0] == 200, 60, "승인 조회 복구(200)", every=2)
    paused(ops, "/v1/cases", _C2_REVIEWER, "검토 목록 pause", GW_HDR_OPS_S - 0.5, GW_HDR_OPS_S + BASIC_AUTH_S)
    wait(lambda: _c2_raw("GET", "/v1/cases", basic=_C2_REVIEWER)[0] == 200, 60, "검토 목록 복구(200)", every=2)
    rec("5u", "REAL", "사람이 쓰는 화면 경로의 gateway 상류 상한: release-gate 중지 중 승인 조회 " + f"{obs['승인 조회 C7']}·운영자 읽기 {obs['운영자 active-pointer C8']}(코드, 초)가 503 {{\"code\":\"UPSTREAM_UNAVAILABLE\"}}; release-gate 무응답 중 승인 조회 {obs['승인 조회 pause']}(코드, 클라이언트 초, gateway duration 초; 설정 헤더 180s), ops-feedback 무응답 중 검토 목록 {obs['검토 목록 pause']}(설정 헤더 60s)이 504 UPSTREAM_UNAVAILABLE; 해제 뒤 모두 200 복구. 정적 화면(admin-console, kiosk-frontend) 프록시의 상한은 같은 설정이나 이 단계에서 시험하지 않았다")

@step('5m', repos=('survey-service', 'model-runtime', 'kiosk-frontend') + _GW, deps=('4',),
      why="STATE['pointers'] 를 읽고 model-serving 을 pause 한다. " + _P4)
def step5m():
    title("5m", "model-serving 무응답(docker pause) 중 환자 턴: survey 턴 마감 안에 분류된 실패, 값 미저장, unpause 뒤 같은 turn_id 확정 (FAULT_MATRIX B1, model-runtime 요청 상한)")
    if "pointers" not in STATE: rec("5m", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    wait_gw_ready(300)
    sid = f"sess-{RID}-outm"
    sid = _sid(*_c2_kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}))
    c, r1 = _c2_turn(sid, "m-1", "네 있어요"); assert c == 200 and not r1.get("turn_failure_signal"), (c, r1)
    sidr = _sid(*_c2_kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}))
    phrase, _rules = risk_phrase()
    sh([a.docker, "pause", MS_CONTAINER])
    try:
        # 모델 서버가 멈춘 턴에서도 위험 발화의 직원 알림이 먼저 나간다(D88 U1: 규칙 감지는 모델 추출·쓰기 확정과 무관). 추출 호출 없이 정지하므로 마감 안에 끝난다
        t_r = time.time(); cr, rr = _c2_turn(sidr, "mr-1", f"저는 {phrase} 있어요"); dt_r = time.time() - t_r
        assert cr == 200 and (rr.get("turn_failure_signal") or {}).get("staff_alert") in ("DELIVERED", "DELIVERY_FAILED"), ("모델 서버가 멈췄는데 위험 발화의 직원 알림이 나가지 않았다", cr, str(rr)[:160])
        assert dt_r < TURN_CLIENT_MAX_S, f"위험 정지 턴이 마감을 넘겼다: {dt_r:.1f}s (상한 {TURN_CLIENT_MAX_S}s = 서버 마감 {SURVEY_TURN_DEADLINE_S}s + 클라이언트 지연 여유)"
        assert [x for x in _c2_staff("GET", "/v1/staff/alerts?status=OPEN")[1]["items"] if x["session_id"] == sidr], "모델 서버가 멈춘 중의 위험 발화가 직원 알림 목록에 없다"
        t_req = time.time(); c, b, h, el = gk_turn(sid, "m-2", "아니요 없어요", timeout=70)
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
        c2, r2 = _c2_turn(sid, "m-2", "아니요 없어요"); tries.append((c2, r2))
        if c2 == 200 and not r2.get("turn_failure_signal"): break
        time.sleep(3)   # 재시도 간격(복구 폴링): 같은 turn_id 를 서비스가 준비된 뒤 다시 보내는 사이의 간격이고, 종료 조건은 200 + 실패 신호 없음이다(상한은 반복 횟수). 복구를 sleep 으로 흉내 내는 것이 아니다
    def same_id_confirms(): assert tries[-1][0] == 200 and not tries[-1][1].get("turn_failure_signal"), f"같은 turn_id 재전송 {len(tries)}회 모두 실패 응답: {str(tries[-1][1])[:150]}"
    policy("5m", "survey-service: NOT_COMMITTED 로 끝난 턴의 turn_id 재전송이 새로 처리되도록(CR-D25)", "model-serving 정지로 실패한 턴을 unpause 뒤 같은 turn_id 로 재전송하면 확정된다", same_id_confirms)
    # 서비스 자체의 복구는 새 turn_id 로 확인한다(하드 단언): 값이 한 번 저장된다
    if not (tries[-1][0] == 200 and not tries[-1][1].get("turn_failure_signal")):   # 같은 turn_id 가 확정되지 않았을 때만(확정됐다면 이미 저장돼 중복 기록이 된다)
        def new_id():
            c3, r3 = _c2_turn(sid, "m-3", "아니요 없어요"); return c3 == 200 and not r3.get("turn_failure_signal")
        wait(new_id, 60, "unpause 뒤 새 turn_id 턴 확정", every=3)
    sv2 = staff_sv(sid); assert {v["key"]: v for v in sv2["values"]}["Q1.D02.diagnosed"]["value"] is False, "복구 뒤 값이 저장되지 않았다"
    n_final = utt_count(sv2, "아니요 없어요")
    # model-runtime 요청 상한(MODEL_RUNTIME_REQUEST_DEADLINE_S 3.5s)과 엔진 멈춤 시 /readyz 503 은 pause 로는 볼 수 없다(컨테이너가 통째로 얼어 /readyz 도 응답하지 못한다).
    # 이 이미지가 그 코드를 가졌는지는 라벨의 model-runtime 태그로만 안다: 태그가 73e79f9(요청 상한) 이후를 포함해야 한다.
    # 감시 스택(Prometheus 규칙, ADR 0037)이 보는 것과 같은 필드를 직접 읽는다: model-serving /readyz 200(엔진 정상), release-gate /readyz 의 judging_loop(연속 실패 3 미만, 인증 실패 아님)
    _rc, _rb, _ = _c2_ms_call("/readyz", None, None, "GET")
    assert _rc == 200 and json.loads(_rb or "null").get("status") == "ready", ("model-serving /readyz", _rc, (_rb or "")[:120])   # 상태 코드만 보지 않는다: 사이드카가 맞는 사이트를 못 고르면 본문 없는 200 이 올 수 있다(e5779d9)
    gc, gr = SB.readyz("release-gate"); assert gc == 200, ("release-gate /readyz", gc)   # 상태 관찰: 컨테이너 안 /readyz(감시 스택이 보는 같은 필드)
    jl = gr.get("judging_loop")
    assert jl is not None and not jl.get("upstream_auth_failed") and (jl.get("consecutive_failures") or 0) < 3, ("release-gate 판정 루프", jl)
    rec("5m", "REAL", f"model-serving pause 중 환자 턴(gateway 경유): 상태 {c}, gateway duration {gd[0]:.2f}s(survey 턴 마감 50s 안), 실패 응답 {body}; 위험 발화는 같은 모델 정지 중에도 직원 알림(staff_alert)이 먼저 나갔다({dt_r:.1f}s); 값 저장 없음(Q1.D01 유지, Q1.D02 없음), 중지 중 발화 기록 {n_logged}건; unpause 뒤 새 turn_id 턴은 확정(값 저장, 서비스 복구); 같은 turn_id(m-2) 재전송은 정책 단언(survey-service 가 실패 응답을 저장해 계속 NOT_COMMITTED 를 돌려주면 POLICY-PENDING, CR-D25). 발화 기록 {n_final}건. 실제 스택에서 직접 읽은 model-serving /readyz OK, release-gate 판정 루프 (연속 실패 {jl.get('consecutive_failures')}회)를 읽었다. 못 보는 것: model-runtime 요청 상한 3.5s·엔진 멈춤 시 /readyz 503(pause 로는 컨테이너가 통째로 얼어 볼 수 없고, 이 E2E 이미지의 model-runtime 태그에 상한 코드가 들어 있는지는 docs/E2E.md 참고)")

def gw_bytes(method, path, data, ctype, basic=None, headers=None):
    """게이트웨이 경유 원문 본문 호출(자료 업로드). (상태, JSON 또는 문자열, 헤더)"""
    return _c2_gw(method, path, account=basic, raw=data, ctype=ctype if data is not None else None, headers=headers, timeout=60)

def _c2_qa_read(method, *args, **kw):
    """이웃 읽기 면(I1)은 게이트웨이에 열지 않는다. 읽는 주체(synthetic-data·release-gate)가 제품 네트워크 안에 있으므로 question-authoring 컨테이너 안에서 그 이미지의 boundary_contracts 클라이언트(HttpQuestionReader)로 읽는다.
    토큰은 서비스가 이미 가진 읽기 토큰 표(/run/secrets/qa-read-tokens)에서 release-gate 몫을 컨테이너 안에서 꺼낸다(호스트로 나오지 않는다)."""
    code = ("import json\nfrom openit_link.clients import HttpQuestionReader\n"
            "tok=None\nfor ln in open('/run/secrets/qa-read-tokens'):\n n,_,v=ln.strip().partition('=')\n if n=='release-gate': tok=v.split(',')[0]\n"
            "assert tok, 'qa-read-tokens 에 release-gate 항목이 없다'\n"
            "P=json.loads(" + repr(json.dumps({"m": method, "a": list(args), "k": kw})) + ")\n"
            "r=getattr(HttpQuestionReader('@SELF@',tok),P['m'])(*P['a'],**P['k'])\n"
            "print(json.dumps(r,default=lambda o: dict(o) if hasattr(o,'keys') else list(o)))\n")
    return json.loads(SB.exec_py("question-authoring", code).strip().splitlines()[-1])

@step('5a', repos=('question-authoring', 'admin-console') + _GW, deps=(),
      why='step5a 는 STATE 를 읽지 않는다. 그러나 앞 단계가 만든 저자 계정·문항 상태에 의존하는지는 코드를 읽어 확정하지 못했다')
def step5a():
    title("5a", "저자 경로(question-authoring)를 gateway OIDC 로그인 뒤에서: 자료 등록·확인(author), 임상 근거 승인(clinical-reviewer), 자기 승인 403, 본문 상한 (D88/U9)")
    qset = f"qs-{RID}-gwauthor"; form = form_for(qset, (ROOT / "test/fixtures/question-form-v2.txt").read_text()).encode()
    up = f"/v1/materials?question_set_id={qset}&filename=gw.txt"
    assert gw_bytes("POST", up, form, "text/plain")[0] == 401, "인증 없이 저자 경로가 열려 있다"
    assert gw_bytes("POST", up, form, "text/plain", basic=_C2_STAFF)[0] == 403, "author 역할이 아닌 계정(staff)이 저자 경로를 쓸 수 있다"
    c, d, _ = gw_bytes("POST", up, form, "text/plain", basic=_C2_AUTHOR, headers={"X-Openit-User": "spoofed-user", "Authorization-X": "x"}); assert c in (200, 201), ("자료 등록", c, d)
    c, pv, _ = _c2_raw("GET", f"/v1/drafts/{d['draft_id']}/preview", basic=_C2_AUTHOR); assert c == 200 and pv["ready_to_confirm"], (c, pv)
    c, ref, _ = _c2_raw("POST", f"/v1/drafts/{d['draft_id']}/confirm", {"preview_hash": pv["preview_hash"]}, basic=_C2_AUTHOR); assert c == 200, ("확인", c, ref)
    # 1인 운영(QA_REQUIRE_TWO_PERSON=false, L13): 저자의 확정이 임상 근거 승인을 함께 남기고, 임상 검수 역할은 /v1/reviews 403(설계). 위조 X-Openit-User 는 무시되어 인증 계정이 기록된다
    body = {"question_set": ref, "decision": "APPROVED", "clinical_basis_approved": True, "reason": "E2E: 1인 운영에서 검수 역할은 거부돼야 한다"}
    c, e, _ = _c2_raw("POST", "/v1/reviews", body, basic=_C2_CLINICAL, headers={"X-Openit-User": _C2_AUTHOR}); assert c == 403 and e.get("code") == "PERMISSION_DENIED", ("1인 운영에서 임상 검수 역할이 /v1/reviews 를 통과했다", c, e)
    revs = list(_c2_qa_read("get_reviews", ref)); assert len(revs) == 1, len(revs)
    assert revs[-1]["clinical_basis_approved"] is True and revs[-1]["reviewer_id"] == _C2_AUTHOR, ("저자의 확정이 임상 근거 승인을 남기고, 위조 헤더가 무시돼 인증 계정이 기록돼야 한다", revs[-1])
    assert dict(_c2_qa_read("latest", qset, reviewed_only=True))["version"] == ref["version"], "임상 승인 뒤 reviewed_only 에 나타나야 한다"
    # 이웃 읽기 면(I1)은 gateway 에 열지 않는다. 본문 상한 8MiB 초과는 413
    assert _c2_raw("GET", f"/v1/question-sets/{qset}/versions", basic=_C2_AUTHOR)[0] == 404, "I1 읽기 면이 gateway 에 열려 있다"
    assert _c2_raw("GET", "/v1/question-sets", basic=_C2_AUTHOR)[0] == 401, "정확히 /v1/question-sets 는 키오스크 목록(I10)이라 사람 계정이 아니라 기기 토큰만 받는다"
    # R3.5: 본문 상한(8MiB) 초과는 게이트웨이가 상류로 보내기 전에 413 + {"code":"PAYLOAD_TOO_LARGE"} 로 거절한다(예전엔 "413 또는 연결 끊김"을 모두 거부로 봤다: 연결 끊김은 R3.5 가 아니다).
    # curl 로 보낸다: 서버가 413 을 먼저 보내고 연결을 닫으면 파이썬 urllib 은 보내던 중 쓰기 오류로 응답을 못 읽는다(curl 은 응답이 오면 읽는다). 쿠키는 OIDC 로그인 세션을 쓴다
    cookie = SB.session_cookie(_C2_AUTHOR)
    r9 = subprocess.run(["curl", "-s", "-m", "60", "--cacert", str(a.gw_ca), "-o", "-", "-w", "\n%{http_code} %{content_type}", "-X", "POST", "-H", f"Cookie: {cookie}", "-H", "Content-Type: text/plain",
                         "--data-binary", "@-", SB.gw_url(human=True) + up], input=b"x" * (9 * 1024 * 1024), capture_output=True)
    out9 = r9.stdout.decode(errors="replace").rsplit("\n", 1)
    code9, ctype9 = (out9[-1].split(" ", 1) + [""])[:2]
    assert code9 == "413" and "PAYLOAD_TOO_LARGE" in out9[0] and ctype9.startswith("application/json"), ("8MiB 초과 본문이 413 + PAYLOAD_TOO_LARGE + application/json 이 아니다", code9, out9[0][:100], ctype9)
    rec("5a", "REAL", f"저자 경로(gateway 경유, 개별 계정): 인증 없음 401, 역할 없는 계정 403, author 계정의 자료 등록·미리보기·확인(문항 세트 {qset}@{ref['version']}), 저자의 자기 임상 승인 403(4-eyes), clinical-reviewer 계정의 승인 200(위조 X-Openit-User 는 무시되고 reviewer_id={_C2_CLINICAL} 가 기록됨), 승인 뒤 reviewed_only 최신 버전, I1 읽기 면 404, 9MiB 본문 거부({c9})")

def dev_tok(d): return SB.DeviceId(d)   # 기기 d 의 클라이언트 인증서(mTLS)
@step('5d', repos=('survey-service', 'kiosk-frontend') + _GW, deps=('4',),
      why="STATE['pointers'] 를 읽는다. " + _P4)
def step5d():
    title("5d", "기기 인증서(mTLS, D136): 기기 A가 만든 세션에 기기 B는 접근하지 못한다, 허용 목록 밖·CA 밖 인증서는 거부, 목록에서 일련번호를 빼면 다음 요청부터 거부되고 되돌리면 회복")
    if "pointers" not in STATE: rec("5d", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    wait_gw_ready(300)
    A, B = dev_tok("e2e-a"), dev_tok("e2e-b")
    def gk(tok, method, path, body=None):
        c, b, _h = _c2_gw(method, path, body, token=tok); return c, b
    c, st = gk(A, "POST", "/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}); sid = _sid(c, st)   # 서버가 발급한 session_id
    c, r = gk(A, "POST", f"/v1/sessions/{sid}/turns", {"session_id": sid, "kind": "UTTERANCE", "utterance": "네 있어요", "turn_id": "dA-1"}); assert c == 200, ("기기 A 발화", c, r)
    cs, _ = gk(A, "GET", f"/v1/sessions/{sid}/state"); assert cs in (200, 429), ("기기 A 상태 조회", cs)
    # 기기 B 는 같은 session_id 로 상태·발화·종료를 시도해도 세션에 접근하지 못한다(계약상 404, 존재를 드러내지 않는다)
    time.sleep(1)   # 속도 제한 간격: 서버가 0.5초보다 잦은 상태 조회를 429 로 막는다(위 state 조회 직후라 1초 둔다). 복구 대기가 아니다
    for lab, m, pth, bd in (("상태", "GET", f"/v1/sessions/{sid}/state", None),
                            ("발화", "POST", f"/v1/sessions/{sid}/turns", {"session_id": sid, "kind": "UTTERANCE", "utterance": "아니요 없어요", "turn_id": "dB-1"}),
                            ("종료", "POST", f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"})):
        cb, rb = gk(B, m, pth, bd); assert cb in (404, 403), (f"기기 B 가 기기 A 의 세션에 {lab} 접근이 허용됐다", cb, str(rb)[:100])
    sv = staff_sv(sid); assert utt_count(sv, "아니요 없어요") == 0 and sv["status"] == "IN_PROGRESS", "기기 B 의 시도가 세션을 바꿨다"
    c, r2 = gk(A, "POST", f"/v1/sessions/{sid}/turns", {"session_id": sid, "kind": "UTTERANCE", "utterance": "아니요 없어요", "turn_id": "dA-2"}); assert c == 200, ("기기 A 는 계속 정상이어야 한다", c, r2)
    # 계약 4.0.4 PUBLIC_API F절: 게이트웨이→survey 키오스크 경로 서비스 토큰(survey-api-kiosk)은 필수다. 정상 배포의 /readyz 는 shared_kiosk_token=true
    rz = _c2_ready()[1]; kt = rz.get("kiosk_tokens") or {}
    assert kt.get("shared_kiosk_token") is True, ("/readyz 의 키오스크 경로 게이트웨이 토큰 상태", kt)
    env = {"SECRETS_DIR": a.secrets, "DEPLOY_PROJECT": a.project}
    kad = lambda *args: sh(["bash", str(ROOT / "scripts/kiosk-add-device.sh"), *args], env=env)
    # (1) 신뢰 CA 가 발급했지만 허용 목록에 없는 인증서: 403 PERMISSION_DENIED(BoundaryError). 운영자가 하지 않은 등록은 없다
    sh(["bash", "-c", 'source "$1/scripts/lib.sh" && source "$1/scripts/gateway-lib.sh" && gw_issue_device_cert "$2" e2e-unlisted >/dev/null', "x", str(ROOT), a.secrets], env=env)
    cu, bu = gk(SB.DeviceId("e2e-unlisted"), "POST", "/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}); _assert_denied("허용 목록에 없는 기기 인증서", cu, bu)
    # (2) 다른 CA 가 발급한 인증서(CN 은 e2e 와 같다): TLS 핸드셰이크에서 거절된다(HTTP 응답이 없다, RFC 8446 클라이언트 인증 실패). 기대는 상태 코드가 아니라 연결 오류다
    rg = WORK / "rogue-ca"; rg.mkdir(parents=True, exist_ok=True)
    sh(["bash", "-c", 'set -e; cd "$1"; openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout ca.key -out ca.pem -subj /CN=rogue-ca -days 2 >/dev/null 2>&1; '
       'openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout d.key -out d.csr -subj /CN=e2e >/dev/null 2>&1; '
       'printf "extendedKeyUsage=clientAuth\n" > ext; openssl x509 -req -in d.csr -CA ca.pem -CAkey ca.key -set_serial 0x5151 -days 2 -extfile ext -out d.crt >/dev/null 2>&1', "x", str(rg)])
    import http.client as _hc
    try: cr, br = gk(SB.DeviceId("rogue", cert=str(rg / "d.crt"), key=str(rg / "d.key")), "POST", "/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}); rogue = ("HTTP", cr)
    except (OSError, _hc.HTTPException) as e: rogue = ("연결 오류", type(e).__name__)   # ssl.SSLError·ConnectionResetError·URLError 는 모두 OSError
    assert rogue[0] == "연결 오류", ("다른 CA 의 인증서가 TLS 에서 거절되지 않았다(HTTP 응답을 받았다)", rogue)
    # (3) 폐기·복구: 기기 c 의 일련번호를 목록에서 빼면 다음 요청부터 403, 다시 넣으면 회복한다(재시작 없음, 계약 F절: 요청마다 대조)
    C = dev_tok("e2e-c"); c, st_c = gk(C, "POST", "/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}); assert c == 200, ("등록된 기기 C 는 정상이어야 한다", c); _sid(c, st_c)
    ser = subprocess.run(["bash", "-c", 'source "$1/scripts/lib.sh" && source "$1/scripts/gateway-lib.sh" && gw_allowlist serials e2e-c', "x", str(ROOT)], capture_output=True, text=True, env={**os.environ, **env}, check=True).stdout.split()
    assert len(ser) == 1, "기기 c 의 일련번호가 하나가 아니다"
    kad("revoke-serial", "e2e-c", ser[0])
    cc, bc = gk(C, "POST", "/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}); _assert_denied("목록에서 일련번호를 뺀 기기 C", cc, bc)
    c, _ = gk(A, "POST", "/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}); assert c == 200, "다른 기기는 폐기의 영향을 받지 않는다"
    kad("register", "e2e-c", ser[0])
    cr2, _ = gk(C, "POST", "/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}); assert cr2 == 200, ("일련번호를 되돌리면 기기 C 가 회복해야 한다", cr2)
    rec("5d", "REAL", "기기 인증서(mTLS): 기기 A 가 만든 세션에 기기 B 의 상태·발화·종료는 404/403 이고 세션은 바뀌지 않았다, 기기 A 는 계속 정상, 인증서 없음·목록에 없는 인증서는 403 PERMISSION_DENIED(BoundaryError), 다른 CA 의 인증서는 TLS 에서 거절(연결 오류), 기기 C 의 일련번호를 목록에서 빼자 다음 요청이 403 이고 되돌리자 회복(게이트웨이 재시작 없음). 못 보는 것: 이미 열린 TLS 연결에서의 거부(새 연결로만 본다)")

def _validate_if_known(name, obj):
    """계약 v2.1.0 의 새 스키마(StaffCallRetryResult 등)는 설치된 boundary-contracts 가 v2.1.0 이상일 때만 있다. 없으면 필드 단언만 한다(BOUNDARY_TAG 를 올리기 전에도 구문·자체 시험이 돈다)."""
    try: bc.validator(name)
    except Exception: return False
    validate(name, obj); return True

@step('5n', repos=('survey-service', 'model-runtime', 'kiosk-frontend', 'boundary-contracts') + _GW, deps=('4',),
      why="STATE['pointers'] 를 읽는다(e2e_steps.py step5n 앞부분). 5n-reask 의 실효 되묻기 한도는 survey-service 가 /readyz reask_limit.effective(계약 v3.1.0)로 알려 주는 값만 읽는다(문항 세트 session_settings 로 계산하지 않는다: 구조 규칙 4). 5n-reask 는 가짜 A 의 reasks 설정(model-runtime 0.7.3 이후, test/fake-model/question_flow.json)으로 REASK 를 연속 유도한다. 위험 문구는 E2E 가 주입한 시험 규칙 파일(test/risk-rules.e2e.json)에서 읽고, 기기 e2e-a·e2e-b 토큰을 쓴다(5d 와 같은 gen-secrets.sh 구성). " + _P4)
def step5n():
    title("5n", "직원 호출 재알림·실패 기록·정지 사유 (계약 v2.1.0 PUBLIC_API G·H절, CR-H001·H002, 가짜 모델)")
    if "pointers" not in STATE: rec("5n", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    wait(lambda: _c2_ready()[0] == 200, 300, "survey-service 가 활성 릴리스를 적재(/readyz 200)", every=3)
    def tcall(tok, method, path, body=None):   # 지정한 토큰으로 게이트웨이 경유 호출: (상태, 본문, 소문자 헤더)
        code, b, hd = _c2_gw(method, path, body, token=tok)
        print(f"    호출 {method} {path} -> {code}", flush=True)   # 어느 호출이 어떤 코드를 받았는지 로그에 남긴다(단계 5n 첫 실행의 404 가 어느 호출인지 몰랐다)
        return code, b, hd
    def state_dev(tok, session=None):   # state_of 는 시험 기본 기기(e2e) 토큰이라 다른 기기가 만든 세션은 404 다(survey-service _device_denied). 세션을 만든 기기 토큰으로 조회한다
        for _ in range(8):
            time.sleep(0.7)   # 속도 제한 간격: 서버가 0.5초보다 잦은 상태 조회를 429 로 막는다
            c, r, _h = tcall(tok, "GET", f"/v1/sessions/{session or sid}/state")
            if c != 429: return c, r
        return c, r
    # (a) 위험 발화로 정지(단계 5f 의 방식: E2E 가 주입한 시험 규칙의 문구). 이 구성에는 직원 콘솔 구독자가 없어 전달은 DELIVERY_FAILED 로 끝나는 것이 정상이다(survey-service alerts.py 머리말). 구독자가 있으면 DELIVERED 일 수 있고 그래도 아래 호출은 OPEN 알림이 있으므로 성립한다
    sid = f"sess-{RID}-n"; phrase, _r = risk_phrase()
    A = dev_tok("e2e-a"); B = dev_tok("e2e-b")
    c, st = tcall(A, "POST", "/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS})[:2]; sid = _sid(c, st)
    c, rr, _h = tcall(A, "POST", f"/v1/sessions/{sid}/turns", {"session_id": sid, "kind": "UTTERANCE", "utterance": f"저는 {phrase} 있어요", "turn_id": "n-1"}); assert c == 200, (c, rr)
    fs = rr.get("turn_failure_signal") or {}; first_status = fs.get("staff_alert")
    assert first_status in ("DELIVERED", "DELIVERY_FAILED"), ("위험 발화인데 직원 알림 신호가 없다", rr)
    # (b) 정지 사유: /state 의 pause_reason 은 RISK (SessionState, 정지일 때만 의미)
    c, stt = state_dev(A); assert c == 200 and stt["state"] == "PAUSED_RISK", ("GET /state(기기 A)", c, stt)
    assert stt.get("pause_reason") == "RISK", ("위험 정지인데 /state 의 pause_reason 이 RISK 가 아니다(계약 v2.1.0 H절)", stt)
    _validate_if_known("SessionState", stt)
    # (c) 재알림: 응답 필드, 같은 turn_id 멱등, 간격 안의 다른 turn_id 는 429
    c, r1, _h = tcall(A, "POST", f"/v1/sessions/{sid}/staff-call/retry", {"turn_id": "n-retry-1"}); assert c == 200, ("재알림", c, str(r1)[:200])
    assert r1["alert_id"] and r1["staff_alert"] in ("DELIVERED", "DELIVERY_FAILED") and isinstance(r1["delivery_attempts"], int) and r1["delivery_attempts"] >= 2 and r1["retry_after_s"] > 0, ("StaffCallRetryResult 필드", r1)
    _validate_if_known("StaffCallRetryResult", r1)
    c, r1b, _h = tcall(A, "POST", f"/v1/sessions/{sid}/staff-call/retry", {"turn_id": "n-retry-1"}); assert c == 200 and r1b == r1, ("같은 turn_id 재전송이 같은 응답이 아니다(시도 횟수도 늘면 안 된다)", c, r1b, r1)
    c, r2, h2 = tcall(A, "POST", f"/v1/sessions/{sid}/staff-call/retry", {"turn_id": "n-retry-2"}); assert c == 429, ("간격(retry_after_s) 안의 새 turn_id 재알림이 429 가 아니다", c, str(r2)[:200])
    assert "retry-after" in h2, ("429 에 Retry-After 헤더가 없다", h2)
    # (d) 다른 기기·위조·직원 토큰은 거부된다
    cb, rb, _h = tcall(B, "POST", f"/v1/sessions/{sid}/staff-call/retry", {"turn_id": "n-retry-b"}); assert cb in (404, 403), ("다른 기기 토큰의 재알림이 허용됐다", cb, str(rb)[:100])
    cbr, _r, _h = tcall(B, "POST", f"/v1/sessions/{sid}/staff-call/report", {"outcome": "NOT_NOTIFIED", "turn_id": "n-rep-b"}); assert cbr in (404, 403), ("다른 기기 토큰의 실패 기록이 허용됐다", cbr)
    cf, _r, h_f = tcall("forged-" + "x" * 24, "POST", f"/v1/sessions/{sid}/staff-call/retry", {"turn_id": "n-retry-f"}); assert cf == 401 and h_f.get("www-authenticate", "").startswith("Bearer"), ("위조 토큰의 재알림은 401 + WWW-Authenticate: Bearer (계약 6절)", cf, h_f)
    cn, _r, h_n = tcall(None, "POST", f"/v1/sessions/{sid}/staff-call/retry", {"turn_id": "n-retry-f"}); assert cn == 401 and h_n.get("www-authenticate", "").startswith("Bearer"), ("토큰 없는 재알림은 401 + WWW-Authenticate: Bearer (계약 6절)", cn, h_n)
    cs = _c2_in("survey-service", "POST", f"/v1/sessions/{sid}/staff-call/retry", TOK("survey-api-staff"), {"turn_id": "n-retry-s"})[0]; assert cs == 403, ("직원 토큰으로 서비스에 직접 재알림이 403 이 아니다", cs)
    assert tcall(A, "POST", f"/v1/sessions/{sid}/staff-call/retry", {"turn_id": "n-retry-2"})[0] in (200, 429), "거부 시도 뒤 기기 A 의 호출이 깨졌다"
    # (e) 실패 기록: StaffAlert 에 manual_notice_* 가 남고 직원 알림 목록에서 보인다. 같은 turn_id 같은 outcome 은 멱등, 다른 outcome 은 409
    c, rep, _h = tcall(A, "POST", f"/v1/sessions/{sid}/staff-call/report", {"outcome": "STAFF_NOTIFIED_MANUALLY", "turn_id": "n-rep-1"}); assert c == 200, ("실패 기록", c, str(rep)[:200])
    assert rep["alert_id"] == r1["alert_id"] and rep.get("manual_notice_outcome") == "STAFF_NOTIFIED_MANUALLY" and rep.get("manual_notice_reported_at"), ("StaffAlert 에 manual_notice_* 가 없다", rep)
    _validate_if_known("StaffAlert", rep)
    c, rep2, _h = tcall(A, "POST", f"/v1/sessions/{sid}/staff-call/report", {"outcome": "STAFF_NOTIFIED_MANUALLY", "turn_id": "n-rep-1"}); assert c == 200 and rep2 == rep, ("같은 turn_id 실패 기록이 멱등이 아니다", c, rep2)
    c, _r, _h = tcall(A, "POST", f"/v1/sessions/{sid}/staff-call/report", {"outcome": "NOT_NOTIFIED", "turn_id": "n-rep-1"}); assert c == 409, ("같은 turn_id 에 다른 outcome 이 409 가 아니다", c)
    c, pg = _c2_staff("GET", "/v1/staff/alerts?status=OPEN"); assert c == 200, (c, pg); validate("StaffAlertPage", pg)
    mine = [x for x in pg["items"] if x["session_id"] == sid and x["alert_id"] == r1["alert_id"]]
    assert mine and mine[0].get("manual_notice_outcome") == "STAFF_NOTIFIED_MANUALLY" and mine[0].get("manual_notice_reported_at"), ("직원 알림 목록에 manual_notice_* 가 없다", mine)
    assert mine[0].get("delivery_attempts", 0) >= 2 and mine[0].get("last_delivery_status") in ("DELIVERED", "DELIVERY_FAILED"), ("StaffAlert 의 delivery_attempts·last_delivery_status", mine[0])
    assert mine[0].get("pause_reason") in (None, "RISK"), ("StaffAlert.pause_reason", mine[0])
    sv = staff_sv(sid); assert sv["status"] == "PAUSED_RISK", ("실패 기록은 세션을 풀지 않는다(직원이 개입으로 풀 때까지 PAUSED_RISK)", sv["status"])
    # (f) 직원이 풀어 알림이 OPEN 이 아니게 되면 재알림은 409 NO_OPEN_ALERT
    c, iv, _h = _c2_raw("POST", f"/v1/sessions/{sid}/intervention", {"session_id": sid, "decision": "RESUME", "turn_id": "n-iv-1"}, basic=_C2_STAFF); assert c == 200, (c, iv)
    c, nr, _h = tcall(A, "POST", f"/v1/sessions/{sid}/staff-call/retry", {"turn_id": "n-retry-3"})
    assert c == 409 and ((nr.get("error") or nr).get("details") or {}).get("reason") == "NO_OPEN_ALERT", ("OPEN 알림이 없을 때 409 NO_OPEN_ALERT 가 아니다", c, str(nr)[:200])
    c, st3 = state_dev(A); assert c == 200 and not st3.get("pause_reason"), ("정지가 풀렸는데 pause_reason 이 남았다(정지일 때만 의미)", st3)
    tcall(A, "POST", f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"})
    rec("5n", "REAL", f"위험 발화 정지(첫 전달 {first_status}) -> /state pause_reason=RISK -> staff-call/retry(필드·같은 turn_id 멱등·간격 안 새 turn_id 429+Retry-After) -> 다른 기기·위조·무토큰·직원 토큰 거부 -> staff-call/report(StaffAlert manual_notice_*, 멱등, 다른 outcome 409, 직원 알림 목록에 보임, 세션은 PAUSED_RISK 유지) -> 개입 뒤 재알림 409 NO_OPEN_ALERT")
    # (g) 되묻기 한도 정지(pause_reason=REASK_LIMIT, survey-service ADR-0020·0022): 가짜 A 의 reasks 설정(model-runtime 0.7.3 이후, test/fake-model/question_flow.json 의
    # '되묻기시험' -> REASK)으로 같은 세션에서 REASK 를 연속으로 유도한다. 한도(N)는 /readyz 의 reask_limit 에서 읽는다(지어내지 않는다)
    rz = _c2_ready()[1]; rl = rz.get("reask_limit")   # /readyz 의 reask_limit 은 {"active", "max_consecutive", "effective"(정수 또는 null)} 객체다(계약 v3.1.0)
    # 실효 한도는 survey-service 가 낸 계약 출력(SurveyReadyz.reask_limit.effective, 계약 v3.1.0)만 읽는다: 서비스의 계산 규칙(문항 세트 session_settings 와 서비스 한도의 최솟값)을 E2E 가 흉내 내지 않는다(구조 규칙 4)
    N = (rl or {}).get("effective")
    if not isinstance(N, int) or N < 1:
        rec("5n-reask", "BLOCKED", f"되묻기 실효 한도(reask_limit.effective)가 없거나 null 이다(/readyz reask_limit={rl!r}): 활성 릴리스가 없거나 한도가 꺼져 있다. SURVEY_MAX_CONSECUTIVE_REASK 를 1 이상으로 둔다"); return
    sid2 = f"sess-{RID}-n-reask"; utt = "되묻기시험 글쎄요"; FAKE = "(가짜 응답)"
    c, st = tcall(A, "POST", "/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS})[:2]; sid2 = _sid(c, st)
    for i in range(1, N + 1):   # 한도까지는 정상 진행: 되묻는다(세션은 진행 중, 직원 알림 없음, 문장은 모델 응답)
        c, rr = tcall(A, "POST", f"/v1/sessions/{sid2}/turns", {"session_id": sid2, "kind": "UTTERANCE", "utterance": utt, "turn_id": f"nr-{i}"})[:2]
        assert c == 200 and not rr.get("turn_failure_signal") and FAKE in str(rr.get("response_text")), (f"{i}번째 되묻기 턴이 정상 진행이 아니다", c, str(rr)[:200])
    c, s_ = state_dev(A, sid2); assert c == 200 and s_["state"] == "ACTIVE" and not s_.get("pause_reason"), (f"한도({N}) 전에 정지했다", c, s_)
    sv = staff_sv(sid2)
    said = [t for t in sv["turns"] if t["utterance"]]; assert [t["action"] for t in said] == ["REASK"] * N, ("턴 기록의 action", [(t["turn_id"], t["action"]) for t in said])
    c, pg0 = _c2_staff("GET", "/v1/staff/alerts?status=OPEN"); assert c == 200 and not [x for x in pg0["items"] if x["session_id"] == sid2], "한도 전에 직원 알림이 생겼다"
    # N+1 번째: 되묻는 대신 직원 호출 경로(PAUSED_RISK + CALL_STAFF 알림 + 고정 문장 CALL_STAFF, 모델 문장이 아니다)
    c, rl = tcall(A, "POST", f"/v1/sessions/{sid2}/turns", {"session_id": sid2, "kind": "UTTERANCE", "utterance": utt, "turn_id": f"nr-{N + 1}"})[:2]
    assert c == 200 and rl.get("response_text") and FAKE not in str(rl.get("response_text")), (f"{N + 1}번째 턴 응답이 문항 세트 고정 문장이 아니다", c, str(rl)[:200])
    fixed_text = rl["response_text"]
    c, s_ = state_dev(A, sid2); assert c == 200 and s_["state"] == "PAUSED_RISK", (c, s_)
    assert s_.get("pause_reason") == "REASK_LIMIT", ("/state 의 pause_reason 이 REASK_LIMIT 가 아니다(계약 v2.1.0 H절)", s_); _validate_if_known("SessionState", s_)
    c, pg = _c2_staff("GET", "/v1/staff/alerts?status=OPEN"); assert c == 200, (c, pg); validate("StaffAlertPage", pg)
    al = [x for x in pg["items"] if x["session_id"] == sid2]
    assert len(al) == 1 and al[0]["kind"] == "CALL_STAFF" and al[0].get("pause_reason") == "REASK_LIMIT", ("CALL_STAFF 직원 알림(pause_reason REASK_LIMIT)이 하나 생기지 않았다", al)
    assert staff_sv(sid2)["status"] == "PAUSED_RISK"
    # 직원 재개 -> 정상: 정지가 풀리고 pause_reason 이 사라지며, 되묻기 문구가 없는 발화는 다시 모델 응답으로 진행한다(연속 횟수는 다시 센다)
    c, iv, _h = _c2_raw("POST", f"/v1/sessions/{sid2}/intervention", {"session_id": sid2, "decision": "RESUME", "turn_id": "nr-iv-1"}, basic=_C2_STAFF); assert c == 200, (c, iv)
    c, s_ = state_dev(A, sid2); assert c == 200 and s_["state"] == "ACTIVE" and not s_.get("pause_reason"), ("재개 뒤 상태", c, s_)
    c, rn = tcall(A, "POST", f"/v1/sessions/{sid2}/turns", {"session_id": sid2, "kind": "UTTERANCE", "utterance": "네 있어요", "turn_id": "nr-after"})[:2]
    assert c == 200 and not rn.get("turn_failure_signal") and FAKE in str(rn.get("response_text")), ("재개 뒤 정상 진행이 아니다", c, str(rn)[:200])
    tcall(A, "POST", f"/v1/sessions/{sid2}/end", {"session_id": sid2, "kind": "SESSION_END"})
    rec("5n-reask", "REAL", f"되묻기 한도 정지(가짜 A reasks '되묻기시험'->REASK, 실효 한도 {N} = min(/readyz max_consecutive, 문항 세트 ask/confirm/unrecognized 한도)): 같은 세션에서 REASK {N}번 연속은 정상 진행(IN_PROGRESS, 알림 없음, 모델 문장, 턴 기록 action 전부 REASK) -> {N + 1}번째 턴에 PAUSED_RISK + /state pause_reason=REASK_LIMIT + CALL_STAFF 직원 알림 1건(pause_reason REASK_LIMIT) + 문항 세트 고정 문장(모델 문장이 아님; 문장 내용 자체는 문항 세트 저작이라 비교하지 않았다) -> 직원 RESUME 뒤 IN_PROGRESS·pause_reason 없음·다음 발화는 정상 진행")

@step('5r', repos=('survey-service', 'kiosk-frontend', 'admin-console') + _GW, deps=('4',),
      why="STATE['pointers'] 를 읽는다. " + _P4)
def step5r():
    title("5r", "환자 세션 -> 외부 위험 신호 -> 직원 확인·개입 -> 결과 조회 (D85 A~F절, 가짜 모델)")
    if "pointers" not in STATE: rec("5r", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    wait(lambda: _c2_ready()[0] == 200, 300, "survey-service 가 활성 릴리스를 적재(/readyz 200)", every=3)   # 단계 5 없이 단독으로 돌려도 되게
    sid = f"sess-{RID}-risk"; subj = f"e2e-subject-{RID}"; utter = "뇌졸중은 없고 약도 안 먹어요"
    RES = lambda: TOK("survey-result-reader"); RSK = lambda: TOK("survey-risk-source")   # 내부 호출용 토큰(게이트웨이에 열지 않는다)
    # 위험 신호 감지기와 병원의 결과 조회는 운영에서 제품 네트워크 안의 호출자다(게이트웨이에 열지 않는다, D85): survey-service 컨테이너 안에서 그 API 를 부른다
    svc_call = lambda m, pth, tk, bd=None: (lambda r: (r[0], _c2_dec(r[1])))(_c2_in("survey-service", m, pth, tk, bd))
    # (A) 키오스크 기기(mTLS 기기 인증서)로 세션 시작(subject_ref 는 세션 시작 요청의 칸), 발화 한 턴
    c, st = _c2_kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS, "subject_ref": subj}); sid = _sid(c, st); validate_survey("FrontendInput", st)
    c, tr = _c2_turn(sid, "rk-1", utter); assert c == 200, (c, tr)
    # (D) 위험 신호: risk-source 토큰으로 서비스에 직접. 맞는 토큰이라도 다른 역할이면 403, 게이트웨이에는 열려 있지 않다
    sig = {"signal_id": f"sig-{RID}-1", "source": "e2e-detector", "code": "TEST_RISK", "severity": "RISK"}
    for lab, tk in (("kiosk", _c2_kdev()), ("staff", TOK("survey-api-staff")), ("result-reader", RES())):
        assert svc_call("POST", f"/v1/sessions/{sid}/risk-signals", tk, sig)[0] == 403, f"{lab} 토큰(맞는 토큰, 다른 역할)으로 위험 신호 입력이 열림"
    assert _c2_gw("POST", f"/v1/sessions/{sid}/risk-signals", sig, token=_c2_kdev())[0] in (403, 404), "위험 신호 입력이 게이트웨이를 통과함"
    c, r1 = svc_call("POST", f"/v1/sessions/{sid}/risk-signals", RSK(), sig); assert c == 201, (c, r1)
    assert r1["session_status"] == "PAUSED_RISK" and r1["alert_id"], r1
    c, r2 = svc_call("POST", f"/v1/sessions/{sid}/risk-signals", RSK(), sig); assert c == 200 and r2["alert_id"] == r1["alert_id"], ("같은 signal_id 재전송이 멱등이 아님", c, r2)
    # 직원 알림이 목록에 나온다(게이트웨이 경유, 직원 계정)
    c, pg = _c2_staff("GET", "/v1/staff/alerts?status=OPEN"); assert c == 200, (c, pg); validate("StaffAlertPage", pg)
    mine = [x for x in pg["items"] if x["session_id"] == sid and x["alert_id"] == r1["alert_id"]]; assert mine and mine[0]["status"] == "OPEN", ("위험 신호가 알림 목록에 없다", pg["items"][:2])
    assert mine[0]["kind"] == "RISK_STOP", mine[0]   # 목록(StaffAlert)과 세션 조회(StaffSessionView.alerts[])의 kind 는 같은 이름 RISK_STOP(계약 PUBLIC_API.md; survey-service CR-019). 신호 severity 의 RISK, pause_reason 의 RISK 와는 다른 필드
    # (C) 직원 세션 조회: 대화 기록·값·subject_ref
    c, sv = _c2_staff("GET", f"/v1/staff/sessions/{sid}"); assert c == 200, (c, sv); validate_survey("StaffSessionView", sv)
    assert sv["status"] == "PAUSED_RISK" and sv["subject_ref"] == subj and sv["turns"], (sv["status"], sv.get("subject_ref"), len(sv.get("turns", [])))
    va = [al for al in sv["alerts"] if al["alert_id"] == r1["alert_id"]]; assert va, "직원 세션 조회의 alerts 에 이 알림이 없다"
    assert va[0]["kind"] == "RISK_STOP" and va[0]["rule_id"] == "e2e-detector:TEST_RISK", va[0]
    assert _c2_raw("GET", f"/v1/staff/sessions/{sid}", basic=_C2_OPERATOR)[0] == 403, "operator 계정이 직원 세션 조회를 부를 수 있다"
    # (E) 직원 개입(RESUME): 행위자는 게이트웨이가 붙인 헤더의 계정, 본문의 staff_id 는 무시
    # 본문은 InterventionDecision(+turn_id 봉투)뿐이다(additionalProperties false: staff_id 를 실으면 400). 행위자는 헤더가 정본이므로 위조 X-Openit-User 를 실어도 인증 계정이 기록되어야 한다
    c, iv, _ = _c2_raw("POST", f"/v1/sessions/{sid}/intervention", {"session_id": sid, "decision": "RESUME", "turn_id": "iv-1"}, basic=_C2_STAFF, headers={"X-Openit-User": "spoofed-staff"}); assert c == 200, (c, iv)
    c, sv2 = _c2_staff("GET", f"/v1/staff/sessions/{sid}"); assert c == 200, (c, sv2); validate_survey("StaffSessionView", sv2)
    res = [al.get("resolved_by") for al in sv2["alerts"] if al["alert_id"] == r1["alert_id"]]
    assert res == [_C2_STAFF], f"alerts[].resolved_by 가 인증된 직원 ID가 아니다: {res}"
    assert sv2["status"] == "IN_PROGRESS", sv2["status"]
    c, en = _c2_kiosk(f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"}); assert c == 200, (c, en)
    # (B) 결과 조회: result-reader 토큰. subject_ref·상태·answers 는 있고 환자 발화 원문은 없다
    c, rs = svc_call("GET", f"/v1/results/{sid}", RES()); assert c == 200, (c, rs); validate_survey("SessionResult", rs)
    assert rs["subject_ref"] == subj and rs["status"].startswith("ENDED") and isinstance(rs["answers"], list), rs
    assert utter not in json.dumps(rs, ensure_ascii=False), "결과 조회 응답에 환자 발화 원문이 있다"
    c, lst = svc_call("GET", f"/v1/results?subject_ref={subj}", RES()); assert c == 200 and any(x["session_id"] == sid for x in lst["items"]), (c, str(lst)[:150])
    for lab, tk in (("kiosk", _c2_kdev()), ("staff", TOK("survey-api-staff")), ("risk-source", RSK())):
        assert svc_call("GET", f"/v1/results/{sid}", tk)[0] == 403, f"{lab} 토큰(맞는 토큰, 다른 역할)으로 결과 조회가 열림"
    # (G) 의사 결과 보기(U83, 3.2.0 PUBLIC_API B절): 게이트웨이는 clinician 역할 계정에만 결과 읽기·확인 표시를 연다. 다른 역할 403, 무인증 401
    for pth in (f"/v1/results/{sid}", f"/v1/results?subject_ref={subj}"):
        assert _c2_raw("GET", pth, basic=_C2_STAFF)[0] == 403 and _c2_raw("GET", pth, basic=_C2_OPERATOR)[0] == 403, f"결과 조회 {pth} 가 clinician 아닌 역할에 열려 있다"
        assert _c2_raw("GET", pth)[0] == 401, f"결과 조회 {pth} 가 인증 없이 열려 있다"
    c, rs_c, _ = _c2_raw("GET", f"/v1/results/{sid}", basic=_C2_CLINICIAN); assert c == 200, (c, str(rs_c)[:150]); validate_survey("SessionResult", rs_c)
    assert rs_c["session_id"] == sid and not rs_c.get("acknowledged_by"), rs_c.get("acknowledged_by")
    c, lst_c, _ = _c2_raw("GET", f"/v1/results?status={rs_c['status']}", basic=_C2_CLINICIAN); assert c == 200 and any(x["session_id"] == sid for x in lst_c["items"]), (c, str(lst_c)[:150])
    c, ak1, _ = _c2_raw("POST", f"/v1/results/{sid}/ack", {}, basic=_C2_CLINICIAN, headers={"X-Openit-User": "spoofed-doctor"}); assert c == 200, (c, str(ak1)[:150]); validate_survey("SessionResult", ak1)
    assert ak1.get("acknowledged_by") == _C2_CLINICIAN and ak1.get("acknowledged_at"), ("확인 표시가 인증 계정으로 기록되지 않았다", ak1.get("acknowledged_by"))
    c, ak2, _ = _c2_raw("POST", f"/v1/results/{sid}/ack", {}, basic=_C2_CLINICIAN); assert c == 200 and ak2.get("acknowledged_at") == ak1["acknowledged_at"], ("확인 표시 재호출이 멱등이 아니다", c)
    assert _c2_raw("POST", f"/v1/results/{sid}/ack", {}, basic=_C2_STAFF)[0] == 403
    # 접근 기록: 읽는 공개 경로가 없다(DB 를 열지 않는다). 기록을 못 남기면 데이터를 주지 않는 설계(fail-closed)라 위 조회 성공이 기록 쓰기 성공을 뜻한다. /readyz 에 접근 기록 항목이 있으면 함께 본다
    c, rz = _c2_ready(); acc = {k: v for k, v in (rz or {}).items() if "access" in k.lower()}
    rec("5r", "REAL", f"의사 결과 보기(U83): clinician 계정으로 GET /v1/results/{{id}}·목록 200, POST ack 200 acknowledged_by=인증 계정(위조 헤더 무시)·재호출 멱등, staff·operator 403, 무인증 401. 세션 시작(기기 토큰, subject_ref) -> 발화 -> POST /v1/sessions/{{id}}/risk-signals(risk-source 토큰, 서비스에 직접: 201 PAUSED_RISK, 재전송 200 같은 alert_id, 다른 역할 토큰·게이트웨이 경유는 거부) -> 직원 알림 목록(RISK_STOP, OPEN) -> GET /v1/staff/sessions/{{id}}(직원 계정, 게이트웨이 경유, StaffSessionView 스키마, subject_ref·turns, alerts[].rule_id e2e-detector:TEST_RISK) -> 개입 RESUME(위조 X-Openit-User 무시, alerts[].resolved_by={_C2_STAFF}) -> GET /v1/results/{{id}}·/v1/results?subject_ref(result-reader 토큰, SessionResult 스키마, 발화 원문 없음, 게이트웨이에는 404). 접근 기록: 읽는 경로가 없어 간접 확인(조회 성공 = 기록 성공, /readyz 접근 항목 {sorted(acc) or '없음'}). SSE 수신은 확인하지 않았다(목록으로 확인).")

@step('5s', repos=('survey-service', 'model-runtime') + _GW, deps=('4',),
      why="step5s 는 STATE['containers_before_swap'],['releases'](step4)를 읽는다(e2e_steps.py step5s 앞부분)",
      also={'release-gate': '포인터 교체(활성화) 경계', 'model-lab': '게시된 어댑터가 model-serving에 적재'})
def step5s():
    title("5s", "어댑터 교체(포인터 1 -> 2)에서 다른 서비스는 그대로이고 새 릴리스가 LOADED 이다")
    before = STATE.get("containers_before_swap")
    if not before or "releases" not in STATE: rec("5s", "BLOCKED", "포인터 교체 전 스냅샷이 없다(단계 4)"); return
    after = container_ids()
    EA.check_unchanged({k: tuple(v) for k, v in before.items()}, after, SWAP_SERVICES)
    new = STATE["releases"]["2"]
    c, st, _h = _c2_ms_call(f"/v1/releases/{new}", None, INF_TOK(), "GET"); assert c == 200, (c, st); st = json.loads(st)
    EA.check_release_loaded(st, new)
    rec("5s", "REAL", f"포인터 교체(활성화 2회째) 전후로 {', '.join(SWAP_SERVICES)} 컨테이너의 ID 와 StartedAt 이 같다(docker inspect 의 두 필드만 읽음). model-serving 의 /v1/releases/{new} 가 LOADED(오류 없음). 변경된 것은 model-serving 의 적재 릴리스뿐이다. 어댑터는 시험용 가짜(TEST-SUB)")

RISK_RULES = ROOT / "test/risk-rules.e2e.json"   # deploy 가 정한 시험용 규칙(계약 SurveyRiskRulesFile). survey-service 에는 test/compose.risk-rules.yaml 이 SURVEY_RISK_RULES_FILE 로 연결한다

def risk_phrase():
    """E2E 가 survey-service 에 넣은 시험용 규칙 파일에서 위험 문구를 읽는다(영역 내부 파일을 읽지 않는다, U48). (문구, 규칙 id 목록)"""
    doc = json.loads(RISK_RULES.read_text(encoding="utf-8"))
    try: v = bc.validator("SurveyRiskRulesFile")
    except Exception: v = None   # 계약 2.8.0 이전 패키지에는 스키마가 없다: 검증하지 못했음을 알린다(통과로 세지 않는다)
    if v is None: print("  !! SurveyRiskRulesFile 스키마가 설치된 계약 패키지에 없어 시험 규칙 파일을 검증하지 못했다(계약 2.8.0 이상 필요) !!")
    else: validate("SurveyRiskRulesFile", doc)
    rule = doc["rules"][0]; return rule["match"]["any_of"][0]["contains"], [r["id"] for r in doc["rules"]]

@step('5f', repos=('survey-service', 'ops-feedback', 'kiosk-frontend') + _GW, deps=('4',),
      why="STATE['pointers'] 를 읽는다. " + _P4,
      also={'admin-console': 'gateway 경유 정적 화면 제공과 접근 구분'})
def step5f():
    title("5f", "프론트 이미지와 게이트웨이: 정적 화면, 공개 API 호출 순서, 직원 경로 권한 분리, 직원 알림 입력원 없음 (kiosk-frontend)")
    if "pointers" not in STATE: rec("5f", "BLOCKED", "활성 릴리스가 없다(단계 4)"); return
    # (a) 정적 화면
    c, html, _ = _c2_text("/"); assert c == 200 and "문진" in html, (c, html[:100])
    c, _b, hd = _c2_text("/staff/"); assert c == 302 and hd.get("location", "").startswith("/oauth2/start"), ("직원 콘솔이 인증 없이 열려 있다(화면 경로는 로그인으로 302)", c, hd.get("location"))
    c, _b, hd = _c2_gw("GET", "/staff/", headers={"Cookie": "_openit_session=forged"}); assert c == 302, ("위조한 세션 쿠키는 인증이 아니다(로그인으로 302)", c)
    c, stf, _ = _c2_text("/staff/", _C2_STAFF); assert c == 200 and "직원 콘솔" in stf, (c, stf[:100])
    c, sw, h = _c2_text("/staff/sw.js", _C2_STAFF); assert c == 200, c
    assert _c2_text("/healthz")[0] == 200
    c, _t, hd = _c2_text("/"); assert "default-src 'self'" in " ".join(f"{v}" for k, v in hd.items() if k.lower() == "content-security-policy"), "CSP 헤더가 없다"
    assert _c2_text("/v1/turns")[0] == 404
    rec("5a", "REAL", "게이트웨이 경유 kiosk-frontend: /(키오스크 화면) 200, /staff/ 는 인증 없이·위조한 세션 쿠키로 로그인 302, OIDC 로그인 세션으로 200, /staff/sw.js 200, CSP 헤더, /v1 기타 경로 404")
    # (b) 브라우저가 부르는 순서를 HTTP로(토큰 없이 같은 출처): 세션 시작, 발화 2턴, state 조회, 종료
    sf = f"sess-{RID}-fe"
    c, st = _c2_kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}); sf = _sid(c, st); validate_survey("FrontendInput", st)
    for i, text in enumerate(("뇌졸중은 없고 약도 안 먹어요", "약도 안 먹어요"), 1):
        c, tr = _c2_turn(sf, f"fe-{i}", text); assert c == 200, (c, tr); validate_survey("FrontendInput", tr)
    c, state = _c2_state(sf); assert c == 200, (c, state); validate("SessionState", state)
    assert state["state"] == "ACTIVE", state
    c, en = _c2_kiosk(f"/v1/sessions/{sf}/end", {"session_id": sf, "kind": "SESSION_END"}); assert c == 200, (c, en)
    rec("5b", "REAL", "프론트의 공개 API 호출 순서가 게이트웨이(같은 출처, 토큰 없이)를 거쳐 실제 survey-service에 통과: 세션 시작 -> 발화 2턴 -> state(SessionState 스키마, ACTIVE) -> 종료")
    # (c) 직원 경로 권한 분리
    c1 = _c2_gw("GET", "/v1/staff/alerts")[0]; assert c1 == 401, ("인증 없는 직원 API는 401 (계약 6절: /v1/* 는 401 + Bearer 안내, 화면은 로그인 302)", c1)
    c2 = _c2_in("survey-service", "GET", "/v1/staff/alerts", _c2_kdev())[0]; assert c2 == 403, f"키오스크 토큰으로 직원 API가 열림 {c2}"
    c3 = _c2_gw("GET", "/v1/staff/alerts", token=TOK("survey-api-kiosk"))[0]; assert c3 == 401, ("Bearer 는 사람 계정 경로의 자격이 아니다: 401 (계약 6절)", c3)   # 클라이언트가 보낸 Authorization은 게이트웨이가 바꾸지 못한 채 인증 없이 거부된다
    c, pg = _c2_staff("GET", "/v1/staff/alerts?status=OPEN"); assert c == 200, (c, pg); validate("StaffAlertPage", pg)
    rec("5c", "REAL", f"권한 분리: 인증 없는 키오스크 쪽 호출은 게이트웨이에서 {c1}(직원 API는 로그인 필요), survey에 키오스크 토큰으로 직접 부르면 403, 기본 인증 뒤에는 staff 토큰이 붙어 목록 200(StaffAlertPage 스키마). 인증 없는 호출이 403이 아니라 401인 것은 브라우저가 인증 창을 띄우게 하려는 선택이다")
    # (d) 위험 감지: 모든 발화 턴의 원문에 규칙을 먼저 적용한다(D88 U1·U2). 규칙은 E2E 가 SURVEY_RISK_RULES_FILE 로 넣은 시험용 파일(계약 SurveyRiskRulesFile)이다. 알림은 모델 추출·쓰기 확정과 무관하게 먼저 나간다
    # (옛 검사 '임시 기본 목록(PROVISIONAL_DEFAULT) 켜짐'은 규칙 파일을 주입하면 성립하지 않아 뺐다. /readyz 의 source·provisional 값은 규칙 파일일 때의 모양을 deploy 가 알지 못해 단정하지 않는다)
    c, rz = _c2_ready(); sas = rz.get("staff_alert_source") or {}
    phrase, rule_ids = risk_phrase()
    assert sas.get("active") is True and sas.get("rule_count") == len(rule_ids), f"/readyz 의 staff_alert_source 가 '켜짐, 규칙 {len(rule_ids)}개'가 아니다: {sas}"
    s0 = _sid(*_c2_kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}))
    c, ok_ = _c2_turn(s0, "rk0-1", "네 있어요"); assert c == 200 and not ok_.get("turn_failure_signal"), ("위험 문구가 없는 발화는 정상 진행해야 한다", c, ok_)
    c, stn = _c2_state(s0); validate("SessionState", stn); assert stn["state"] == "ACTIVE", ("위험 문구가 없는데 세션이 멈췄다", stn)
    c, pg0 = _c2_staff("GET", "/v1/staff/alerts?status=OPEN"); assert not [x for x in pg0["items"] if x["session_id"] == s0], "위험 문구가 없는데 알림이 있다"
    vals_before = staff_sv(s0)["values"]
    risk_text = f"저는 {phrase} 있어요"   # E2E 가 주입한 시험 규칙 파일의 위험 문구로 만든 시험 문장
    c, rr = _c2_turn(s0, "rk0-2", risk_text); assert c == 200, (c, rr); validate_survey("FrontendInput", rr)
    fs = rr.get("turn_failure_signal") or {}
    assert fs.get("staff_alert") in ("DELIVERED", "DELIVERY_FAILED"), ("위험 발화인데 직원 알림 신호가 없다(키오스크가 대기/직원 호출 화면으로 갈 신호)", rr)
    c, stn = _c2_state(s0); assert stn["state"] == "PAUSED_RISK" or stn.get("status") == "PAUSED_RISK" or "PAUSED" in json.dumps(stn), ("세션이 위험 정지가 아니다", stn)
    c, pg1 = _c2_staff("GET", "/v1/staff/alerts?status=OPEN"); validate("StaffAlertPage", pg1)
    mine = [x for x in pg1["items"] if x["session_id"] == s0]; assert mine, "위험 발화인데 직원 알림 목록(OPEN)에 이 세션의 알림이 없다"
    sv0 = staff_sv(s0); assert sv0["status"] == "PAUSED_RISK" and sv0["values"] == vals_before, ("위험 정지 턴의 답이 저장됐거나 상태가 다르다", sv0["status"], sv0["values"], vals_before)
    hits = (_c2_ready()[1].get("staff_alert_source") or {}).get("hits_by_rule") or {}; assert sum(hits.values()) >= 1, ("/readyz hits_by_rule 에 적중이 없다", hits)
    _c2_kiosk(f"/v1/sessions/{s0}/end", {"session_id": s0, "kind": "SESSION_END"})
    rec("5k", "REAL", f"위험 감지 켜짐(D88 U1·U2): /readyz staff_alert_source active=true, 규칙 {sas['rule_count']}개(E2E 가 SURVEY_RISK_RULES_FILE 로 넣은 시험 규칙, 계약 SurveyRiskRulesFile). 위험 문구가 없는 발화는 정상 진행(ACTIVE, 알림 없음). 시험 규칙의 문구('{phrase}')가 든 발화는 turn_failure_signal.staff_alert={fs.get('staff_alert')}, 세션 PAUSED_RISK, 직원 알림 목록(OPEN)에 나타남, 답은 저장되지 않음, /readyz hits_by_rule 적중 {sum(hits.values())}. 거짓 알림 가능성과 임상 검토 전이라는 한계는 survey-service 문서의 것이다")
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
         "session_id": f"s-{RID}", "turn_id": f"t-{RID}-{n}", "sent_at": "2026-10-15T00:00:00Z", "trace": t,
         "question_set_id": QS}   # 3.3.0: 릴리스가 문진표 여럿이면 어느 문진표의 턴인지 봉투가 말해야 사례에 question_set 이 붙는다(없으면 NO_QUESTION_SET 로 신호에서 빠진다, 4차 E2E 단계 7)
    validate("TraceEnvelope", e); validate_survey("TurnTrace", t); return e

# ---- 단계 6 이후의 제품 접근 도우미 (wo-444). 드라이버가 제품에 닿는 길은 e2e_sandbox(SB)의 셋뿐이다:
#   (a) 게이트웨이(사람 계정·기기·기계 토큰), (b) 제품 네트워크 안(compose exec/run), (c) 별도 호스트의 추론 서버. 내부 서비스의 호스트 포트는 없다.
import e2e_sandbox as SB
_C3_ACCT = {"approver": "trainer-e2e", "operator": "operator-e2e", "reviewer": "reviewer-e2e", "author": "author-e2e", "clinical": "clinical-e2e", "staff": "staff-e2e"}   # Keycloak 시험 사용자: test/gateway-oidc/accounts.test.conf 를 scripts/idp-test-users.sh 가 만든다 의 시험 계정(역할 이름 -> 계정 ID)
_C3_SVC = {"qa": "question-authoring", "gate": "release-gate", "ops": "ops-feedback", "survey": "survey-service"}   # 단계가 쓰는 짧은 이름 -> compose 서비스

def _c3_tok(name):   # 시험 비밀 폴더의 토큰 파일(값은 출력하지 않는다, D84)
    return _tokpath(name).read_text().strip()

def _c3_gw(method, path, role=None, body=None, headers=None, timeout=30):
    """게이트웨이 경유 한 요청(사람 역할 계정 = OIDC 로그인 세션 쿠키). (상태, JSON 또는 문자열 본문, 소문자 헤더). role=None 이면 인증 없이."""
    st, h, raw = SB.gw_request(method, path, account=_C3_ACCT[role] if role else None, json=body, headers=headers, timeout=timeout)
    try: j = json.loads(raw) if raw else None
    except ValueError: j = raw.decode(errors="replace")
    return st, j, h

def _c3_gwc(cls, role):   # 계약 클라이언트를 게이트웨이 주소·사람 계정으로(스키마 검증은 클라이언트가 한다)
    return SB.gw_client(cls, account=_C3_ACCT[role])

_C3_PRE = '''import json, os, sys, time, urllib.request, urllib.error
V = json.loads(%s)
def _tokfile(env): return open(os.environ[env]).read().strip()
def _list(env):   # 서버가 받는 목록 값 "역할=토큰,..." (compose 가 마운트한 파일, 값은 출력하지 않는다)
    return dict(i.partition("=")[::2] for i in open(os.environ[env]).read().strip().split(","))
def call(method, url, token=None, body=None, headers=None, raw=None, ctype="application/json", timeout=30, rawout=False):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    if token: req.add_header("Authorization", "Bearer " + token)
    if data is not None: req.add_header("Content-Type", ctype)
    for k, v in (headers or {}).items(): req.add_header(k, v)
    try:
        r = urllib.request.urlopen(req, timeout=timeout); st, b, h = r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        st, b, h = e.code, e.read(), e.headers
    if not rawout:
        try: b = json.loads(b or b"null")
        except ValueError: b = b.decode(errors="replace")
    return st, b, h.get("WWW-Authenticate")
R = None
'''
def _c3_code(snippet, v):   # 컨테이너 안에서 돌릴 코드: 도우미 머리말 + 변수 V + 조각. 조각은 R 에 결과(JSON 직렬화 가능)를 둔다
    return (_C3_PRE % repr(json.dumps(v, ensure_ascii=False))) + snippet + "\nprint(json.dumps(R, ensure_ascii=False))\n"

def _c3_py(service, snippet, timeout=60, **v):
    """제품 컨테이너 안에서 파이썬 조각을 돌리고 R 을 돌려준다(그 서비스가 가진 토큰 파일·네트워크로 이웃을 부른다: 운영에서 그 일을 하는 주체가 컨테이너 안에 있을 때)."""
    out = SB.exec_py(service, _c3_code(snippet, v), timeout=timeout)
    return json.loads(out.strip().splitlines()[-1])

def _c3_job(job, args=(), timeout=300, **v):
    """제품의 잡 컨테이너를 한 번 실행한다. args 가 있으면 명령을 덮어쓴다. (종료 코드, 표준 출력, 표준 오류). 시간 초과는 종료 코드 124."""
    try: r = SB.run_job(job, list(args), timeout=timeout)
    except subprocess.TimeoutExpired: return 124, "", f"{job} 시간 초과({timeout}s)"
    return r.returncode, r.stdout or "", r.stderr or ""

def _c3_job_py(job, snippet, timeout=120, **v):   # 잡 이미지(그 영역의 토큰·네트워크)에서 파이썬 조각을 돌린다. compose run 은 stdin 을 쓰지 않으므로 -c 로 넘긴다(코드에 비밀 없음)
    rc, out, err = _c3_job(job, ["python", "-c", _c3_code(snippet, v)], timeout)
    assert rc == 0, f"{job} 안의 조각이 실패({rc}): {(err or out)[-400:]}"
    return json.loads(out.strip().splitlines()[-1])

def _c3_ready(k):
    """서비스 k(짧은 이름) 컨테이너 안에서 본 /readyz 상태 코드. 실행에 실패하면 0."""
    try: return SB.readyz(_C3_SVC[k])[0]
    except Exception: return 0

def _c3_probe(k, path):
    """컨테이너 안에서 GET 127.0.0.1:8080<path>: (상태 코드, 본문, 걸린 초). 걸린 초는 컨테이너 안에서 잰다(docker exec 시작 시간이 섞이지 않게)."""
    r = _c3_py(_C3_SVC[k], '''
t = time.time()
try:
    r = urllib.request.urlopen("@SELF@" + V["path"], timeout=10); st, b = r.status, r.read()
except urllib.error.HTTPError as e: st, b = e.code, e.read()
except Exception as e: st, b = 0, type(e).__name__.encode()
try: b = json.loads(b)
except ValueError: b = b.decode(errors="replace")
R = [st, b, time.time() - t]''', path=path)
    return r[0], r[1], r[2]

def _c3_healthz(k): return _c3_probe(k, "/healthz")[0]

def _c3_survey_ready(): return SB.readyz("survey-service")   # (상태, 본문)

def _c3_gate_read(path):
    """release-gate 의 읽기 면(I4)을 survey-service 컨테이너 안에서 읽는다(survey-service 가 쓰는 읽기 토큰 그대로: 운영에서 릴리스를 읽는 주체). (상태, JSON)."""
    r = _c3_py("survey-service", '''
st, b, _ = call("GET", "https://release-gate" + V["path"], _tokfile("SURVEY_RELEASE_READER_TOKEN_FILE"))
R = [st, b]''', path=path)
    return r[0], r[1]

def _c3_decisions_for(subj):
    q = urllib.parse.urlencode({f"{k}_{f}": (subj[k2][0] if k2 == "question_sets" else subj[k2])[f] for k, k2 in (("question_set", "question_sets"), ("lora_a", "lora_a"), ("lora_b", "lora_b")) for f in ("id", "version")} | {"limit": "100"})
    c, b = _c3_gate_read("/v1/decisions?" + q); assert c == 200, ("판정 조회", c, str(b)[:200])
    return b["items"]

def _c3_approver_hash(sid):   # 승인 화면이 하는 대로: review-report 응답 머리글 X-Openit-Report-Hash 를 그대로 쓴다
    c, b, h = _c3_gw("GET", f"/v1/submissions/{sid}/review-report", "approver")
    assert c == 200 and (h.get("x-openit-report-hash") or "").startswith("sha256:"), ("review-report 에 X-Openit-Report-Hash 가 없다", c, h)
    return h["x-openit-report-hash"]

_C3_CODE_OF_STATUS = {400: "INVALID_RECORD", 401: "PERMISSION_DENIED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND", 409: "CONFLICT"}
def _c3_approve(role, sid, decision, *, reason=None, report_hash=None):
    """승인 결정(POST /v1/approvals)을 사람 계정으로 게이트웨이에 보낸다. 행위자는 게이트웨이가 붙인 계정 ID 다. 실패하면 BoundaryError(code)."""
    body = {"submission_id": sid, "decision": decision, "approver_role": "release-approver", "report_hash": report_hash or _c3_approver_hash(sid)}
    if reason is not None: body["reason"] = reason
    validate("ApprovalRequest", body)
    c, j, _ = _c3_gw("POST", "/v1/approvals", role, body)
    if c in (200, 201): return j.get("approval", j) if isinstance(j, dict) else j
    raise bc.BoundaryError((j.get("code") if isinstance(j, dict) else None) or _C3_CODE_OF_STATUS.get(c, "FAILED_PRECONDITION"), (j.get("message") if isinstance(j, dict) else str(j)[:120]) or f"HTTP {c}")

def _c3_activate(release_id):   # 운영자가 릴리스 운영 화면에서 하는 일: operator 계정으로 POST /v1/activate
    c, j, _ = _c3_gw("POST", "/v1/activate", "operator", {"requested_by_role": "operator", "release_id": release_id})
    assert c == 200, f"activate {release_id} 실패 {c}: {str(j)[:200]}"
    return j

def _c3_pointer():   # 운영자가 보는 활성 포인터(없으면 None)
    c, j, _ = _c3_gw("GET", "/v1/active-pointer", "operator")
    assert c in (200, 404), ("활성 포인터 조회", c, str(j)[:120])
    return (j.get("item") if isinstance(j, dict) else None) if c == 200 else None   # 응답은 {"item": ActivePointer 또는 null}

# 영역마다 자기 DB 컨테이너(<서비스>-db): 계정(데이터베이스) -> DB 서비스. 앱이 쓰는 4개 영역 DB 가 "데이터베이스 전체"다(keycloak-db 는 사람 인증 몫)
_DB_OF = {"survey": "survey-db", "qa": "question-authoring-db", "ops": "ops-feedback-db", "gate": "release-gate-db"}


def _pgs():
    return [f"{a.project}-{d}-1" for d in _DB_OF.values()]


def _pg_each(verb, pgs, **kw):   # 영역 DB 컨테이너 전부에 같은 docker 동사(stop/start/pause/unpause)
    for c in ([pgs] if isinstance(pgs, str) else pgs): sh([a.docker, verb, c], **kw)


def _c3_pg_wait(pgs):
    for pg in ([pgs] if isinstance(pgs, str) else pgs):
        wait(lambda pg=pg: sh([a.docker, "inspect", "-f", "{{.State.Health.Status}}", pg], check=False).stdout.strip() == "healthy", 120, f"{pg} healthy", every=2)

@step('6', repos=('ops-feedback', 'survey-service', 'boundary-contracts') + _GW, deps=('1', '4'),
      why="step6 은 STATE['qs'](step1)·['releases'](step4)를 읽는다")
def step6():
    title(6, "Trace를 수집·비식별해 실패 사례를 만든다 (ops-feedback, I6->I7)")
    rel = (STATE.get("releases") or {}).get(STATE["qs"][-1]["version"], f"rel-{RID}-none")
    env = trace_env(rel, 1); STATE["trace_env"] = env; save()
    # Trace 를 ops-feedback 으로 보내는 운영 주체는 survey-service(outbox)다: 그 컨테이너 안에서, 그 서비스의 수집 토큰으로 이웃 서비스 이름 주소를 부른다
    o = _c3_py("survey-service", '''
u = "https://ops-feedback/v1/traces"; t = _tokfile("SURVEY_TRACE_INGEST_TOKEN_FILE")
r1 = call("POST", u, t, V["env"]); r2 = call("POST", u, t, V["env"])
n = call("POST", u, None, V["env"]); bad = call("POST", u, t, {**V["env"], "trace": {"x": 1}})
R = {"r1": r1[:2], "r2": r2[:2], "noauth": [n[0], n[2]], "bad": bad[:2]}''', env=env)
    (c1, r1), (c2, r2) = o["r1"], o["r2"]
    assert c1 == 200 and c2 == 200 and (r1["status"], r2["status"]) == ("ACCEPTED", "DUPLICATE"), (o["r1"], o["r2"])
    validate("IngestResult", dict(r1)); validate("IngestResult", dict(r2))
    cn, wn = o["noauth"]   # 계약 CONVENTIONS.md 6절: 토큰이 없으면 401 + WWW-Authenticate: Bearer
    assert cn == 401 and (wn or "").split(" ")[0].rstrip(",") == "Bearer", ("토큰 없는 Trace 수집: 401 + WWW-Authenticate: Bearer (계약 CONVENTIONS.md 6절)", cn, wn)
    c, e4 = o["bad"]; assert c == 400; validate("BoundaryError", e4)
    rec("6a", "TEST-SUB", f"실패 신호가 든 봉투는 e2e가 만든 시험 자료(공개 API의 정상 턴으로는 실패 사례가 생기지 않음; 정상 턴의 Trace 전송은 단계 5에서 REAL로 확인; release_id는 단계 4의 실제 릴리스). 수집 REAL(survey-service 컨테이너 안에서 survey-service 의 수집 토큰으로): ACCEPTED→DUPLICATE, 토큰 없음 401, 스키마 위반 400")
    rc, out, err = _c3_job("job-ops-feedback")
    assert rc == 0, f"ops 잡 종료 {rc}: {(err + out)[-600:]}"
    summ = json.loads(out.strip().splitlines()[-1])
    # 실패 사례는 검토자가 게이트웨이(검토 화면의 경로)로 읽는다: ops-feedback 읽기 토큰은 게이트웨이가 붙인다
    fs = _c3_gwc(HttpFailureStore, "reviewer")
    cases = fs.list_cases(source_release_id=rel)[0]
    assert cases, f"FailureCase가 생기지 않았다: {summ}"
    for c in cases:
        validate("FailureCase", dict(c))
        ref = c.get("deidentified_trace_ref") or c.get("trace_ref")
    tr = fs.get_trace(cases[0]["deidentified_trace_ref"]); blob = json.dumps(tr, ensure_ascii=False)
    assert f"s-{RID}" not in blob and f"t-{RID}-1" not in blob, "비식별 trace에 원본 세션/턴 ID가 남았다"
    rc2, out2, err2 = _c3_job("job-ops-feedback")
    s2 = json.loads(out2.strip().splitlines()[-1]); assert s2.get("cases_published", 0) == 0, f"잡이 멱등이 아니다: {s2}"
    STATE["cases"] = [dict(c) for c in cases]; save()
    rec("6b", "REAL", f"비식별 잡 run-once(컨테이너, 시험용 잡 설정 test/ops-job): FailureCase {len(cases)}건 게시, 스키마 통과, 비식별 trace에 원본 세션·턴 ID 없음(검토자 계정으로 게이트웨이 경유 읽기), 재실행은 새 사례 0건(멱등). 요약 {json.dumps(summ)[:160]}")

GOOD_EXPECTED = {"action": "NEXT", "next_item": "Q1.D02", "values": [{"key": "Q1.D01.diagnosed", "value": False, "precision": "exact", "status": "ANSWERED", "save": True}]}   # 검토자가 쓴 정답(시험 자료, ActionExtraction)
def bad_ok():
    return {"review_status": "CONFIRMED", "expected_kind": "LORA_A", "expected": GOOD_EXPECTED}

@step('7', repos=('synthetic-data', 'ops-feedback', 'question-authoring', 'boundary-contracts') + _GW, deps=('1', '2', '6'),
      why="step7 은 STATE['cases'],['extract_input'](step6)·['dataset'](step2)·['qs'](step1)를 읽는다")
def step7():
    title(7, "실패 사례가 데이터 생성·학습·저작으로 돌아간다 (I7 HTTP)")
    if not STATE.get("cases"): rec(7, "BLOCKED", "FailureCase가 없다(단계 6)"); return
    defects = []   # 경계 결함: 단계를 끝까지 돌린 뒤 한꺼번에 실패시킨다(뒤 확인을 가리지 않는다)
    fs = _c3_gwc(HttpFailureStore, "reviewer")   # 검토자 계정으로 게이트웨이 경유(읽기 토큰은 게이트웨이가 붙인다)
    mine = {c["case_id"] for c in STATE["cases"]}
    cid = STATE["cases"][0]["case_id"]
    # 개선 신호(저작으로의 환류): question-authoring이 I7을 읽어 문항별 사례 수를 낸다. 저자가 읽는 것이므로 먼저 저자 계정으로 게이트웨이를 시도한다
    cg, sg, _ = _c3_gw("GET", f"/v1/signals?question_set_id={QS}", "author")
    if cg != 200: defects.append(f"저자 계정이 개선 신호(GET /v1/signals)를 읽을 입구가 게이트웨이에 없다(상태 {cg}). 저작으로의 환류를 받는 사람은 저자인데 Caddyfile 의 저자 경로(@qaauthor)에 /v1/signals 가 없다")
    # 서비스 동작 자체(저자 토큰은 200, 읽기 토큰은 403, 원문 없음)는 question-authoring 컨테이너 안에서 그 서비스의 토큰 목록으로 확인한다
    sg_in = _c3_py("question-authoring", '''
au = next(t.split(":")[0] for t in _tokfile("QA_AUTHOR_TOKENS_FILE").split(",") if t.split(":")[1] == V["author"])
rd = _list("QA_READ_TOKENS_FILE")["synthetic-data"]; B = "@SELF@/v1/signals"
R = {"sig": call("GET", B + "?question_set_id=" + V["qs"], au)[:2], "read": call("GET", B, rd)[0]}''', qs=QS, author=_C3_ACCT["author"])
    c, sig = sg_in["sig"]; assert c == 200, (c, sig)
    blob = json.dumps(sig, ensure_ascii=False)
    assert QS in blob and any(k in blob for k in ("case_count", "cases", "count")), f"신호에 문항 세트/사례 수가 없다: {blob[:300]}"
    assert sg_in["read"] == 403, "읽기 토큰으로 신호가 열림"
    assert f'"s-{RID}"' not in blob and "삼십육" not in blob, "신호에 발화/ID 원문이 있다"
    rec("7s", "REAL", f"question-authoring GET /v1/signals(저자 토큰, 읽기 토큰은 403; question-authoring 컨테이너 안에서 확인)가 ops-feedback I7을 HTTP로 읽어 문항 세트 {QS}의 사례 수를 낸다(저작으로의 환류). 응답 {blob[:200]}")
    bad = {"review_status": "CONFIRMED", "expected": {"items": [{"bad": 1}]}, "expected_kind": "LORA_A"}
    # 검토 게시의 입력 검증은 검토자 계정으로 게이트웨이를 통해(검토 화면의 경로) 본다. X-Openit-User 는 게이트웨이가 계정 ID 로 붙인다
    c, e = _c3_gw("POST", f"/v1/cases/{cid}/review", "reviewer", bad)[:2]; assert c == 400, (c, e); validate("BoundaryError", e)
    c, e2 = _c3_gw("POST", f"/v1/cases/{cid}/review", "reviewer", {"review_status": "CONFIRMED", "expected": GOOD_EXPECTED})[:2]; assert c == 400, (c, e2)
    # 읽기 토큰으로는 검토를 게시할 수 없다: 게이트웨이는 늘 검토 토큰을 붙이므로 ops-feedback 컨테이너 안에서 그 서비스의 읽기 토큰으로 확인한다
    c403 = _c3_py("ops-feedback", '''
R = call("POST", "@SELF@/v1/cases/" + V["cid"] + "/review", _list("OPS_READ_TOKENS_FILE")["synthetic-data"], V["bad"], {"X-Openit-User": "reader-e2e"})[0]''', cid=cid, bad=bad)
    assert c403 == 403, "읽기 토큰으로 검토 게시됨"
    assert _c3_gw("POST", "/v1/cases/nonexistent-case/review", "reviewer", {"review_status": "DISMISSED"})[0] == 404
    pi = dict(__import__("copy").deepcopy(STATE["extract_input"])); pi["user_utterance"] = "뇌졸중은 진단받은 적 없어요"   # 개인정보를 뺀 문장으로 검토자가 쓴 입력(시험 자료, ActionExtractionInput)
    badri = {**bad_ok(), "reviewed_input": {"user_utterance": 1}}
    c, eri = _c3_gw("POST", f"/v1/cases/{cid}/review", "reviewer", badri)[:2]; assert c == 400, ("잘못된 reviewed_input이 받아들여짐", c, eri)
    good = {"review_status": "CONFIRMED", "expected_kind": "LORA_A", "reviewed_input": pi, "expected": GOOD_EXPECTED}
    # ---- 게이트웨이 경유 검토(admin-console 검토 화면의 경로): 사람 계정(reviewer-e2e) 인증 뒤, ops-feedback 읽기/reviewer 쓰기 토큰은 게이트웨이가 붙인다
    assert _c3_gw("GET", "/v1/cases")[0] == 401, "인증 없이 /v1/cases 가 열려 있다"
    assert _c3_gw("POST", f"/v1/cases/{cid}/review", None, good)[0] == 401
    assert _c3_gw("GET", "/v1/cases", "approver")[0] == 403, "승인자 계정이 검토 경로를 부를 수 있다"
    assert _c3_gw("POST", f"/v1/cases/{cid}/review", "approver", good)[0] == 403, "승인자 계정이 검토를 게시할 수 있다"
    assert _c3_gw("GET", "/v1/submissions", "reviewer")[0] == 403, "검토자 계정이 승인 경로를 부를 수 있다"
    assert _c3_gw("POST", "/v1/approvals", "reviewer", {})[0] == 403
    assert _c3_gw("POST", "/v1/traces", "reviewer", {})[0] == 404, "서비스 내부 면(POST /v1/traces)이 게이트웨이에 열려 있다"
    c, lst, hd = _c3_gw("GET", "/v1/cases?review_status=PENDING", "reviewer"); assert c == 200, (c, lst)
    assert "no-store" in hd.get("cache-control", ""), "Cache-Control: no-store 가 유지되지 않았다"
    mine_pending = [x for x in lst["items"] if x["case_id"] == cid]; assert mine_pending and mine_pending[0]["review_status"] == "PENDING", lst
    c, one, _ = _c3_gw("GET", f"/v1/cases/{cid}", "reviewer"); assert c == 200 and one["case_id"] == cid, (c, one); validate("FailureCase", one)
    c, trc, _ = _c3_gw("GET", "/v1/deidentified-traces/" + one["deidentified_trace_ref"], "reviewer"); assert c == 200 and trc, (c, trc)
    assert "삼십육" not in json.dumps(trc, ensure_ascii=False) and f's-{RID}' not in json.dumps(trc), "비식별 trace에 원문이 있다"
    c, r1, _ = _c3_gw("POST", f"/v1/cases/{cid}/review", "reviewer", good, {"X-Openit-User": "spoofed-user"}); assert c == 201, (c, r1); validate("FailureCase", r1)
    c, r2, _ = _c3_gw("POST", f"/v1/cases/{cid}/review", "reviewer", good, {"X-Openit-User": "spoofed-user"}); assert c == 200 and r2 == r1, (c, "같은 검토 재전송이 같은 결과가 아니다")
    rec("7g", "REAL", "검토 화면 경로를 게이트웨이 경유로 한 번: 인증 없이 401, 승인자 계정으로 검토 경로 403·검토자 계정으로 승인 경로 403, POST /v1/traces 404, 검토자 계정으로 PENDING 목록 -> 사례 조회(FailureCase 스키마) -> 비식별 trace 조회(no-store 유지, 원문 없음) -> reviewed_input 포함 CONFIRMED 201(재전송 200, 위조 X-Openit-User 무시 요청)")
    reviewer_id = _C3_ACCT["reviewer"]
    rb = (r1.get("ext") or {}).get("ops-feedback", {}).get("reviewed_by")
    assert rb == reviewer_id, f"검토 응답의 reviewed_by 가 인증 계정이 아니다(위조 X-Openit-User={'spoofed-user'}): {rb!r}"
    via_i7 = fs.get_case(cid)   # 계약 클라이언트로 다시 읽어도(스키마 검증 포함) 같은 기록이어야 한다
    assert (via_i7.get("ext") or {}).get("ops-feedback", {}).get("reviewed_by") == reviewer_id, dict(via_i7).get("ext")
    rec("7h", "REAL", f"검토자 기록: 게이트웨이 경유 검토 응답과 I7 조회 결과의 ext[ops-feedback].reviewed_by 가 인증 계정 {reviewer_id}이고, 요청에 실은 위조 X-Openit-User(spoofed-user)는 기록되지 않았다(게이트웨이가 덮어씀). 승인 쪽도 같은 위조 시험이 REAL이다(4g: approver_id가 인증 계정 {_C3_ACCT['approver']}). 화면 렌더링은 BLOCKED")

    confirmed = [x for x in fs.list_cases(review_status="CONFIRMED")[0] if x["case_id"] in mine]; assert confirmed
    assert confirmed[0].get("reviewed_input") == pi, "reviewed_input이 I7 읽기에 그대로 보이지 않는다"
    rec("7a", "REAL", f"검토 확인을 HTTP로(게이트웨이 경유, 검토자 계정): POST /v1/cases/{{id}}/review 잘못된 expected는 400({e.get('message','')[:80]}), expected_kind 없음 400, 읽기 토큰 403(ops-feedback 컨테이너 안), 없는 사례 404, 올바른 확인(reviewed_input 포함)은 201(새 version, FailureCase 스키마 통과, I7 읽기에서 reviewed_input 그대로), 잘못된 reviewed_input 400, 재전송 200 같은 결과. 검토 UI는 아직 없다")
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
    if defects: raise AssertionError("경계 결함: " + "; ".join(defects))

def _ds_tar(manifest, root):
    import io, tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        def add(name, data):
            ti = tarfile.TarInfo(name); ti.size = len(data); ti.mtime = 0; t.addfile(ti, io.BytesIO(data))
        add("manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
        for f in manifest["files"]: add("files/" + f["path"], (root / "files" / f["path"]).read_bytes())
    return buf.getvalue()

@step('7d', repos=('synthetic-data', 'boundary-contracts', 'deploy:compose.yaml,scripts/gen-secrets.sh') + _GW, deps=('1', '2'),
      why="step7d 는 STATE['dataset'](step2)와 step2 가 WORK/datasets 에 쓴 manifest.json·files/ 를 읽어 dataset-store 에 게시한다(e2e_steps.py step7d). 실행 중 스택의 dataset-store 가 필요하다",
      also={'model-lab': 'model-lab 이 읽는 I2(dataset-store) 읽기 토큰 경로와 쓰기 거부(model-lab 코드는 E2E 에서 돌지 않는다)'})
def step7d():
    title("7d", "dataset-store(I2 HTTP 서버, 쓰기=synthetic-data·읽기=model-lab 토큰): 게시, 읽기, 읽기 토큰 쓰기 거부, 멱등, 불변, 토큰 없음 (D100)")
    if "dataset" not in STATE: rec("7d", "BLOCKED", "단계 2 가 게시한 데이터셋이 없다(STATE['dataset'])"); return
    ds = STATE["dataset"]; root = WORK / "datasets" / ds["id"] / ds["version"]
    m = json.loads((root / "manifest.json").read_text()); assert m["content_hash"] == ds["content_hash"], "단계 2 의 매니페스트가 바뀌었다"
    body = _ds_tar(m, root); q = urllib.parse.quote
    # 실제 생산자 잡(synthetic-data import, store.kind=http)이 dataset-store 로 게시한다. 같은 입력이라 단계 2 의 파일 저장소 게시와 버전·content_hash 가 같아야 한다(결정적)
    # (잡은 이미지 안의 계약 패키지로 도므로 호스트 잡 환경의 버전을 따로 확인하지 않는다)
    hs = {"kind": "http", "base_url": DS_JOB_URL, "token_secret": "DATASET_STORE_WRITE_TOKEN", "timeout_seconds": 60}   # 잡에 넘기는 주소: 서비스 이름(컨테이너 안에서 127.0.0.1 은 자기 자신)
    rc, o, _ = run_import("http", 2, hs)
    assert rc == 0 and o.get("status") in ("PUBLISHED", "ALREADY_PUBLISHED"), f"잡의 HTTP 게시 실패: {rc} {o}"
    assert (o["version"], o["content_hash"]) == (ds["version"], ds["content_hash"]), ("잡이 HTTP 로 게시한 버전·해시가 단계 2 와 다르다", o)
    rc2, o2, _ = run_import("http2", 2, hs); assert rc2 == 0 and o2["status"] == "ALREADY_PUBLISHED", ("같은 잡 재실행이 멱등이 아니다", rc2, o2)
    via = f"실제 생산자 잡 import, store.kind=http, 결과 {o['status']}, 버전·해시는 단계 2 와 같다) -> 같은 잡 재실행 ALREADY_PUBLISHED"
    # 불변: 같은 (id, 버전)에 내용만 다른 매니페스트(created_at 만 다름, 새 content_hash)는 409. 저장된 것이 바뀌지 않았는지 다시 읽어 확인한다
    m2 = dict(m); m2["created_at"] = "2026-10-16T00:00:00Z" if m["created_at"] != "2026-10-16T00:00:00Z" else "2026-10-17T00:00:00Z"
    m2["content_hash"] = canonical.content_hash(m2); validate("DatasetManifest", m2)
    # dataset-store 는 datasets 네트워크에만 있고 읽는 쪽(model-lab)·쓰는 쪽(synthetic-data)은 잡 컨테이너다. 이 시험은 dataset-store 컨테이너 안에서 그 서비스가 받는 두 토큰(쓰기=synthetic-data, 읽기=model-lab)으로 요청한다
    o7 = _c3_py("dataset-store", '''
import base64, hashlib
B = "@SELF@"; TAR = "application/x-tar"; ID, VER = V["id"], V["ver"]
WT = _list("DATASET_STORE_WRITE_TOKENS_FILE")["synthetic-data"]; RT = _list("DATASET_STORE_READ_TOKENS_FILE")["model-lab"]
body, body2 = base64.b64decode(V["body"]), base64.b64decode(V["body2"]); vp = B + "/v1/datasets/" + V["qid"] + "/versions/" + V["qver"]
R = {"dup": call("POST", B + "/v1/datasets", WT, raw=body, ctype=TAR)[:2],
     "list": call("GET", B + "/v1/datasets", RT)[:2], "versions": call("GET", B + "/v1/datasets/" + V["qid"] + "/versions", RT)[:2], "manifest": call("GET", vp, RT)[:2], "files": []}
for p in V["files"]:
    st, b, _ = call("GET", vp + "/files/" + V["quote"][p], RT, rawout=True); R["files"].append([p, st, "sha256:" + hashlib.sha256(b).hexdigest()])
R["read_post"] = call("POST", B + "/v1/datasets", RT, raw=body, ctype=TAR)[0]
R["conflict"] = call("POST", B + "/v1/datasets", WT, raw=body2, ctype=TAR)[0]
R["after"] = call("GET", vp, RT)[:2]
R["noauth_get"] = call("GET", B + "/v1/datasets")[::2]; R["noauth_post"] = call("POST", B + "/v1/datasets", None, raw=body, ctype=TAR)[0]
R["badtok"] = call("GET", B + "/v1/datasets", "x" * 48)[::2]''',
        timeout=120, id=ds["id"], ver=ds["version"], qid=q(ds["id"]), qver=q(ds["version"]), body=__import__("base64").b64encode(body).decode(), body2=__import__("base64").b64encode(_ds_tar(m2, root)).decode(),
        files=[f["path"] for f in m["files"]], quote={f["path"]: q(f["path"], safe="") for f in m["files"]})
    c2, b2 = o7["dup"]; assert c2 == 200 and b2["content_hash"] == m["content_hash"], ("같은 게시는 멱등 200 이어야 한다", c2, str(b2)[:200])
    # 읽기: 읽기 토큰으로 목록·버전·매니페스트·파일 바이트(해시를 manifest 와 대조)
    c, b = o7["list"]; assert c == 200 and ds["id"] in json.dumps(b), ("목록", c, str(b)[:200])
    c, b = o7["versions"]; assert c == 200 and ds["version"] in json.dumps(b), ("버전 목록", c, str(b)[:200])
    c, b = o7["manifest"]; assert c == 200 and b["content_hash"] == m["content_hash"], ("매니페스트", c, str(b)[:200])
    validate("DatasetManifest", b)
    want = {f["path"]: f["content_hash"] for f in m["files"]}
    for p, c, h in o7["files"]: assert c == 200 and h == want[p], ("파일 바이트가 manifest 해시와 다르다", p, c)
    assert len(o7["files"]) == len(m["files"])
    assert o7["read_post"] == 403, ("읽기 토큰으로 게시가 거부되지 않았다", o7["read_post"])
    assert o7["conflict"] == 409, ("같은 버전에 다른 내용은 409 여야 한다", o7["conflict"])
    c, b = o7["after"]; assert c == 200 and b["content_hash"] == m["content_hash"], "409 뒤에 저장된 버전이 바뀌었다"
    # 토큰 없음·모르는 토큰은 401 + WWW-Authenticate: Bearer, 읽기 토큰으로 게시처럼 맞는 토큰의 권한 부족만 403 이다(계약 CONVENTIONS.md 6절, HTTP.md I2, RFC 9110 15.5.2, RFC 6750 3절; D106)
    for what, (c, w) in (("토큰 없는 읽기", o7["noauth_get"]), ("모르는 토큰", o7["badtok"])):
        assert c == 401 and (w or "").split(" ")[0].rstrip(",") == "Bearer", (f"{what}: 토큰이 없거나 틀리면 401 + WWW-Authenticate: Bearer (계약 CONVENTIONS.md 6절)", c, w)
    assert o7["noauth_post"] == 401, ("토큰 없는 게시", o7["noauth_post"])
    rec("7d", "REAL", f"dataset-store 서버(실제 이미지)에 단계 2 와 같은 입력의 데이터셋 {ds['id']}@{ds['version']} 를 쓰기 토큰(synthetic-data)으로 게시({via}, 같은 tar 재게시는 멱등 200 -> 읽기 토큰(model-lab)으로 목록·버전·매니페스트(스키마 통과)·파일 {len(m['files'])}개 바이트(manifest 해시 일치) -> 읽기 토큰의 게시는 403 -> 같은 버전에 다른 내용은 409 이고 저장본 불변 -> 토큰 없음·모르는 토큰은 401 + WWW-Authenticate: Bearer. 요청은 dataset-store 컨테이너 안에서 그 서비스의 두 토큰으로 했다(서비스가 datasets 네트워크에만 있어 호스트·게이트웨이로는 닿지 않는다). 못 보는 것: 소비자 model-lab 의 실제 읽기 코드(그 영역), 큰 본문·동시 게시 한도, synthetic-data run(시드) 모드의 HTTP 게시(import 모드만 확인)")

@step('8', repos=('release-gate', 'survey-service', 'kiosk-frontend', 'boundary-contracts') + _GW, deps=('1', '4', '6'),
      why="step8 은 STATE['cases'](step6)·['pointers'],['releases'](step4)·['qs'](step1)를 읽는다",
      also={'ops-feedback': 'ops-feedback이 release-gate에 롤백 요청(I5)'})
def step8():
    title(8, "롤백 요청이 활성 릴리스를 되돌린다 (ops-feedback -> release-gate, I5 HTTP)")
    # 롤백을 요청하는 운영 주체는 ops-feedback 의 잡이다: 그 잡 컨테이너 안에서 그 잡의 쓰기 토큰(OPS_GATE_WRITE_TOKEN_FILE)으로 release-gate 를 부른다(잡은 release 네트워크에 있다)
    rollback = lambda req: _c3_job_py("job-ops-feedback", 'R = call("POST", "https://release-gate/v1/rollback", _tokfile("OPS_GATE_WRITE_TOKEN_FILE"), V["req"])[:2]', req=req)
    if "releases" not in STATE:
        req = {"pipeline_schema_version": bc.PIPELINE_SCHEMA_VERSION, "request_id": f"rbk-{RID}-0", "requested_at": "2026-10-15T00:00:00Z", "from_release_id": f"rel-{RID}-new",
               "to_release_id": f"rel-{RID}-old", "reason": "E2E 시험", "evidence_refs": ["ev-e2e-test-1"], "requested_by_role": "ops-feedback"}
        validate("RollbackRequest", req); c, rc = rollback(req); assert c in (200, 201), (c, rc); validate("RollbackReceipt", dict(rc)); assert rc["status"] == "REJECTED"
        rec(8, "BLOCKED", "릴리스가 없어 APPLIED를 못 보인다. 요청 경로만 확인(REJECTED 영수증)"); return
    rels = STATE["releases"]; old, new = rels[STATE["qs"][0]["version"]], rels[STATE["qs"][-1]["version"]]
    cur = _c3_pointer(); assert cur["release_id"] == new   # 활성 포인터는 운영자가 보는 것과 같다(운영자 계정, 게이트웨이)
    req = {"pipeline_schema_version": bc.PIPELINE_SCHEMA_VERSION, "request_id": f"rbk-{RID}-1", "requested_at": "2026-10-15T00:00:00Z", "from_release_id": new,
           "to_release_id": old, "reason": "E2E 시험 롤백", "evidence_refs": [STATE["cases"][0]["case_id"]] if STATE.get("cases") else ["ev-e2e-test-1"], "requested_by_role": "ops-feedback"}
    validate("RollbackRequest", req)
    c, rc = rollback(req); assert c in (200, 201), (c, rc); validate("RollbackReceipt", dict(rc)); assert rc["status"] == "APPLIED", dict(rc)
    c2, rc2 = rollback(req); assert c2 in (200, 201) and dict(rc2) == dict(rc), "같은 request_id가 같은 결과가 아니다"
    ap = _c3_pointer(); validate("ActivePointer", dict(ap)); assert ap["release_id"] == old and ap["pointer_version"] > STATE["pointers"][-1]["pointer_version"]
    r = wait(lambda: (lambda cr: cr[1] if cr[0] == 200 and cr[1].get("active_release") == old else None)(_c3_survey_ready()), 60, f"survey가 이전 릴리스 {old}로 복귀")
    assert not r["release_loader"]["rejections"]
    # 공개 API: 롤백 뒤에도 서비스가 산다. 새 세션은 이전 릴리스로 시작된다(/readyz active_release), 롤백 전에 시작한 세션도 이어서 처리된다
    sidb = f"sess-{RID}-b"
    c, st = kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}); sidb = _sid(c, st)
    c, tb = public_turn(sidb, "turn-1", "뇌졸중은 없어요"); assert c == 200, (c, tb)
    kiosk(f"/v1/sessions/{sidb}/end", {"session_id": sidb, "kind": "SESSION_END"})
    # 롤백 권한이 없는 역할(question-authoring 의 쓰기 토큰)은 거부된다: release-gate 컨테이너 안에서 그 서비스의 쓰기 토큰 목록의 다른 역할로 확인한다
    cb, eb = _c3_py("release-gate", 'R = call("POST", "@SELF@/v1/rollback", _list("GATE_WRITE_TOKENS_FILE")["question-authoring"], V["req"])[:2]', req={**req, "request_id": f"rbk-{RID}-2"})
    assert cb in (400, 401, 403) and isinstance(eb, dict) and eb.get("code") == "PERMISSION_DENIED", ("허용되지 않은 역할이 롤백함", cb, str(eb)[:120])
    rec(8, "REAL", f"ops-feedback 잡의 토큰(잡 컨테이너 안)으로 RollbackRequest -> RollbackReceipt APPLIED(멱등), 활성 포인터(운영자 계정, 게이트웨이) {new}->{old}, 실제 survey-service가 /readyz에서 이전 릴리스로 복귀, 롤백 권한 없는 역할은 PERMISSION_DENIED(release-gate 컨테이너 안), 롤백 뒤 공개 API로 새 세션 한 턴 처리(이전 릴리스). 롤백을 요청한 주체는 e2e가 띄운 ops-feedback 잡 컨테이너이고 ops-feedback 잡의 자동 롤백 평가는 아님")

def _c3_sub_for(subj):
    """제출 목록(승인자 계정, 게이트웨이)에서 이 조합(문항 세트·LoRA 쌍)의 제출을 찾는다. 없으면 None. 후보는 수집기 잡이 접수한다(운영에서 접수하는 주체)."""
    ref = lambda r: (r["id"], str(r["version"]))
    items, _ = _c3_gwc(HttpGateService, "approver").list_submissions(limit=100)
    for v in items:
        s = v.get("subject", {})
        if sorted(ref(x) for x in s.get("question_sets", [])) == sorted(ref(x) for x in subj["question_sets"]) and all(ref(s.get(k, {"id": None, "version": None})) == ref(subj[k]) for k in ("lora_a", "lora_b")): return dict(v)
    return None

def _c3_report_of(sid):   # 승인 요청 보고서(자동 검사 전이면 409 -> None)
    c, j, _ = _c3_gw("GET", f"/v1/submissions/{sid}/review-report", "approver")
    if c == 409: return None
    assert c == 200, ("review-report", c, str(j)[:200])
    return j

def _c3_ms_get(path, auth=True):
    """추론 서버(model-runtime)의 GET. 다른 호스트 역할의 추론 서버(--ms-url 또는 별도 프로젝트)면 그 주소로(호출자 토큰은 --ms-token-file 또는 이 구성이 만든 survey-service 용 토큰), 아니면 이 프로젝트의 model-serving 컨테이너 안에서 그 서버가 받는 토큰으로. (상태, JSON 또는 문자열)."""
    base = (getattr(a, "ms_url", "") or "").rstrip("/") or SB.inference_url()
    if base:
        tf = getattr(a, "ms_token_file", "")
        tok = pathlib.Path(tf).read_text().strip() if tf else _c3_tok("inference-survey-service")
        req = urllib.request.Request(base + path, headers={"Authorization": "Bearer " + tok} if auth else {})
        try:
            with urllib.request.urlopen(req, timeout=30) as r: st, b = r.status, r.read()
        except urllib.error.HTTPError as e: st, b = e.code, e.read()
        try: return st, json.loads(b or b"null")
        except ValueError: return st, b.decode(errors="replace")
    r = _c3_py("model-serving", 'R = call("GET", "@SELF@" + V["path"], _list("MODEL_RUNTIME_TOKENS_FILE")["survey-service"] if V["auth"] else None)[:2]', path=path, auth=auth)
    return r[0], r[1]

def _c3_ms_container(): return getattr(a, "ms_container", "") or f"{a.project}-model-serving-1"   # 호스트에서 docker inspect/exec 하는 대상(운영자 역할)

def _c3_ensure_sub(subj):
    """이 조합의 제출. 수집기 잡이 접수한 것이 있으면 그것(운영의 경로, SubmissionView 스키마). 수집기는 문항 세트마다 가장 최근 검수 버전만 접수하므로 옛 버전의 조합은 없다:
    그 경우 release-gate 컨테이너 안에서 operator 쓰기 토큰으로 POST /v1/submissions 를 한다(게이트웨이에는 이 경로가 없다: 운영에서는 수집기만 접수한다). 반환은 submission_id 가 든 dict."""
    sub = _c3_sub_for(subj)
    if sub: validate("SubmissionView", sub); return sub
    c, j = _c3_py("release-gate", '''
R = call("POST", "@SELF@/v1/submissions", _list("GATE_WRITE_TOKENS_FILE")["operator"], {"subject": V["subj"], "requested_by_role": "operator"}, {"X-Openit-User": V["user"]})[:2]''', subj=subj, user=_C3_ACCT["operator"])
    assert c in (200, 201, 202), ("후보 접수", c, str(j)[:200]); validate("GateSubmission", j)
    return j

@step('demo4', repos=('release-gate', 'model-lab') + _GW, deps=('1', '3'),
      why='demo.sh 전용. E2E 기본 실행에 들어가지 않는다')
def demo4():
    """demo.sh 용: 후보 수집·자동 검사까지 하고, 승인은 --demo-stop 이면 사람에게 남긴다(아니면 시험용 승인자 계정으로 대신: TEST-SUB). 승인 화면에 볼 제출 하나는 항상 대기로 둔다."""
    title("demo4", "데모 릴리스: 후보 수집·자동 검사 -> 승인 -> 활성화 (release-gate)")
    if "lora" not in STATE: rec("demo4", "BLOCKED", "단계 3의 패키지가 없다"); return
    rc, out, err = _c3_job("job-release-gate-collect")
    assert rc in (0, 75), f"collect 종료 {rc}: {(err + out)[-500:]}"
    A, B = STATE["lora"]["LORA_A"], STATE["lora"]["LORA_B"]
    subj = {v["version"]: _subj(v, A, B) for v in STATE["qs"]}
    subj_u = _subj_u(A, B)
    subs = {k: _c3_ensure_sub(sj) for k, sj in subj.items()}
    sub_u = _c3_ensure_sub(subj_u)
    for k, sub in list(subs.items()) + [("u", sub_u)]:
        wait_review_report(_c3_report_of, sub["submission_id"], k)
    STATE["demo_subs"] = {**{k: v["submission_id"] for k, v in subs.items()}, "u": sub_u["submission_id"]}; save()
    if a.demo_stop:
        rec("demo4", "REAL", f"후보 수집·자동 검사까지 완료. 승인 대기 제출: " + ", ".join(f"문항 세트 v{k}={v['submission_id']}" for k, v in subs.items()) + f", 보지 못한 문항 세트={sub_u['submission_id']}. 사람이 /admin/ 에서 승인한 뒤 demo.sh activate")
        return
    rels = {}
    for k, sub in subs.items():
        _c3_approve("approver", sub["submission_id"], "APPROVE", reason="데모: 시험용 승인자(스크립트)가 대신 승인")
    for k, sj in subj.items():
        d = wait(lambda sj=sj: next((x for x in _c3_decisions_for(sj) if x["result"] == "PASS"), None), 30, f"PASS 판정 v{k}")
        rels[k] = d.get("release_id")
    for k in sorted(rels): _c3_activate(rels[k])
    STATE["releases"] = rels; save()
    rec("demo4", "TEST-SUB", f"승인자를 스크립트가 시험용 승인자 계정으로 대신했다(TEST-SUB). PASS 릴리스 {rels}, 활성화 완료. 승인 화면용으로 제출 {sub_u['submission_id']}(보지 못한 문항 세트)는 승인 대기로 남겼다")

@step('demo_activate', repos=('release-gate',) + _GW, deps=('1', '3'),
      why='demo.sh 전용')
def demo_activate():
    """사람이 /admin/ 에서 승인한 제출의 릴리스를 활성화한다(오래된 문항 세트 버전부터)."""
    title("demo_activate", "승인된 제출의 릴리스 활성화")
    rels = {}
    for k in sorted(v["version"] for v in STATE["qs"]):
        sj = _subj(next(v for v in STATE["qs"] if v["version"] == k), STATE["lora"]["LORA_A"], STATE["lora"]["LORA_B"])
        d = next((x for x in _c3_decisions_for(sj) if x["result"] == "PASS"), None)
        if d: rels[k] = d.get("release_id")
    if not rels: rec("demo_activate", "BLOCKED", "승인된(PASS) 제출이 아직 없다. /admin/ 에서 승인한 뒤 다시 실행한다"); return
    cur = _c3_pointer()
    for k in sorted(rels):
        if not cur or cur["release_id"] != rels[k]: cur = _c3_activate(rels[k])
    STATE["releases"] = rels; save()
    rec("demo_activate", "REAL", f"승인된 릴리스 활성화: {rels}, 현재 활성 {dict(cur)['release_id']}")

@step('diag', repos=('release-gate',) + _GW, deps=('3', '4', 'demo4', 'demo_activate', 'demo_swap'),
      why='demo.sh 전용 진단')
def diag():
    """demo.sh diag: 켜져 있는 데모의 게이트·레지스트리 상태를 읽기 전용으로 요약한다(게이트웨이·컨테이너 안 읽기만, 토큰·비밀 값은 출력하지 않는다)."""
    title("diag", "진단: 제출·판정·수집기·모델 패키지")
    try:
        items, _ = _c3_gwc(HttpGateService, "approver").list_submissions(limit=100)
        print(f"-- release-gate 제출 {len(items)}건")
        for v in items:
            subj = v.get("subject", {}); qs = (subj.get("question_sets") or [{}])[0]; la = subj.get("lora_a", {}); lb = subj.get("lora_b", {})
            print(f"  [{v.get('status')}] {v['submission_id']} 문진표 {[x.get('id') + '@' + str(x.get('version')) for x in subj.get('question_sets', [])]} LoRA_A {la.get('id')}@{la.get('version')} LoRA_B {lb.get('id')}@{lb.get('version')} decision={v.get('decision_id')} release={v.get('release_id')}")
            if v.get("decision_id"):
                c, d = _c3_gate_read("/v1/decisions/" + v["decision_id"])
                if c == 200: print("\n".join("      " + l for l in decision_text(d).splitlines()))
    except Exception as e:
        print(f"-- 제출 목록을 읽지 못했다: {type(e).__name__}: {str(e)[:200]}")
    try:
        ap = _c3_pointer(); print(f"-- 활성 릴리스 포인터: {ap}")
    except Exception as e:
        print(f"-- 활성 포인터를 읽지 못했다: {type(e).__name__}: {str(e)[:120]}")
    rc, out, err = _c3_job("job-release-gate-collect")
    print(f"-- 후보 수집기 run-once 다시 실행(멱등) 종료 코드 {rc}; 마지막 출력: {(out.strip().splitlines() or ['(없음)'])[-1][:300]}")
    try:   # model-registry 는 release-gate 컨테이너 안에서 그 서비스의 읽기 토큰(GATE_I3_TOKEN_FILE)으로 읽는다(운영에서 패키지를 읽는 주체)
        mr = _c3_py("release-gate", '''
B = "https://model-registry"; T = _tokfile("GATE_I3_TOKEN_FILE"); items = lambda b: b.get("items", b) if isinstance(b, dict) else b
R = []
for i in items(call("GET", B + "/v1/packages", T)[1]):
    vs = items(call("GET", B + "/v1/packages/" + i + "/versions", T)[1]); last = call("GET", B + "/v1/packages/" + i + "/versions/" + vs[-1], T)[1] if vs else {}
    R.append([i, vs, last])''', timeout=90)
        print(f"-- model-registry 패키지 {len(mr)}개")
        for i, vs, m in mr:
            print(f"  {i}: 버전 {vs}")
            if vs:
                sc = m.get("serving_config", {}); print(f"      role={m.get('role')} base={m.get('base_model')} constraint.backend={sc.get('constraint', {}).get('backend')}@{sc.get('constraint', {}).get('backend_version')} prompt={sc.get('prompt_template_version')} runtime={m.get('lineage', {}).get('model_runtime_version')}")
    except Exception as e:
        print(f"-- model-registry 패키지를 읽지 못했다: {type(e).__name__}: {str(e)[:200]}")
    try:
        c, info = _c3_ms_get("/v1/info")
        ex = (info.get("serving_config_expectation") or {}) if c == 200 else {}
        print(f"-- model-serving /v1/info: HTTP {c} backend={info.get('backend') if c == 200 else '-'} 기대 constraint={ex.get('constraint')} prompt={ex.get('prompt_template_versions')} loaded={info.get('loaded') if c == 200 else '-'}")
    except Exception as e:
        print(f"-- model-serving /v1/info 를 읽지 못했다: {type(e).__name__}: {str(e)[:120]}")
    try:
        c, rz = _c3_ms_get("/readyz", auth=False); reason = rz.get("reason") if isinstance(rz, dict) else None
        print(f"-- model-serving /readyz: HTTP {c} status={rz.get('status') if isinstance(rz, dict) else rz} 사유={reason}")
        # 왜 컨테이너 안 읽기를 뺐나: deploy 는 실행 중에 영역 안으로 들어가지 않는다(구조 규칙 1·6, CONVENTIONS 13절). 모델 캐시 사유는 위 /readyz 의 사유(공개 응답)만 본다.
        if "OSError" in str(reason):
            print("   -> 모델 캐시 쓰기 불가 가능성(readyz 사유가 OSError): 영역의 캐시 볼륨 소유·마운트를 영역 문서로 확인한다")
    except Exception as e:
        print(f"-- model-serving /readyz·컨테이너 점검을 건너뜀: {type(e).__name__}: {str(e)[:120]}")
    print(f"-- 상태 파일 요약: 릴리스 {STATE.get('releases')}, 제출 {STATE.get('demo_subs')}, llm 대조 {STATE.get('llm_cfg_vs_server')}")
    rec("diag", "REAL", "진단 출력만 했다(변경 없음)")

@step('demo_active', repos=('release-gate',) + _GW, deps=(),
      why='demo.sh 전용')
def demo_active():
    """demo.sh swap-adapters 가 전후에 부른다: 활성 릴리스 포인터(읽기 전용, 운영자 계정)."""
    title("demo_active", "활성 릴리스 포인터 (읽기 전용)")
    ap = dict(_c3_pointer() or {})
    print(f"  활성 릴리스 {ap.get('release_id')} pointer_version {ap.get('pointer_version')}")
    rec("demo_active", "REAL", f"활성 릴리스 {ap.get('release_id')} (pointer_version {ap.get('pointer_version')})")

@step('demo_swap', repos=('release-gate',) + _GW, deps=('1', '2'),
      why='demo.sh 전용')
def demo_swap():
    """demo.sh swap-adapters: 새 모델 패키지(LORA_A/LORA_B)를 게시 -> 후보 수집·자동 검사 -> 시험용 승인자(스크립트) 승인 -> 활성화 -> model-serving 만 새 번들을 적재.
    문항 세트는 가장 최근 것을 그대로 쓰고 어댑터 쌍만 바뀐다. 단계 3(make_packages, publish_packages)·5s(container_ids, check_unchanged, check_release_loaded)와 같은 함수를 쓴다."""
    title("demo_swap", "어댑터 교체: 게시 -> 자동 검사 -> 시험용 승인 -> 활성화 -> model-serving 적재")
    if "qs" not in STATE or "dataset" not in STATE: rec("demo_swap", "BLOCKED", "데모 상태(문항 세트·데이터셋)가 없다: demo.sh up 이 먼저"); return
    print("  !! 승인자는 사람이 아니라 이 스크립트가 시험용 승인자 계정(release-approver)으로 대신한다(TEST-SUB) !!")
    before_ptr = dict(_c3_pointer() or {})
    pk = make_packages(); refs = publish_packages(pk)
    subj = _subj(STATE["qs"][-1], refs["LORA_A"], refs["LORA_B"])
    snap = container_ids(); assert set(snap) == set(SWAP_SERVICES), f"컨테이너를 찾지 못했다: {sorted(set(SWAP_SERVICES) - set(snap))}"
    ms_before = sh([a.docker, "inspect", "-f", "{{.State.StartedAt}}", _c3_ms_container()], check=False).stdout.strip()
    rc, out, err = _c3_job("job-release-gate-collect")
    assert rc in (0, 75), f"collect 종료 {rc}: {(err + out)[-500:]}"
    sub = _c3_ensure_sub(subj); sid = sub["submission_id"]
    existing = next((d for d in _c3_decisions_for(subj) if d["result"] == "PASS"), None)
    if not existing:
        rep = wait_review_report(_c3_report_of, sid, "교체 후보"); validate("ReviewReport", rep)
        bad = [c for c in rep["checks"] if c["result"] not in ("PASS", "SKIPPED")]
        assert not bad, f"자동 검사가 통과하지 못했다(승인하지 않고 멈춤): {bad}"
        print("  자동 검사: " + ", ".join(f"{c['kind']}={c['result']}" for c in rep["checks"]))
        dec = dict(_c3_approve("approver", sid, "APPROVE", reason="데모: 시험용 승인자(스크립트)가 대신 승인(어댑터 교체)")); validate("GateApproval", dec)
        existing = wait(lambda: next((d for d in _c3_decisions_for(subj) if d["result"] == "PASS"), None), 30, "승인 뒤 PASS 판정")
    rid = existing.get("release_id")
    c, rel = _c3_gate_read("/v1/releases/" + rid); assert c == 200, (c, rel); validate("ReleaseManifest", dict(rel))
    # 번들(해시 검증 포함)은 그것을 읽는 소비자 survey-service 의 컨테이너 안에서 그 서비스의 읽기 토큰·계약 클라이언트로 푼다
    bl = _c3_py("survey-service", '''
from openit_link.clients import HttpReleaseReader
import pathlib
b = HttpReleaseReader("https://release-gate", _tokfile("SURVEY_RELEASE_READER_TOKEN_FILE")).load_bundle(V["rid"], dest=pathlib.Path("/tmp/c3-bundles"))
R = {"release_id": b.manifest["release_id"]}''', timeout=180, rid=rid)
    assert bl["release_id"] == rid
    unchanged_pointer = before_ptr.get("release_id") == rid
    ap = dict(before_ptr) if unchanged_pointer else dict(_c3_activate(rid)); validate("ActivePointer", ap)
    r = wait(lambda: (lambda cr: cr[1] if cr[0] == 200 and cr[1].get("active_release") == rid else None)(_c3_survey_ready()), 300, f"survey가 릴리스 {rid} 적재", every=3)
    st = wait(lambda: (lambda cs: cs[1] if cs[0] == 200 and cs[1].get("state") in ("LOADED", "FAILED") else None)(_c3_ms_get(f"/v1/releases/{rid}")), 600, f"model-serving 이 {rid} 적재", every=3)
    EA.check_release_loaded(st, rid)
    after = container_ids(); EA.check_unchanged({k: tuple(v) for k, v in snap.items()}, after, SWAP_SERVICES)
    ms_after = sh([a.docker, "inspect", "-f", "{{.State.StartedAt}}", _c3_ms_container()], check=False).stdout.strip()
    print(f"  활성 릴리스: {before_ptr.get('release_id')} (pointer_version {before_ptr.get('pointer_version')}) -> {rid} (pointer_version {ap['pointer_version']})" + ("  [이미 활성이었다: 같은 어댑터 쌍, 교체 없음]" if unchanged_pointer else ""))
    print("  컨테이너 StartedAt (전 -> 후):")
    for svc in SWAP_SERVICES: print(f"    {svc:22} {snap[svc][1]} -> {after[svc][1]}  {'불변' if snap[svc] == after[svc] else '바뀜'}")
    print(f"    {'model-serving':22} {ms_before} -> {ms_after}  {'불변' if ms_before == ms_after else '바뀜(컨테이너 재시작)'}")
    print(f"  model-serving 의 릴리스 {rid}: state={st['state']} (LOADED)")
    STATE.setdefault("swaps", []).append({"release_id": rid, "packages": refs}); save()
    rec("demo_swap", "TEST-SUB", f"새 릴리스 {rid} 활성화(승인자는 스크립트가 대신함, TEST-SUB). model-serving 에서 LOADED. {', '.join(SWAP_SERVICES)} 컨테이너의 ID·StartedAt 불변")

def _c3_qa_versions(qset):
    """문항 세트 버전 목록(I1). 운영에서 이것을 읽는 주체는 release-gate(수집·판정)라서 release-gate 컨테이너 안에서 그 서비스의 I1 읽기 토큰으로 읽는다."""
    r = _c3_py("release-gate", '''
st, b, _ = call("GET", "https://question-authoring/v1/question-sets/" + V["qs"] + "/versions", _tokfile("GATE_I1_TOKEN_FILE"))
R = [st, b]''', qs=qset)
    assert r[0] == 200, ("문항 버전 목록", r[0], str(r[1])[:120])
    return r[1].get("items", r[1]) if isinstance(r[1], dict) else r[1]

@step('5p', repos=('survey-service', 'question-authoring', 'release-gate', 'ops-feedback') + _GW, deps=('4',),
      why="STATE['pointers'] 가 없으면 활성 릴리스 없이 일부만 시험한다(has_release). postgres 를 stop/start 한다")
def step5p():
    title("5p", "PostgreSQL 컨테이너 중지 -> 서비스 /readyz 비정상 관찰 -> 기동 -> /readyz 복구, 이전 데이터 보존, 새 쓰기 (D85)")
    pg = _pgs()
    svcs = [("qa", "question-authoring"), ("gate", "release-gate"), ("ops", "ops-feedback"), ("survey", "survey-service")]
    def ready(k):   # 서비스 컨테이너 안에서 본 /readyz (코드, 본문)
        try: c, b, _ = _c3_probe(k, "/readyz"); return c, b
        except Exception as e: return 0, f"{type(e).__name__}"
    def healthy(k): return ready(k)[0] == 200
    # 왜 행 지문이 아닌가(헤드 판단, ADR 0066): DB 행 수준 정합은 데이터 주인 영역의 백업→복구 왕복 시험이 맡는다(RUNTIME R10.1, DATA_OWNERSHIP). deploy 는 BackupJobResult 와 공개 API 값까지만 본다.
    # 데이터 보존은 공개 API 로 읽은 값(question-authoring 문항 버전, survey-service 의 Trace outbox 상태)으로 본다. 영역 DB 를 pg_dump 로 직접 읽는 행 지문은 쓰지 않는다(deploy 는 영역 안으로 들어가지 않는다, 구조 규칙 1·6)
    has_release = "pointers" in STATE
    if not has_release:
        # 단독 실행: 활성 릴리스가 없으면 survey-service /readyz 는 DB 가 멀쩡해도 503 no_active_release 이다. 이 단계는 그 경우 survey-service 의 복구를 판정하지 못한다
        svcs = [x for x in svcs if x[0] != "survey"]
        print("  (활성 릴리스가 없어 survey-service 는 제외한다: 단계 4 를 포함해 돌려야 survey-service 복구도 확인된다)")
    # 1) 서비스를 거쳐 데이터를 쓴다(question-authoring 자료 등록 -> 확인). 다른 데이터베이스는 행 지문으로 비교한다
    qset = f"qs-{RID}-pgrestart"
    form = (ROOT / "test/fixtures/question-form-v2.txt").read_text()
    upload(qset, form, "pg1.txt")
    before_v = [dict(v) for v in _c3_qa_versions(qset)]
    assert len(before_v) == 1, before_v
    dbs = ["qa", "gate", "ops_log", "ops_failure"] + (["survey"] if has_release else [])
    sidp = f"sess-{RID}-pgturn"
    if has_release:
        # 환자 세션: 값이 하나 확정된 상태에서 DB 를 멈춘다. Trace 전송이 끝나기를 기다려 행 지문이 흔들리지 않게 한다
        rb0 = _c3_survey_ready()[1]
        sidp = _sid(*kiosk("/v1/sessions", {"kind": "SESSION_START", "question_set_id": QS}))
        c, _p1 = public_turn(sidp, "p-1", "네 있어요"); assert c == 200, (c, _p1)
        wait(lambda: _c3_survey_ready()[1]["trace_outbox"]["sent"] - rb0["trace_outbox"]["sent"] >= 1 or None, 30, "p-1 Trace 전송")
        settled(lambda: json.dumps(_c3_survey_ready()[1]["trace_outbox"], sort_keys=True), 30, what="Trace outbox 가 안정(행 지문이 흔들리지 않게)")   # 고정 3초 대신(R4.3)
    ob0 = json.dumps(_c3_survey_ready()[1].get('trace_outbox'), sort_keys=True) if has_release else None
    for k, n in svcs: assert healthy(k), f"{n} /readyz 가 처음부터 200 이 아니다: {ready(k)}"
    # 2) 중지. /healthz(살아 있음)는 유지되고 /readyz 는 비정상이 되어야 한다
    t0 = time.time(); _pg_each("stop", pg)
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
        out_turn = gk_turn(sidp, "p-2", "아니요 없어요", timeout=70)   # DB 가 멈춘 동안 환자 턴
        print(f"    환자 턴(DB 중지 중, gateway 경유): 상태 {out_turn[0]} {out_turn[3]:.1f}s 본문 {str(out_turn[1])[:160]}")
    for k, n in svcs:
        hc = _c3_healthz(k)
        assert hc == 200, f"{n} /healthz 가 DB 중지 중 {hc} (살아 있음 점검은 DB 와 무관해야 한다)"
    # 3) 기동하고 복구를 기다린다
    t1 = time.time(); _pg_each("start", pg)
    _c3_pg_wait(pg)
    t_pg = time.time() - t1
    rec_t = {}
    def all_up():
        for k, n in svcs:
            if k not in rec_t and healthy(k): rec_t[k] = time.time() - t1
        return len(rec_t) == len(svcs)
    wait(all_up, 180, "postgres 기동 뒤 모든 서비스의 /readyz 200 복구", every=1)
    # 4) 데이터 보존과 새 쓰기
    if has_release:
        ob1 = json.dumps(_c3_survey_ready()[1].get('trace_outbox'), sort_keys=True)
        assert ob0 == ob1, f"재시작 전후 survey-service 의 Trace outbox 상태가 다르다: {ob0} -> {ob1}"
    after_v = [dict(v) for v in _c3_qa_versions(qset)]
    assert after_v == before_v, ("문항 버전이 달라졌다", before_v, after_v)
    upload(qset, form.replace("현재 약물 치료 중이십니까?", "지금 약물 치료 중이십니까?"), "pg2.txt")
    assert len(_c3_qa_versions(qset)) == 2, "복구 뒤 새 쓰기(버전 2)가 반영되지 않았다"
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
        policy("5p", "survey-service 의 턴 총 마감 시간(50s)과 DB 접속·문장 상한", "DB 중지 중 환자 턴이 총 마감(50s + 클라이언트 지연 여유) 안에 끝난다", pol_deadline)
        policy("5p", "survey-service 의 turn_id 멱등", "실패한 턴을 같은 turn_id 로 재전송하면 발화가 한 번만 기록된다", pol_once)
    detail = ", ".join(f"{n} {obs[k][1]}({obs[k][0]:.0f}s)->200({rec_t[k]:.0f}s)" for k, n in svcs)
    rec("5p", "REAL", f"postgres 컨테이너 stop -> /readyz 비정상 관찰 -> start (healthy {t_pg:.0f}s) -> 복구. 서비스별 중지 뒤 처음 비정상 코드(경과)->복구 200(기동 뒤 경과): {detail}. /healthz 는 중지 중에도 200. 행 지문 보존: {', '.join(dbs)}. 복구 뒤 새 쓰기 반영(question-authoring 버전 2)." + turn_note + ("" if has_release else " survey-service 는 활성 릴리스가 없는 단독 실행이라 제외."))

# ---- FAULT_MATRIX 1-1절 '4차 근거 대조'의 빈 10칸을 닫는 단계들 (5pn, 5pj, 5g, 5b). 기대는 head/docs/FAULT_POLICY.md 이다 ----
def _pg_ready_wait(pg): _c3_pg_wait(pg)

def _ready_code(k): return _c3_ready(k)   # 서비스 컨테이너 안에서 본 /readyz 코드

def _outbox_drained(timeout=120):
    """survey-service 의 Trace outbox 가 비기를 기다리고 그때의 전송 수(sent)를 돌려준다(계약 SurveyReadyz.trace_outbox.pending/sent).
    왜: ops_log 에는 잡뿐 아니라 ops-feedback(outbox 가 보낸 Trace)도 쓴다. 앞 단계의 DB 장애로 밀린 Trace 가 백오프 뒤 전송되면 ops_log 가 잡과 무관하게 바뀐다.
    /readyz 가 503(활성 릴리스 없음 등)이어도 본문의 trace_outbox 는 계약상 필수라 읽는다. 상한 120초는 측정값이 아니다(outbox 백오프 상한을 deploy 가 알지 못해 넉넉히 잡은 시작값)."""
    def drained():
        try: c, r = _c3_survey_ready()
        except Exception: return None
        ob = r.get("trace_outbox") if isinstance(r, dict) else None
        return (ob["sent"],) if ob and ob["pending"] == 0 else None
    return wait(drained, timeout, "survey-service trace_outbox.pending == 0(밀린 Trace 전송 끝)", every=1)[0]

def _run_ops_job():   # 스케줄러와 같은 호출(compose run --rm job-ops-feedback). 설정은 e2e.sh 가 내보낸 OPS_JOB_CONFIG
    rc, out, err = _c3_job("job-ops-feedback", timeout=120)
    return rc, (out + err)[-300:]

@step('5pn', repos=('survey-service', 'question-authoring', 'release-gate', 'ops-feedback') + _GW, deps=('4',),
      why="STATE['pointers'] 가 없으면 survey-service(A5)를 제외한다(has_release 와 같은 제한). postgres 를 서비스 DB 네트워크에서 disconnect/connect 하고 D1 잡을 한 번 돌린다")
def step5pn():
    title("5pn", "PostgreSQL 네트워크 분리(docker network disconnect, F8) -> 서비스 /readyz 2초 안 503 -> 재연결 -> 사람 개입 없이 200 (FAULT_MATRIX A5·C4·D1·D4·E1 F8)")
    # FAULT_POLICY 11: 분리(F8)는 중지(F1)·멈춤(F2)과 같은 규칙. 연결할 수 없으면 F1 로 분류한다 -> 원칙 5: 의존이 죽으면 /readyz 는 2초 안에 503. 원칙 12: 의존이 돌아오면 사람 개입 없이 /readyz 200
    edges = [("A5", "survey", "survey-service", "db-survey"), ("C4", "gate", "release-gate", "db-gate"), ("D4", "ops", "ops-feedback", "db-ops"), ("E1", "qa", "question-authoring", "db-qa")]
    if "pointers" not in STATE:   # 활성 릴리스가 없으면 survey-service /readyz 는 DB 와 무관하게 503(5p 와 같은 제한)
        edges = [e for e in edges if e[1] != "survey"]; print("  (활성 릴리스가 없어 A5(survey-service)는 제외한다: 단계 4 를 포함해 돌려야 A5 가 확인된다)")
    out = []
    for cell, k, name, net in edges:
        N = f"{a.project}_{net}"
        assert _ready_code(k) == 200, f"{name} /readyz 가 처음부터 200 이 아니다"
        # postgres 쪽에서 그 서비스의 DB 네트워크만 끊는다: stop 과 달리 postgres 는 살아 있고 다른 서비스는 영향이 없다. 서비스 쪽에서는 postgres 이름이 풀리지 않거나 경로가 없다
        pg = f"{a.project}-{_DB_OF[k]}-1"   # 그 서비스 영역의 DB 컨테이너만 그 영역의 DB 망에서 끊는다
        sh([a.docker, "network", "disconnect", N, pg])
        try:
            wait(lambda: _ready_code(k) != 200 or None, 60, f"{name} 분리 뒤 /readyz 비정상", every=1)
            c, b, el = _c3_probe(k, "/readyz")   # 걸린 시간은 서비스 컨테이너 안에서 잰다
            assert c == 503, f"{name} 분리 중 /readyz 가 503 이 아니다: {c} {str(b)[:100]}"
            assert el <= 2.5, f"{name} 분리 중 /readyz 응답 {el:.1f}s (FAULT_POLICY 5: 2초 안, 여유 0.5s)"
            assert _c3_healthz(k) == 200, f"{name} /healthz 가 분리 중 200 이 아니다(원칙 5)"
            body = json.dumps(b, ensure_ascii=False) if isinstance(b, dict) else str(b)
            assert "postgres://" not in body and "password" not in body.lower(), f"{name} /readyz 본문에 접속 정보가 있다"
            job_note = ""
            if net == "db-ops":   # D1: 같은 네트워크를 쓰는 job-ops-feedback 도 DB 에 닿지 못해 조용히 성공하지 않는다
                rc, tail = _run_ops_job(); assert rc != 0, f"D1: 분리 중 job-ops-feedback 이 성공(0)으로 끝났다: {tail}"
                job_note = f", D1 잡 종료 코드 {rc}"
        finally:
            sh([a.docker, "network", "connect", "--alias", _DB_OF[k], N, pg], check=False)   # 시험이 실패해도 분리를 남기지 않는다
        t1 = time.time(); wait(lambda: _ready_code(k) == 200 or None, 90, f"{name} 재연결 뒤 /readyz 200 (사람 개입 없이)", every=1)
        if net == "db-ops":
            rc2, tail2 = _run_ops_job(); assert rc2 == 0, f"D1: 재연결 뒤 job-ops-feedback 이 성공하지 않는다({rc2}): {tail2}"
        out.append(f"{cell} {name}: 503 {el:.1f}s -> 복구 {time.time() - t1:.0f}s{job_note}")
    rec("5pn", "REAL", "postgres 를 서비스별 DB 네트워크에서 disconnect(F8) -> /readyz 503(2초 안)·/healthz 200 -> connect 뒤 자동 200. " + "; ".join(out))

@step('5pj', repos=('ops-feedback', 'deploy:config,compose.yaml,scripts'), deps=(),
      why='STATE 를 읽지 않는다. 스택의 postgres 를 stop/start·pause/unpause 하고 job-ops-feedback 을 run-once 로 돌린다(OPS_JOB_CONFIG)')
def step5pj():
    title("5pj", "DB 중지 중 job-ops-feedback run-once: 실패가 드러나고(조용히 성공 안 함) 복구 뒤 재실행이 멱등으로 성공 (FAULT_MATRIX D1 F1·F4)")
    # FAULT_POLICY 14: 스케줄러/잡 실패는 상태 파일 또는 종료 코드로 드러난다. 원칙 4: DB 는 connect_timeout 이 있어 무한 대기하지 않는다. 원칙 12: 복구 뒤 재전송/재실행이 안전하다
    pg = f"{a.project}-ops-feedback-db-1"   # job-ops-feedback 이 쓰는 영역 DB
    # 잡의 멱등만 보려면 기준(fp0)과 비교(fp1) 사이에 ops_log 의 다른 쓰기 주체(ingest)가 쓰지 않아야 한다. 지문 대상을 잡의 테이블로 좁히는 방식은 쓰지 않았다:
    # 잡도 ops_log 에 쓰고(compose 의 job-ops-feedback 에 OPS_LOG_DATABASE_URL_FILE), 어느 테이블을 쓰는지는 ops-feedback 내부라 deploy 가 정하면 그 영역 스키마에 묶인다.
    # 대신 밀린 Trace 가 다 전송된 뒤 첫 잡이 그것을 처리하고 기준을 잡으며, fp1 에서 전송 수가 그대로임(새 Trace 없음)을 확인한다.
    sent0 = _outbox_drained()
    rc0, tail0 = _run_ops_job(); assert rc0 == 0, f"사전 조건: DB 정상일 때 잡이 성공하지 않는다({rc0}): {tail0}"
    # 멱등은 잡이 두 번 모두 0 으로 끝나고 새 Trace 가 없다는 것(전송 수 불변)으로 본다. ops_log 행 지문(pg_dump 직접 읽기)은 쓰지 않는다(구조 규칙 1·6)
    _pg_each("stop", pg); notes = []
    try:
        t = time.time(); rc, tail = _run_ops_job(); el = time.time() - t
        assert rc != 0, f"DB 중지 중 job-ops-feedback 이 성공(0)으로 끝났다(조용한 성공): {tail}"
        assert el <= 60, f"DB 중지 중 잡이 {el:.0f}s 걸렸다(무한 대기 금지, 원칙 4)"
        notes.append(f"F1 중지: 종료 코드 {rc} ({el:.0f}s)")
    finally:
        _pg_each("start", pg)
    _pg_ready_wait(pg)
    wait(lambda: all(_ready_code(k) == 200 for k in ("ops", "qa", "gate")) or None, 120, "postgres 기동 뒤 서비스 /readyz 200", every=1)
    _pg_each("pause", pg); 
    try:
        t = time.time(); rc, tail = _run_ops_job(); el = time.time() - t
        assert rc != 0, f"DB 무응답(pause) 중 job-ops-feedback 이 성공(0)으로 끝났다: {tail}"
        assert el <= 60, f"DB pause 중 잡이 {el:.0f}s 걸렸다(무한 대기 금지, 원칙 4)"
        notes.append(f"F4 pause: 종료 코드 {rc} ({el:.0f}s)")
    finally:
        _pg_each("unpause", pg, check=False)
    wait(lambda: all(_ready_code(k) == 200 for k in ("ops", "qa", "gate")) or None, 120, "unpause 뒤 서비스 /readyz 200", every=1)
    for i in (1, 2):   # 같은 입력으로 두 번: 둘 다 성공하고 행 지문이 같다(멱등)
        rc, tail = _run_ops_job(); assert rc == 0, f"복구 뒤 재실행 {i} 이 실패했다({rc}): {tail}"
    sent1 = _outbox_drained()
    assert sent1 == sent0, f"5pj 도중 survey-service 가 새 Trace 를 보냈다(sent {sent0}->{sent1}): ops_log 지문 비교가 잡의 멱등만 보지 못한다(시험 전제 위반)"
    rec("5pj", "REAL", "job-ops-feedback run-once: " + "; ".join(notes) + "; 복구 뒤 재실행 2회 모두 0 이고 전송 수 불변(멱등).")

def _registry_container():
    rp = os.environ.get("REGISTRY_PROJECT", "")
    assert rp, "REGISTRY_PROJECT 환경이 없다(e2e.sh 가 내보낸다)"
    return rp   # compose.registry.yaml: container_name: ${REGISTRY_PROJECT}

# 5g 의 상한(초). 모두 측정하지 않은 시작값이다(D125: 측정 최악 + 여유가 되려면 이 호스트에서 재야 한다. 값을 지어내지 않는다). 한 곳에서만 바꾼다.
_PUB_OK_S = 60      # 정상·중지 상태의 게시 한 번(작은 이미지 하나). 측정 안 함
_PUB_HANG_S = 25    # 무응답 게시: PUBLISH_PROBE_TIMEOUT(5초) 보다 충분히 길어야 자체 상한이 먼저 듣는다. 측정 안 함
_PUB_RETRY_S = 90   # 복구 뒤 재시도 성공을 기다리는 상한. 측정 안 함
@step('5g', repos=('deploy:scripts,compose.registry.yaml,locks',), deps=(),
      why='STATE 를 읽지 않는다. e2e.sh 가 띄운 임시 레지스트리(REGISTRY_PROJECT)를 stop/start·pause/unpause 하고 publish-images.sh kiosk-frontend 를 부른다',
      also={'kiosk-frontend': '이 이미지(kiosk-frontend)를 올리는 로컬 레지스트리가 중지·무응답일 때 publish-images.sh 가 실패하고 잠금이 깨지지 않는다(G2 F1·F4)'})
def step5g():
    title("5g", "로컬 레지스트리 중지(F1)·무응답(F4) 중 이미지 게시: 실패하고 잠금이 깨지지 않으며 실행 중 서비스는 영향 없음 -> 복구 뒤 재시도 성공 (FAULT_MATRIX G2 F1·F4)")
    # 기대 출처: FAULT_MATRIX G2 '레지스트리 중단: 새 이미지 적용·롤백이 막히고 이미 떠 있는 컨테이너는 영향 없음'. FAULT_POLICY 원칙 4(무한 대기 금지)·12(복구 뒤 사람 개입 없이 재시도 성공)
    reg = _registry_container(); lock = pathlib.Path(os.environ["DEPLOY_LOCK"])
    def lock_hash(): return hashlib.sha256(lock.read_bytes()).hexdigest()
    pub = lambda t: subprocess.run(["timeout", str(t), "bash", str(ROOT / "scripts/publish-images.sh"), "kiosk-frontend"], capture_output=True, text=True)
    r0 = pub(_PUB_OK_S * 2); assert r0.returncode == 0, f"사전 조건: 레지스트리 정상일 때 게시가 실패한다(종료 코드 {r0.returncode}): 표준 출력 끝 {r0.stdout[-300:]!r} / 표준 오류 끝 {r0.stderr[-300:]!r}"
    h0 = lock_hash(); notes = []
    def live_ok(): return all(_c3_healthz(k) == 200 for k in ("qa", "gate", "ops"))
    sh([a.docker, "stop", reg])
    try:
        r = pub(_PUB_OK_S); assert r.returncode not in (0, 124), f"F1: 레지스트리 중지 중 게시가 {'성공' if r.returncode == 0 else '60s 안에 끝나지 않았다'}(종료 코드 {r.returncode}): 표준 출력 끝 {r.stdout[-200:]!r} / 표준 오류 끝 {r.stderr[-200:]!r}"
        assert lock_hash() == h0, "F1: 실패한 게시가 잠금 파일을 바꿨다"
        assert live_ok(), "F1: 레지스트리 중지가 실행 중 서비스에 영향을 줬다"
        notes.append(f"F1 중지: 게시 종료 코드 {r.returncode}(실패), 잠금 불변, 실행 중 서비스 /healthz 200")
    finally:
        sh([a.docker, "start", reg])
    wait(lambda: pub(_PUB_OK_S).returncode == 0 or None, _PUB_RETRY_S, "레지스트리 기동 뒤 게시 재시도 성공", every=3)
    h1 = lock_hash()
    sh([a.docker, "pause", reg])
    try:
        r = pub(_PUB_HANG_S)   # 무응답: publish-images.sh 는 /v2/ 확인에 자체 상한(PUBLISH_PROBE_TIMEOUT 5초)이 있어 스스로 실패해야 한다. 바깥 timeout 은 그것이 깨졌을 때를 위한 안전망이다. 성공해서는 안 된다
        assert r.returncode != 0, f"F4: 레지스트리 무응답 중 게시가 성공했다(종료 코드 {r.returncode}): {r.stdout[-200:]!r}"
        assert lock_hash() == h1, "F4: 무응답 중 끊긴 게시가 잠금 파일을 바꿨다"
        assert live_ok(), "F4: 레지스트리 pause 가 실행 중 서비스에 영향을 줬다"
        notes.append(f"F4 pause: 게시 종료 코드 {r.returncode}({'스스로 실패(자체 프로브 상한)' if r.returncode != 124 else '자체 상한이 듣지 않아 바깥 timeout 이 끊음'}), 잠금 불변")
    finally:
        sh([a.docker, "unpause", reg], check=False)
    wait(lambda: pub(_PUB_OK_S).returncode == 0 or None, _PUB_RETRY_S, "unpause 뒤 게시 재시도 성공", every=3)
    rec("5g", "REAL", "레지스트리 컨테이너: " + "; ".join(notes) + "; 복구 뒤 재시도 성공.")

@step('5b', repos=('deploy:scripts,config,compose.yaml',), deps=(),
      why='STATE 를 읽지 않는다. question-authoring 영역 백업 잡을 돌리고 그 영역 DB(question-authoring-db)를 stop 한다',
      also={'survey-service': 'survey DB 의 pg_dump 가 백업 도중 영역 DB 중지에서 실패로 보고되고 불완전한 백업을 남기지 않는다(G3 F1)', 'release-gate': 'gate DB 의 pg_dump 가 백업 도중 영역 DB 중지에서 실패로 보고되고 불완전한 백업을 남기지 않는다(G3 F1)', 'ops-feedback': 'ops_log·ops_failure DB 의 pg_dump 가 백업 도중 영역 DB 중지에서 실패로 보고된다(G3 F1)', 'question-authoring': 'qa DB 의 pg_dump 가 백업 도중 영역 DB 중지에서 실패로 보고되고 불완전한 백업을 남기지 않는다(G3 F1)'})
def step5b():
    title("5b", "영역 백업 잡 도중 영역 DB 중지(F1): 잡이 실패로 보고되고 불완전한 백업이 성공으로 남지 않는다 (FAULT_MATRIX G3 F1)")
    # deploy 는 영역 데이터를 직접 꺼내지 않는다(계약 3.4.16, RUNTIME R10.1): 영역의 backup 잡(compose job-question-authoring-backup)을 돌리고 판정은 마지막 줄 BackupJobResult 와 종료 코드로 한다.
    import e2e_backup_jobs as BJ
    pg = f"{a.project}-question-authoring-db-1"
    def run_job():
        r = sh(["bash", str(ROOT / "scripts/run-job.sh"), "job-question-authoring-backup"], env={"DEPLOY_PROJECT": a.project}, check=False)
        return r.returncode, BJ.last_json_line(r.stdout or "")
    _pg_each("stop", pg)
    try:
        rc, res = run_job()
    finally:
        _pg_each("start", pg)
    _pg_ready_wait(pg)
    assert rc != 0, f"영역 DB 중지 중 백업 잡이 성공(0)으로 끝났다(조용한 성공): {res}"
    assert res is None or res.get("status") != "ok", f"영역 DB 중지 중 백업 잡이 status=ok 를 냈다: {res}"
    wait(lambda: _ready_code("qa") == 200 or None, 120, "DB 기동 뒤 question-authoring /readyz 200", every=1)
    rc2, res2 = run_job()   # 복구 뒤 같은 잡을 다시 돌리면 성공한다(멱등, 다음 주기에 한 번 다시 R10.12)
    assert rc2 == 0 and res2 and res2.get("status") == "ok", f"DB 기동 뒤 백업 잡 재실행이 성공하지 않았다({rc2}): {res2}"
    rec("5b", "REAL", f"영역 DB 중지 중 백업 잡 종료 코드 {rc}, status={(res or {}).get('status')} (실패로 보고); DB 기동 뒤 재실행 status=ok.")

_RG_PROBE = """import json, os, ssl, urllib.request, urllib.error
# 추론 서버 pod 의 네트워크 공간에서, 추론 서버와 같은 길로: 자기 영역 게이트웨이 출구(CONNECT, R1.8) -> https://release-gate(release-gate 영역 게이트웨이). OUT-FILE 루트만 믿는다(검증을 끄지 않는다)
ctx = ssl.create_default_context(cadata=ROOT_PEM)
op = urllib.request.build_opener(urllib.request.ProxyHandler({'https': EGRESS}), urllib.request.HTTPSHandler(context=ctx))
good = open('/run/secrets/gate-read-model-serving').read().strip()   # 값은 출력하지 않는다
res = {}
for key, path, tok in CASES:
    h = {'Authorization': 'Bearer ' + (good if tok == 'good' else 'wrong-token')} if tok else {}
    try:
        with op.open(urllib.request.Request('https://release-gate' + path, headers=h), timeout=30) as r: code, body, ct = r.status, r.read(), r.headers.get('Content-Type', '')
    except urllib.error.HTTPError as e: code, body, ct = e.code, e.read(), e.headers.get('Content-Type', '')
    res[key] = [code, ct, len(body), body[:300].decode(errors='replace') if code != 200 else '']
print(json.dumps(res))
"""

@step('5L', repos=('model-runtime', 'release-gate', 'boundary-contracts') + _GW, deps=('4',),
      why="D72·ADR 0070: 다른 호스트 역할의 추론 서버(별도 compose 프로젝트)는 계약 R1.5 대로 OUT-FILE 루트와 서비스 토큰(gate-read-model-serving)으로 "
          "release-gate 영역 게이트웨이에 바로 간다(자기 영역 게이트웨이 출구 R1.8). 공개 입구에는 기계 호출자 경로가 없다(R3.23, 4.0.0). release-gate 는 호스트에 게시되지 않는다(D123)")
def step5L():
    title("5L", "추론 서버 위치 독립(D72): release-gate 영역 게이트웨이로 바로(R1.5), 공개 입구에 기계 경로 없음(R3.23)")
    if "pointers" not in STATE: rec("5L", "BLOCKED", _P4); return
    ms = SB.inference_url(); assert ms, "다른 호스트 역할의 추론 서버가 없다(e2e.sh 가 compose.inference.yaml 을 별도 프로젝트로 띄운다)"
    assert a.out_file, "OUT-FILE 폴더(--out-file)가 없다: e2e.sh 가 export-out-files.sh 로 만들어 넘긴다(R1.5)"
    rid = STATE["pointers"][-1]["release_id"]
    # 0) OUT-FILE(R1.5): 받는 쪽처럼 SHA-256 을 대조하고, hosts 표에 `<주소> release-gate` 줄이 있다
    of = pathlib.Path(a.out_file)
    sums = dict(reversed(l.split(None, 1)) for l in (of / "SHA256SUMS").read_text().splitlines() if l.strip())
    assert set(sums) == {"root_ca.crt", "hosts"}, f"OUT-FILE SHA256SUMS 의 파일 목록: {sorted(sums)}"
    for n, h in sums.items(): assert hashlib.sha256((of / n).read_bytes()).hexdigest() == h.strip(), f"OUT-FILE {n} 의 SHA-256 이 SHA256SUMS 와 다르다"
    hosts = [l.split() for l in (of / "hosts").read_text().splitlines() if l.strip()]
    assert any(len(x) == 2 and x[1] == "release-gate" for x in hosts), f"OUT-FILE hosts 표에 '<주소> release-gate' 줄이 없다: {hosts}"
    root_pem = (of / "root_ca.crt").read_text()
    # 1) 추론 서버가 ready(release 도달 포함). 서버는 OUT-FILE 루트 + 서비스 토큰으로 release-gate 영역 게이트웨이에만 닿는다
    try:
        with urllib.request.urlopen(ms + "/readyz", timeout=10) as r: rs, rbody = r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e: rs, rbody = e.code, ""
    assert rs == 200, f"다른 호스트 역할의 추론 서버 /readyz 가 {rs}"
    assert json.loads(rbody or "null").get("status") == "ready", f"추론 서버 /readyz 본문이 ready 가 아니다(상태 코드만 보지 않는다): {rbody[:120]!r}"
    # 2) 같은 길(추론 서버 pod 의 출구 -> release-gate 영역 게이트웨이)로 서비스 토큰: active-pointer 200·bundle 200. 토큰 없음·틀림은 받는 서비스가 401(R3.23)
    env = json.loads(subprocess.run([a.docker, "inspect", a.ms_container or f"{a.project}-inf-model-serving-1", "--format", "{{json .Config.Env}}"],
                                    capture_output=True, text=True, check=True).stdout or "[]") or []
    egress = next((kv.split("=", 1)[1] for kv in env if kv.startswith("OPENIT_EGRESS_PROXY=")), "")   # 주소(비밀 아님)만 꺼낸다. 다른 값은 읽지 않는다
    assert egress.startswith("http://127.0.0.1:"), f"추론 서버의 OPENIT_EGRESS_PROXY 가 loopback 출구가 아니다(R1.8): {egress!r}"
    cases = [("ap", "/v1/active-pointer", "good"), ("bundle", f"/v1/releases/{rid}/bundle", "good"), ("none", "/v1/active-pointer", ""), ("wrong", "/v1/active-pointer", "wrong")]
    out = SB.exec_py("model-serving", f"ROOT_PEM = {root_pem!r}\nEGRESS = {egress!r}\nCASES = {cases!r}\n" + _RG_PROBE, timeout=120)
    got = json.loads(out.strip().splitlines()[-1])
    assert got["ap"][0] == 200, f"서비스 토큰 /v1/active-pointer (release-gate 영역 게이트웨이): {got['ap']}"
    assert got["bundle"][0] == 200 and got["bundle"][2] > 0, f"서비스 토큰 번들 (release-gate 영역 게이트웨이): {got['bundle']}"
    assert got["none"][0] == 401, f"토큰 없는 요청은 release-gate 가 401 로 거절해야 한다(R3.23): {got['none']}"
    assert got["wrong"][0] == 401, f"틀린 토큰은 release-gate 가 401 로 거절해야 한다(R3.23): {got['wrong']}"
    # 3) 공개 입구에는 기계 호출자 경로가 없다(R3.23, 4.0.0): 같은 서비스 토큰을 공개 입구에 내면 200 이 아니다(OIDC 토큰이 아니라 401, 내보내지 않는 경로는 404)
    tok = (pathlib.Path(a.secrets) / "tokens" / "gate-read-model-serving").read_text().strip()
    st_pa, _, _ = SB.gw_request("GET", "/v1/active-pointer", token=tok)
    st_pb, _, _ = SB.gw_request("GET", f"/v1/releases/{rid}/bundle", token=tok)
    assert st_pa in (401, 404), f"공개 입구가 서비스 토큰으로 /v1/active-pointer 에 {st_pa} 를 냈다(기계 경로가 없어야 한다, R3.23)"
    assert st_pb in (401, 404), f"공개 입구가 서비스 토큰으로 번들에 {st_pb} 를 냈다(기계 경로가 없어야 한다, R3.23)"
    # 4) release-gate 는 호스트에 게시되지 않는다(시험용 문 없음): 게시 포트는 pod(release-gate-net)만 가질 수 있고, 앱·영역 게이트웨이는 그 공간에 붙는다
    for svc in ("release-gate-net", "release-gate", "release-gate-gw"):
        r = subprocess.run([a.docker, "port", f"{a.project}-{svc}-1"], capture_output=True, text=True)
        assert r.returncode == 0, f"{svc} 컨테이너를 찾지 못했다: {r.stderr.strip()[:200]}"
        assert r.stdout.strip() == "", f"{svc} 가 호스트에 게시돼 있다: {r.stdout.strip()}"
    rec("5L", "REAL", f"OUT-FILE(R1.5) SHA-256 대조·hosts 표 release-gate 줄; 다른 호스트 역할 추론 서버 ready(release 도달); 추론 서버 pod 의 출구(R1.8) -> release-gate 영역 게이트웨이: "
        f"서비스 토큰 active-pointer 200·bundle 200({got['bundle'][2]}바이트), 무토큰 401·틀린 토큰 401; 공개 입구에 같은 토큰: active-pointer {st_pa}·bundle {st_pb}(기계 경로 없음, R3.23); release-gate 호스트 게시 없음 (D72·ADR 0070)")


def _kiosk_device_config(dev):
    """키오스크 앱이 기기에서 읽는 /config.json 과 같은 파일(secrets/kiosk-config/<ID>.json, kiosk-add-device.sh 가 만든다)."""
    return json.loads((pathlib.Path(a.secrets) / "kiosk-config" / f"{dev}.json").read_text())

def _place_question_set(dev, qset):   # 운영자가 하는 일 그대로: kiosk-add-device.sh place <기기> <문진표 ID>|-  (ADR 0052)
    sh(["bash", str(ROOT / "scripts/kiosk-add-device.sh"), "place", dev, qset], env={"SECRETS_DIR": a.secrets})

@step('5k', repos=('survey-service', 'kiosk-frontend', 'question-authoring') + _GW, deps=('1', '4'),
      why="STATE['qs'],['qsb'](step1)·['releases'],['pointers'](step4)를 읽는다. 기기 설정 파일(secrets/kiosk-config)과 kiosk-add-device.sh 가 입력이다. " + _P4)
def step5k():
    title("5k", "문진표 둘이 함께 활성: 기기 배치 문진표로 자동 시작, 배치 없는 기기는 목록에서 골라 시작, 결과에 문진표 ID·제목, 모르는 문진표는 400 (계약 3.3.0)")
    if "pointers" not in STATE or "qsb" not in STATE: rec("5k", "BLOCKED", "활성 릴리스(단계 4)나 문진표 B(단계 1)가 없다"); return
    new = STATE["releases"]["2"]
    wait(lambda: (lambda cr: cr[0] == 200 and cr[1].get("active_release") == new)(_c2_ready()), 300, f"survey가 릴리스 {new} 적재", every=3)
    rel = _c1_release(new); validate("ReleaseManifest", rel)
    assert sorted(x["id"] for x in rel["question_sets"]) == sorted([QS, QSB]) and {x["id"]: x["title"] for x in rel["question_sets"]} == {QS: QS_TITLE, QSB: QSB_TITLE}, ("활성 릴리스의 문진표", rel["question_sets"])
    # 기기 배치: A 는 health-screening, B 는 배치 없음(운영자 명령으로 쓴 기기 설정 파일을 키오스크 앱처럼 읽는다)
    _place_question_set("e2e-a", QS); _place_question_set("e2e-b", "-")
    cfg_a, cfg_b = _kiosk_device_config("e2e-a"), _kiosk_device_config("e2e-b")
    validate("DeviceConfig", cfg_a); validate("DeviceConfig", cfg_b)
    assert cfg_a.get("question_set_id") == QS and "question_set_id" not in cfg_b, (cfg_a.get("question_set_id"), "question_set_id" in cfg_b)
    tA, tB = dev_tok("e2e-a"), dev_tok("e2e-b")
    def dk(tok, method, path, body=None): c, b, _h = _c1_gw(method, path, token=tok, body=body); return c, b
    def state_dk(tok, sid):   # 서버가 0.5초보다 잦은 상태 조회를 429 로 막는다(state_of 와 같은 이유)
        for _ in range(8):
            time.sleep(0.7); c, r = dk(tok, "GET", f"/v1/sessions/{sid}/state")   # 속도 제한 간격: 서버가 0.5초보다 잦은 상태 조회를 429 로 막는다
            if c != 429: return c, r
        return c, r
    # 활성 문진표 목록(I10): 기기 토큰이 필요하다(세션과 같은 인증). 활성 릴리스의 문진표 둘이 ID·제목·버전과 함께 나온다
    assert _c1_gw("GET", "/v1/question-sets")[0] == 401, "문진표 목록이 기기 토큰 없이 열려 있다"
    c, lst = dk(tB, "GET", "/v1/question-sets"); assert c == 200, ("문진표 목록", c, str(lst)[:150])
    items = {i["question_set_id"]: i for i in lst["items"]}
    assert set(items) == {QS, QSB} and items[QS]["title"] == QS_TITLE and items[QSB]["title"] == QSB_TITLE and all(i.get("version") for i in items.values()), lst
    # 문진표가 둘인데 고르지 않으면 400, 모르는 문진표 ID 도 400(INVALID_RECORD, details.reason UNKNOWN_QUESTION_SET)
    c, b = dk(tB, "POST", "/v1/sessions", {"kind": "SESSION_START"}); assert c == 400 and b.get("code") == "INVALID_RECORD" and (b.get("details") or {}).get("reason") == "QUESTION_SET_REQUIRED", ("문진표 둘인데 고르지 않은 시작", c, str(b)[:150])
    c, b = dk(tB, "POST", "/v1/sessions", {"kind": "SESSION_START", "question_set_id": "no-such-set"})
    assert c == 400 and b.get("code") == "INVALID_RECORD" and (b.get("details") or {}).get("reason") == "UNKNOWN_QUESTION_SET", ("모르는 문진표로 시작", c, str(b)[:200])
    # 두 세션: A 는 배치된 문진표로 자동 시작(고르는 화면 없음), B 는 목록에서 순서 B 를 골라 시작
    c, st_a = dk(tA, "POST", "/v1/sessions", {"kind": "SESSION_START", "question_set_id": cfg_a["question_set_id"]}); sa = _sid(c, st_a); validate_survey("FrontendInput", st_a)
    c, st_b = dk(tB, "POST", "/v1/sessions", {"kind": "SESSION_START", "question_set_id": QSB}); sb = _sid(c, st_b); validate_survey("FrontendInput", st_b)
    assert st_a["response_text"] != st_b["response_text"], "두 문진표의 첫 질문이 같다(순서 B 의 첫 문항은 Q3 라 달라야 한다)"
    # 끝까지: 기존 턴 스크립트('네 있어요'/'아니요 없어요' 번갈아). 첫 답이 저장된 칸의 문항이 문진표의 첫 문항이다(순서는 문진표 자신에게서 나온다)
    firsts = {}
    for sid, tok, want in ((sa, tA, QS_FIRST), (sb, tB, QSB_FIRST)):
        for i in range(1, 121):
            c, r = dk(tok, "POST", f"/v1/sessions/{sid}/turns", {"session_id": sid, "kind": "UTTERANCE", "utterance": ("네 있어요", "아니요 없어요")[i % 2], "turn_id": f"k-{i}"})
            assert c == 200, (sid, i, c, str(r)[:150]); validate_survey("FrontendInput", r)
            if i == 1:
                vals = _c2_staff("GET", f"/v1/staff/sessions/{sid}")[1]["values"]
                firsts[sid] = vals[0]["key"] if vals else None
                assert firsts[sid] and firsts[sid].startswith(want), (f"첫 문항이 {want} 가 아니다", sid, [v["key"] for v in vals][:3])
            cs, stt = state_dk(tok, sid)
            if cs == 200 and stt["state"] == "ENDED": break
        else:
            raise AssertionError(f"120턴 안에 문진이 끝나지 않았다: {sid}")
        c, en = dk(tok, "POST", f"/v1/sessions/{sid}/end", {"session_id": sid, "kind": "SESSION_END"}); assert c == 200, ("종료", sid, c, str(en)[:100])
    # 결과: 세션마다 문진표 ID·제목이 맞다(result-reader 와 clinician 이 같은 값을 본다), 의사 확인 표시(5r 과 같은 경로)
    for sid, qid, title_ in ((sa, QS, QS_TITLE), (sb, QSB, QSB_TITLE)):
        c, rs, _ = _c2_in_json("survey-service", "GET", f"/v1/results/{sid}", TOK("survey-result-reader")); assert c == 200, (sid, c, rs)
        validate_survey("SessionResult", rs)
        assert rs["question_set_id"] == qid and rs["question_set_title"] == title_ and rs["status"].startswith("ENDED"), (sid, rs["question_set_id"], rs["question_set_title"], rs["status"])
        c, rc, _ = _c2_raw("GET", f"/v1/results/{sid}", basic=_C2_CLINICIAN); assert c == 200 and rc["question_set_id"] == qid and rc["question_set_title"] == title_, (sid, c, str(rc)[:150])
        c, ak, _ = _c2_raw("POST", f"/v1/results/{sid}/ack", {}, basic=_C2_CLINICIAN); assert c == 200 and ak.get("acknowledged_by") == _C2_CLINICIAN, (sid, c, str(ak)[:150])
        c, sv = _c2_staff("GET", f"/v1/staff/sessions/{sid}"); validate_survey("StaffSessionView", sv)
        assert sv["question_set_id"] == qid and sv["question_set_title"] == title_, (sid, sv["question_set_id"], sv["question_set_title"])
    rec("5k", "REAL", f"문진표 둘 활성(릴리스 {new}): 기기 A 배치 {QS} 로 자동 시작(첫 문항 {QS_FIRST}), 배치 없는 기기 B 는 GET /v1/question-sets 에 둘({QS}, {QSB})이 나오고 {QSB} 로 시작(첫 문항 {QSB_FIRST}), 고르지 않은 시작 400 INVALID_RECORD/QUESTION_SET_REQUIRED, 모르는 ID 400 INVALID_RECORD/UNKNOWN_QUESTION_SET, 두 세션 끝까지, 결과(result-reader·clinician·직원 조회)에 문진표 ID·제목 일치, clinician 확인 표시")


STEPS = [("1", step1), ("2", step2), ("3", step3), ("4", step4), ("5", step5), ("5L", step5L), ("5s", step5s), ("5f", step5f), ("5c", step5c), ("5a", step5a), ("5d", step5d), ("5q", step5q), ("5w", step5w), ("5u", step5u), ("5m", step5m), ("5r", step5r), ("5k", step5k), ("5o", step5o), ("5n", step5n), ("6", step6), ("7", step7), ("7d", step7d), ("8", step8), ("5p", step5p), ("5pn", step5pn), ("5pj", step5pj), ("5g", step5g), ("5b", step5b), ("demo4", demo4), ("demo_activate", demo_activate), ("demo_active", demo_active), ("demo_swap", demo_swap), ("diag", diag)]
import e2e_plan as PLAN
only = set(filter(None, a.only.split(",")))
TIMES = []
order = [n for n, _ in STEPS if not (n.startswith("demo") and n not in only) and (not only or n in only)]
_miss = PLAN.missing([n for n, _ in STEPS], PLAN.STEP_DECLS)
if _miss: raise SystemExit(f"입력 선언이 없는 단계: {_miss} (e2e_steps.py 의 단계 함수에 @step 을 단다)")
LAST = PLAN.load_last_pass(); CUR = {n: PLAN.input_hash(n) for n in order}
if a.changed_only:
    sel, why = PLAN.select_changed(order, PLAN.STEP_DECLS, CUR, LAST)
    print("== --changed-only 선택: " + ", ".join(f"{n}({why[n]})" for n in order if n in sel) + " / 제외: " + (", ".join(n for n in order if n not in sel) or "없음"), flush=True)
    order = [n for n in order if n in sel]
STATUS = {}   # 단계 -> 'FAIL' | 'SKIP:<뿌리>' | 'OK'. 선행이 FAIL 이면 의존 단계는 FAIL 이 아니라 SKIP 이다(연쇄 잡음, ADR 0030)
STOPPED = False
for n, fn in STEPS:
    if n not in order: continue
    if STOPPED: continue
    root = PLAN.skip_root(n, STATUS)
    if root:
        STATUS[n] = "SKIP:" + root; rec(n, "SKIP", f"SKIP(선행 실패: 단계 {root})"); continue
    t0 = time.time(); k0 = len(RESULTS); CUR_STEP[0] = n
    try: fn()
    except AssertionError as e: rec(fn.__name__, "FAIL", str(e)); diag_write("steps-traceback.log", f"## 단계 {n} ({fn.__name__}) AssertionError\n{traceback.format_exc()}\n")
    except Exception as e: rec(fn.__name__, "FAIL", f"{type(e).__name__}: {e}"); diag_write("steps-traceback.log", f"## 단계 {n} ({fn.__name__}) {type(e).__name__}\n{traceback.format_exc()}\n")
    failed = any(r[1] == "FAIL" for r in RESULTS[k0:])
    STATUS[n] = "FAIL" if failed else "OK"
    if not failed and any(r[1] in ("REAL", "TEST-SUB") for r in RESULTS[k0:]): LAST[n] = CUR[n]   # BLOCKED 만 있으면 PASS 가 아니다
    TIMES.append((n, time.time() - t0)); print(f"  (소요 {TIMES[-1][1]:.1f}s)", flush=True)
    if failed and a.fail_fast:
        STOPPED = True; print(f"== --fail-fast: 단계 {n} 가 FAIL 이라 중단한다. 미실행: " + ", ".join(m for m, _ in STEPS if m in order and m not in STATUS), flush=True)
if not os.environ.get("E2E_NO_LAST_PASS"): PLAN.save_last_pass(LAST)   # 시험이 실제 기록을 건드리지 않게 끌 수 있다
print("\n== 요약 (단계 1~8)")
for s, st, d in RESULTS: print(f"  {str(s):>4} {st:9} {d[:170]}")
print("\n== 단계별 소요 시간 (1~8)")
for n, sec in TIMES: print(f"  {sec:7.1f}s  단계 {n}")
print(f"  {sum(x for _, x in TIMES):7.1f}s  합계")
(WORK / "steps.json").write_text(json.dumps([list(r) for r in RESULTS], ensure_ascii=False, indent=1))
print(f"  PASS-계열 {sum(1 for r in RESULTS if r[1] not in ('FAIL','SKIP','BLOCKED'))} / FAIL {sum(1 for r in RESULTS if r[1]=='FAIL')} / SKIP {sum(1 for r in RESULTS if r[1]=='SKIP')} / BLOCKED {sum(1 for r in RESULTS if r[1]=='BLOCKED')} (행 기준)")
sys.exit(1 if any(r[1] == "FAIL" for r in RESULTS) else 0)
