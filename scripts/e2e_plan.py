#!/usr/bin/env python3
"""E2E 단계의 입력 선언, 선행 실패 전파(SKIP), 입력 해시 기록, --changed-only 선택. Docker 없이 시험한다(test_e2e_plan.py).
왜 이렇게 하는가: docs/adr/0030-e2e-skip-and-input-hash.md.

선언 한 줄(Decl)의 뜻
  repos : 이 단계가 결과를 의존하는 소스 리포(이미지는 build-images.sh 가 이 리포들의 HEAD 로 만든다). 'deploy:경로,...' 는 deploy 안의 그 경로만 본다.
  deps  : 앞 단계의 상태(STATE/실행 중 스택)에 의존하면 그 단계 이름. 없으면 ().  UNKNOWN 이면 확인하지 못한 것이다(SKIP 근거로 쓰지 않는다).
  solo  : True 는 '이 단계만 새 스택에서 따로 돌려 PASS 하는 것을 확인했다'는 뜻. 지금은 아무 단계도 확인하지 않았으므로 전부 False 이고,
          False 인 단계는 --changed-only 가 항상 고른다.
  why   : deps 와 repos 를 이렇게 선언한 근거(코드 위치). 근거가 없으면 deps=UNKNOWN 으로 쓴다.
"""
import ast, hashlib, json, os, pathlib, re, subprocess, sys
from dataclasses import dataclass

UNKNOWN = "미확인"
HERE = pathlib.Path(__file__).resolve().parent
DEPLOY = HERE.parent
WORKSPACE = DEPLOY.parent
LAST_PASS_FILE = DEPLOY / "state" / "e2e-last-pass.json"   # state/ 는 .gitignore 이다(리포 밖). 단계별 마지막 PASS 때의 입력 해시


@dataclass(frozen=True)
class Decl:
    repos: tuple
    deps: object          # tuple 또는 UNKNOWN
    why: str
    solo: bool = False


_GW = ("deploy:config,compose.yaml,compose.test.yaml,test",)   # 게이트웨이(Caddyfile·계정)를 거치는 단계는 deploy 의 설정도 입력이다
_P4 = "step4 가 STATE['pointers']/['releases'] 를 쓰고 이 단계가 '\"pointers\" not in STATE' 로 BLOCKED 처리한다(e2e_steps.py 의 같은 이름 함수 앞부분)"

