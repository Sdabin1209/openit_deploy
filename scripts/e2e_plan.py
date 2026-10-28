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
    also: tuple = ()      # ((영역, 이유), ...) repos 에 없어도 이 단계가 경계를 보는 영역


_GW_SEC = ("deploy:config,compose.yaml,compose.test.yaml,test",)   # e2e_steps.py 의 _GW 와 같은 구간 입력(구간 선언 전용)


def decls_from_source(path=None):
    """e2e_steps.py 의 @step(...) 데코레이터에서 단계 선언을 읽는다(import 하면 argparse 가 돈다). 선언은 단계 코드 옆 한 곳에만 있다.
    인자는 리터럴과 모듈 최상위 상수(_GW, _P4)의 + 조합만 허용한다. deps=None 은 미확인이다. 순서는 STEPS 목록 순서다."""
    path = path or HERE / "e2e_steps.py"
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    consts = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id.startswith("_") and n.targets[0].id.isupper():
            consts[n.targets[0].id] = eval(compile(ast.Expression(n.value), str(path), "eval"), {}, dict(consts))
    found = {}
    for n in tree.body:
        if not isinstance(n, ast.FunctionDef): continue
        for dec in n.decorator_list:
            if isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "step":
                ev = lambda node: eval(compile(ast.Expression(node), str(path), "eval"), {}, dict(consts))
                name = ev(dec.args[0]); kw = {k.arg: ev(k.value) for k in dec.keywords}
                deps = kw["deps"]
                found[name] = Decl(tuple(kw["repos"]), UNKNOWN if deps is None else tuple(deps), kw["why"], bool(kw.get("solo", False)), tuple((kw.get("also") or {}).items()))
    return {name: found[name] for name in steps_in_source(path) if name in found} | {k: v for k, v in found.items() if k not in steps_in_source(path)}

# e2e.sh 의 구간. 구간 안의 항목 단위 선행 관계는 e2e.sh 의 chk_dep 호출이 갖는다(여기는 구간 단위 선언).
SECTION_DECLS = {
    "prep": Decl(("deploy:scripts,compose.yaml,locks", "survey-service", "question-authoring", "ops-feedback", "release-gate", "model-lab", "model-runtime", "kiosk-frontend", "admin-console"), (), "이미지 빌드·레지스트리·잠금. 실패하면 e2e.sh 가 중단한다(abort_if_failed)"),
    "s9-front": Decl(_GW_SEC, ("prep",), "compose up 과 도달·차단·라벨 점검은 준비의 digest 이미지에 의존한다"),
    "s1-8": Decl(_GW_SEC, ("s9-front",), "e2e_steps.py 는 s9-front 가 띄운 스택에서 돈다. 단계별 선언은 e2e_steps.py 의 @step"),
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


def state_access(path=None):
    """단계별 (읽는 STATE 키, 쓰는 STATE 키). 단계 함수가 (최상위 함수 호출로) 닿는 범위를 ast 로 분석한다.
    읽기: STATE['k'] (Load), STATE.get('k'), 'k' in STATE.  쓰기: STATE['k'] = ... (Store).  키가 리터럴이 아니면 SystemExit(분석할 수 없는 접근은 숨기지 않는다)."""
    path = path or HERE / "e2e_steps.py"
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    def direct(fn):
        r, w = set(), set()
        def key(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, str): return node.value
            raise SystemExit(f"{fn.name}: STATE 키가 리터럴이 아니다(줄 {node.lineno}). 분석할 수 없다")
        for n in ast.walk(fn):
            if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == "STATE":
                (w if isinstance(n.ctx, ast.Store) else r).add(key(n.slice))
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "STATE":
                if n.func.attr == "get": r.add(key(n.args[0]))
                elif n.func.attr == "setdefault": w.add(key(n.args[0]))   # 없을 때만 쓰는 쓰기로 본다(읽기로 세면 자기 쓰기와 구분이 안 된다)
                else: raise SystemExit(f"{fn.name}: STATE.{n.func.attr}() 는 분석하지 못한다(줄 {n.lineno})")
            elif isinstance(n, ast.Compare) and isinstance(n.comparators[0], ast.Name) and n.comparators[0].id == "STATE" and isinstance(n.ops[0], (ast.In, ast.NotIn)):
                r.add(key(n.left))
        return r, w
    out = {}
    for name, fname in STEPS_FN(path):
        seen, todo, r, w = set(), [fname], set(), set()
        while todo:
            f = todo.pop()
            if f in seen or f not in funcs: continue
            seen.add(f); dr, dw = direct(funcs[f]); r |= dr; w |= dw
            todo += [n.id for n in ast.walk(funcs[f]) if isinstance(n, ast.Name) and n.id in funcs]
        out[name] = (r, w)
    return out


def computed_deps(path=None):
    """단계가 읽는 상태 키(자기가 쓴 것 제외)를 앞선 다른 단계가 쓰면 그 단계가 deps 여야 한다. {단계: 단계 집합}."""
    acc = state_access(path); order = list(acc)
    res = {}
    for i, n in enumerate(order):
        need = acc[n][0] - acc[n][1]
        res[n] = {m for m in order[:i] if acc[m][1] & need}
    return res


STEP_DECLS = decls_from_source()


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