# 키는 e2e_steps.py 의 STEPS 이름과 같다(자체 시험이 누락을 검출한다).
STEP_DECLS = {
    "1": Decl(("question-authoring", "survey-service", "boundary-contracts"), (), "step1 은 STATE 를 읽지 않고 qa 에 HTTP 로 올린다(STATE['qs'],['qsu'] 를 씀). 실행 중 스택의 question-authoring 은 필요하다"),
    "2": Decl(("synthetic-data", "survey-service"), ("1",), "step2 는 run_import 로 STATE['qs'](step1 이 씀)를 읽는다(imp_config)"),
    "3": Decl(("model-lab", "model-runtime", "survey-service", "boundary-contracts"), ("1", "2"), "step3 는 make_packages 에서 STATE['dataset'](step2)·['qs'](step1)를 읽는다"),
    "4": Decl(("release-gate", "question-authoring", "survey-service", "model-lab", "boundary-contracts") + _GW, ("1", "3"), "step4 는 STATE['lora'](step3)·['qs'],['qsu'](step1)를 읽고 'lora' 가 없으면 BLOCKED 한다(e2e_steps.py step4 앞부분)"),
    "5": Decl(("survey-service", "model-runtime", "turn-engine", "kiosk-frontend") + _GW, ("3", "4"), "step5 는 STATE['pointers'],['releases'](step4)·['system_prompt'](step3)를 읽는다. " + _P4),
    "5s": Decl(("survey-service", "model-runtime") + _GW, ("4",), "step5s 는 STATE['containers_before_swap'],['releases'](step4)를 읽는다(e2e_steps.py step5s 앞부분)"),
    "5f": Decl(("survey-service", "ops-feedback", "kiosk-frontend") + _GW, ("4",), "STATE['pointers'] 를 읽는다. " + _P4),
    "5c": Decl(("survey-service", "model-runtime") + _GW, ("4",), "STATE['pointers'],['releases'] 를 읽는다. " + _P4),
    "5a": Decl(("question-authoring", "admin-console") + _GW, UNKNOWN, "step5a 는 STATE 를 읽지 않는다. 그러나 앞 단계가 만든 저자 계정·문항 상태에 의존하는지는 코드를 읽어 확정하지 못했다"),
    "5d": Decl(("survey-service", "kiosk-frontend") + _GW, ("4",), "STATE['pointers'] 를 읽는다. " + _P4),
    "5q": Decl(("survey-service", "kiosk-frontend") + _GW, ("4",), "STATE['pointers'] 를 읽고 survey-service 를 stop/start 한다(끝에 되돌린다). " + _P4),
    "5w": Decl(("survey-service", "kiosk-frontend") + _GW, ("4",), "STATE['pointers'] 를 읽고 survey-service 를 pause/unpause 한다. " + _P4),
    "5u": Decl(("release-gate", "survey-service") + _GW, UNKNOWN, "step5u 는 STATE 를 읽지 않는다. 활성 릴리스가 있어야 하는지는 코드를 읽어 확정하지 못했다"),
    "5m": Decl(("survey-service", "model-runtime", "kiosk-frontend") + _GW, ("4",), "STATE['pointers'] 를 읽고 model-serving 을 pause 한다. " + _P4),
    "5r": Decl(("survey-service", "kiosk-frontend") + _GW, ("4",), "STATE['pointers'] 를 읽는다. " + _P4),
    "5n": Decl(("survey-service", "kiosk-frontend", "boundary-contracts") + _GW, ("4",), "STATE['pointers'] 를 읽는다(e2e_steps.py step5n 앞부분). 위험 문구는 빌드 사본의 survey-service risk_rules.py 에서 읽고, 기기 e2e-a·e2e-b 토큰을 쓴다(5d 와 같은 gen-secrets.sh 구성). " + _P4),
    "6": Decl(("ops-feedback", "survey-service", "boundary-contracts"), ("1", "4"), "step6 은 STATE['qs'](step1)·['releases'](step4)를 읽는다"),
    "7": Decl(("synthetic-data", "ops-feedback", "question-authoring", "boundary-contracts") + _GW, ("1", "2", "6"), "step7 은 STATE['cases'],['extract_input'](step6)·['dataset'](step2)·['qs'](step1)를 읽는다"),
    "8": Decl(("release-gate", "survey-service", "kiosk-frontend", "boundary-contracts"), ("1", "4", "6"), "step8 은 STATE['cases'](step6)·['pointers'],['releases'](step4)·['qs'](step1)를 읽는다"),
    "5p": Decl(("survey-service", "question-authoring", "release-gate", "ops-feedback") + _GW, ("4",), "STATE['pointers'] 가 없으면 활성 릴리스 없이 일부만 시험한다(has_release). postgres 를 stop/start 한다"),
    "demo4": Decl(("release-gate", "model-lab"), UNKNOWN, "demo.sh 전용. E2E 기본 실행에 들어가지 않는다"),
    "demo_activate": Decl(("release-gate",), UNKNOWN, "demo.sh 전용"),
    "demo_active": Decl(("release-gate",), UNKNOWN, "demo.sh 전용"),
    "demo_swap": Decl(("release-gate",), UNKNOWN, "demo.sh 전용"),
    "diag": Decl(("release-gate",), UNKNOWN, "demo.sh 전용 진단"),
}

# e2e.sh 의 구간. 구간 안의 항목 단위 선행 관계는 e2e.sh 의 chk_dep 호출이 갖는다(여기는 구간 단위 선언).
SECTION_DECLS = {
    "prep": Decl(("deploy:scripts,compose.yaml,locks", "survey-service", "question-authoring", "ops-feedback", "release-gate", "model-lab", "model-runtime", "kiosk-frontend", "admin-console"), (), "이미지 빌드·레지스트리·잠금. 실패하면 e2e.sh 가 중단한다(abort_if_failed)"),
    "s9-front": Decl(_GW, ("prep",), "compose up 과 도달·차단·라벨 점검은 준비의 digest 이미지에 의존한다"),
    "s1-8": Decl(_GW, ("s9-front",), "e2e_steps.py 는 s9-front 가 띄운 스택에서 돈다. 단계별 선언은 STEP_DECLS"),
    "s9-sched": Decl(("deploy:config,scripts",), ("s9-front",), "run-job 은 스택과 steps.log(단계 4 출력)를 쓴다"),
    "s9-backup": Decl(("deploy:scripts,config",), ("s1-8",), "백업 대상은 단계 1~8 이 쓴 데이터다. 서비스를 멈추고 볼륨을 지운다"),
    "s9-rollback": Decl(("survey-service", "deploy:scripts,locks"), ("s9-backup",), "복구한 스택에서 새 빌드를 올린다"),
}


# ---------------------------------------------------------------- 검증
def validate(decls, order=None):
    """선언 자체의 문제 목록. order 가 있으면 deps 가 실행 순서상 앞에 있는지도 본다."""
    bad = []
    for k, d in decls.items():
        if not d.why.strip(): bad.append(f"{k}: why(근거)가 비었다")
        if not d.repos: bad.append(f"{k}: repos 가 비었다")
        if d.deps != UNKNOWN:
            for x in d.deps:
                if x not in decls: bad.append(f"{k}: deps 의 '{x}' 는 선언에 없다")
                elif order and k in order and x in order and order.index(x) > order.index(k): bad.append(f"{k}: deps '{x}' 가 실행 순서상 뒤에 있다")
    def cyc(k, path):
        d = decls[k].deps
        if d == UNKNOWN: return None
        for x in d:
            if x in path: return path + [x]
            if x in decls:
                r = cyc(x, path + [x])
                if r: return r
    for k in decls:
        c = cyc(k, [k])
        if c: bad.append(f"순환 의존: {' -> '.join(c)}"); break
    return bad


def missing(names, decls):
    """실행하는 단계 중 선언이 없는 것."""
    return [n for n in names if n not in decls]


def steps_in_source(path=HERE / "e2e_steps.py"):
    """e2e_steps.py 의 STEPS 목록을 import 없이(argparse 가 돈다) 읽는다."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "STEPS" for t in node.targets):
            return [e.elts[0].value for e in node.value.elts]
    raise SystemExit("e2e_steps.py 에서 STEPS 를 찾지 못했다")


# ---------------------------------------------------------------- SKIP 전파
def skip_root(step, status, decls=STEP_DECLS):
    """선행(deps, 확인된 것만)이 FAIL 이거나 SKIP 이면 그 뿌리 항목명을 돌려준다. 없으면 None.
    status: {단계: 'FAIL'|'SKIP:<뿌리>'|그 밖(통과·BLOCKED 등)}. 미확인 deps 는 근거가 아니므로 전파하지 않는다."""
    d = decls.get(step)
    if d is None or d.deps == UNKNOWN: return None
    for x in d.deps:
        s = status.get(x)
        if s == "FAIL": return x
        if isinstance(s, str) and s.startswith("SKIP:"): return s[5:]
    return None


# ---------------------------------------------------------------- 입력 해시
def _git(repo_dir, *args):
    return subprocess.run(["git", "-C", str(repo_dir), *args], capture_output=True, text=True).stdout.strip()


def repo_state(spec, workspace=WORKSPACE):
    """'리포' 는 HEAD 커밋(+추적 파일 변경 해시), '리포:경로,...' 는 그 경로의 HEAD 트리와 변경만."""
    name, _, paths = spec.partition(":")
    d = workspace / name
    if not (d / ".git").exists() and not (d / ".git").is_file(): return f"{spec}=없음"
    ps = [p for p in paths.split(",") if p]
    head = ",".join(_git(d, "rev-parse", f"HEAD:{p}") for p in ps) if ps else _git(d, "rev-parse", "HEAD")
    diff = _git(d, "diff", "HEAD", "--", *ps) if ps else _git(d, "diff", "HEAD")
    return f"{spec}={head}" + (f"+dirty:{hashlib.sha256(diff.encode()).hexdigest()[:12]}" if diff else "")


def func_closure_hash(step, path=HERE / "e2e_steps.py"):
    """단계 함수와 그것이 부르는 최상위 함수들의 소스 해시(시험 코드가 바뀌면 입력이 바뀐 것이다). 모듈 상수·픽스처 파일은 포함하지 않는다(한계, ADR)."""
    src = path.read_text(encoding="utf-8"); tree = ast.parse(src)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    fn = dict(STEPS_FN(path)).get(step)
    if fn is None or fn not in funcs: return "함수없음"
    seen, todo = set(), [fn]
    while todo:
        f = todo.pop()
        if f in seen: continue
        seen.add(f)
        for n in ast.walk(funcs[f]):
            if isinstance(n, ast.Name) and n.id in funcs and n.id not in seen: todo.append(n.id)
    text = "\n".join(ast.get_source_segment(src, funcs[f]) or "" for f in sorted(seen))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def STEPS_FN(path=HERE / "e2e_steps.py"):
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "STEPS" for t in node.targets):
            return [(e.elts[0].value, e.elts[1].id) for e in node.value.elts]
    return []


def input_hash(step, decls=STEP_DECLS, repo_state_fn=repo_state, code_hash_fn=func_closure_hash):
    d = decls[step]
    parts = sorted(repo_state_fn(r) for r in d.repos) + [f"code={code_hash_fn(step)}", f"deps={d.deps if d.deps == UNKNOWN else ','.join(d.deps)}"]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def load_last_pass(path=LAST_PASS_FILE):
    try: return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError): return {}


def save_last_pass(rec, path=LAST_PASS_FILE):
    p = pathlib.Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True)); os.replace(tmp, p)


def select_changed(order, decls, current, last):
    """--changed-only 선택. (고른 단계 집합, {단계: 이유}).
    변경: 마지막 PASS 기록이 없거나 해시가 다르다 / 미확인: solo 가 증명되지 않았거나 deps 가 UNKNOWN 이라 항상 포함 /
    하위: 고른 단계에 (확인된 deps 로) 의존한다 / 상류: 고른 단계가 쓰는 STATE 를 만들려면 같이 돌려야 한다(스냅샷이 없어 새 스택에서 상태를 재구성)."""
    why = {}
    for n in order:
        if n not in decls: why[n] = "선언 없음"; continue
        if not decls[n].solo or decls[n].deps == UNKNOWN: why[n] = "미확인(단독 실행 미증명)"
        elif last.get(n) != current[n]: why[n] = "입력 해시 변경"
    changed = True
    while changed:
        changed = False
        for n in order:
            d = decls.get(n)
            if n in why or d is None or d.deps == UNKNOWN: continue
            if any(x in why for x in d.deps): why[n] = "하위(선행 단계가 고른 단계)"; changed = True
    for n in reversed(order):
        d = decls.get(n)
        if n in why and d is not None and d.deps != UNKNOWN:
            for x in d.deps:
                if x not in why: why[x] = "상류(상태 재구성에 필요)"
    return {n for n in order if n in why}, {n: why[n] for n in order if n in why}


def step_status_lines(rows):
    """steps.json 행([단계, 상태, 상세]) -> e2e.sh 가 읽는 '단계|FAIL|SKIP|PASS' 줄 들(단계별 가장 나쁜 상태)."""
    rank = {"PASS": 1, "SKIP": 2, "FAIL": 3}
    worst = {}
    for st_id, st, _ in rows:
        v = st if st in ("FAIL", "SKIP") else "PASS"
        k = str(st_id)
        if rank[v] > rank[worst.get(k, "PASS")] or k not in worst: worst[k] = v
    return [f"{k}|{v}" for k, v in worst.items()]


if __name__ == "__main__":
    # e2e.sh 용: step-status <steps.json> -> '단계|상태' 줄, skips <steps.json> -> SKIP 행 개수
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd in ("step-status", "skips"):
        rows = json.loads(pathlib.Path(sys.argv[2]).read_text())
        if cmd == "skips": print(sum(1 for r in rows if r[1] == "SKIP"))
        else: print("\n".join(step_status_lines(rows)))
    else:
        print("사용: e2e_plan.py step-status|skips <steps.json>", file=sys.stderr); sys.exit(2)
