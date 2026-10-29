#!/usr/bin/env python3
"""영역을 가로지르는 정적 일관성 점검(check-all.sh 가 부른다). 실행 없이 읽어서 아는 어긋남만 본다. 형제 영역은 읽기 전용이다.

원칙: 검증 대상에서 빠진 것을 '통과'로 말하지 않는다. 모든 규칙은 대상 목록을 자동으로 열거하고 결과를 세 상태로 분모와 함께 낸다.
  검증됨 N/M   읽고 어긋남이 없다고 확인한 대상 (M = 검증됨 + 어긋남 + 대상 아님 + 검증 안 함)
  어긋남 F     읽었더니 규칙에 어긋난 대상 (FAIL, 영역/파일:줄 근거)
  대상 아님 K  이 규칙이 보는 종류가 아니다(이유를 붙인다)
  검증 안 함 L 보려 했지만 못 봤다(venv 없음 등, 이유를 붙인다). 통과로 세지 않는다.
규칙 결과: FAIL(어긋남이 하나라도), SKIP(어긋남은 없으나 검증 안 함이 있다), PASS(그 밖). 종료 코드는 FAIL 이 하나라도 있을 때만 1.
'모르는 대상'(처리 방법을 모르는 영역·예시)은 FAIL 이다. 제외하려면 scripts/check-all.exclude 에 이유와 함께 적는다(목록은 출력한다).
값(비밀·설정 값)은 출력하지 않는다. 키 경로와 파일:줄만 낸다.
환경 변수(시험용): CHECK_ALL_WORKSPACE, CHECK_ALL_VERSIONS_CMD, CHECK_ALL_MR_PY, CHECK_ALL_ONLY(쉼표로 구분한 규칙 번호), CHECK_ALL_EXCLUDE
옵션: --strict  SKIP 이 하나라도 있으면 종료 코드 1 (게이트로 쓰는 실행용. SKIP 은 '검증 안 함'이 있다는 뜻이라 통과가 아니다)"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import setup_env_report as SER  # noqa: E402

HERE = Path(__file__).resolve().parent
WS = Path(os.environ.get("CHECK_ALL_WORKSPACE") or HERE.parent.parent)
EXCLUDE_FILE = Path(os.environ.get("CHECK_ALL_EXCLUDE") or HERE / "check-all.exclude")

# 점검이 처리 방법을 아는 영역과 종류의 정본: <워크스페이스>/head/shared/areas.json (scripts/areas.py). 표에 없는 .git 폴더는 '모르는 대상'이다.
# 왜 파일에서 읽나: 영역을 더할 때 이 점검·셸 스크립트·bump 도구를 따로 고치면 한 곳을 빠뜨린다.
sys.path.insert(0, str(HERE))
import areas as _areas
_AREAS = _areas.load(WS / "head" / "shared" / "areas.json") if (WS / "head" / "shared" / "areas.json").is_file() else {"areas": []}
_KIND_MAP = {"python": "py", "node": "node", "library": "py", "compose": "shell", "docs": "docs"}   # 점검 안의 처리 방식
AREA_KIND = {a["name"]: _KIND_MAP[a["kind"]] for a in _AREAS["areas"]}
VERSION_AREAS = [a["name"] for a in _AREAS["areas"] if a["version_train"]]


class R:
    """한 규칙의 결과."""
    def __init__(self):
        self.ok: list[str] = []
        self.bad: list[str] = []              # FAIL 근거(영역/파일:줄)
        self.fail_targets: set[str] = set()
        self.na: list[tuple[str, str]] = []   # (대상, 이유)
        self.un: list[tuple[str, str]] = []
        self.info: list[str] = []

    def fail(self, target: str, line: str):
        self.fail_targets.add(target)
        self.bad.append(line)

    @property
    def status(self) -> str:
        return "FAIL" if self.bad else ("SKIP" if self.un else "PASS")

    @property
    def total(self) -> int:
        return len(set(self.ok) - self.fail_targets) + len(self.fail_targets) + len(self.na) + len(self.un)

    @property
    def verified(self) -> int:
        return len(set(self.ok) - self.fail_targets)


def grouped(pairs: list[tuple[str, str]]) -> str:
    by: dict[str, list[str]] = {}
    for name, why in pairs:
        by.setdefault(why, []).append(name)
    parts = []
    for why, names in by.items():
        shown = ", ".join(names[:4]) + (" 외" if len(names) > 4 else "")
        parts.append(f"{why}: {len(names)}개 [{shown}]" if len(names) <= 12 else f"{why}: {len(names)}개")
    return "; ".join(parts)


# ---------- 허용·제외 목록 ----------
def load_pipe_file(path: Path):
    out = []
    if path.is_file():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s and not s.startswith("#"):
                parts = [p.strip() for p in s.split("|")]
                out.append((n, parts))
    return out


ORDERED_FILE = Path(os.environ.get("CHECK_ALL_ORDERED") or HERE / "check-all-ordered-schemas.txt")
ORDERED = [(n, p[0], p[1] if len(p) > 1 else "") for n, p in load_pipe_file(ORDERED_FILE)]   # (줄, 스키마 이름, 이유)
EXCLUDE = [(n, p[0], p[1] if len(p) > 1 else "") for n, p in load_pipe_file(EXCLUDE_FILE)]   # (줄, 종류:이름, 이유)


def excluded(key: str) -> str | None:
    for _, k, why in EXCLUDE:
        if k == key and why:
            return why
    return None


# ---------- 대상 열거 ----------
def enum_git_dirs() -> list[str]:
    return sorted(d.name for d in WS.iterdir() if d.is_dir() and not d.name.startswith(".") and (d / ".git").exists()) if WS.is_dir() else []


def known_areas() -> list[str]:
    return [a for a in enum_git_dirs() if a in AREA_KIND and not excluded(f"area:{a}")]


_files_cache: dict[str, list[str]] = {}


def files(repo: str) -> list[str]:
    if repo in _files_cache:
        return _files_cache[repo]
    d = WS / repo
    try:
        out = subprocess.run(["git", "-C", str(d), "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n")
        out = [f for f in out if f and (d / f).is_file()]
    except Exception:
        out = []
        for root, dirs, fs in os.walk(d):
            dirs[:] = [x for x in dirs if x not in (".git", ".venv", "node_modules", "__pycache__")]
            out += [str((Path(root) / f).relative_to(d)) for f in fs]
    _files_cache[repo] = [f for f in out if not re.search(r"(^|/)(\.venv|node_modules|\.git)/", f)]
    return _files_cache[repo]


def read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []


def bc_schema_dirs() -> list[Path]:
    bc = WS / "boundary-contracts"
    return [bc / "schemas", bc / "boundary_contracts" / "schemas"]


def find_schema_file(name: str) -> Path | None:
    for d in bc_schema_dirs():
        p = d / f"{name}.schema.json"
        if p.is_file():
            return p
    return None


def example_files() -> list[Path]:
    d = WS / "boundary-contracts" / "examples"
    return sorted(d.glob("*.json")) if d.is_dir() else []


def schema_names() -> list[str]:
    names = set()
    for d in bc_schema_dirs():
        if d.is_dir():
            names |= {p.name[:-len(".schema.json")] for p in d.glob("*.schema.json")}
    return sorted(n for n in names if not n.startswith("_"))


# ---------- 규칙 0: 대상 열거 ----------
def rule_enumerate() -> R:
    r = R()
    areas_missing(r)
    for n, key, why in EXCLUDE:
        if not why:
            r.fail(f"exclude:{key}", f"deploy/scripts/check-all.exclude:{n}: 제외 항목 '{key}' 에 이유가 없다")
    for a in enum_git_dirs():
        if a in AREA_KIND:
            w = excluded(f"area:{a}")
            (r.na.append((f"영역 {a}", f"제외({w})")) if w else r.ok.append(f"영역 {a}"))
        else:
            w = excluded(f"area:{a}")
            if w:
                r.na.append((f"영역 {a}", f"제외({w})"))
            else:
                r.fail(f"영역 {a}", f"모르는 대상: {a}  (워크스페이스의 .git 폴더인데 점검의 영역 표에 없다. head/shared/areas.json 에 넣거나 scripts/check-all.exclude 에 이유와 함께 적는다)")
    for ex in example_files():
        name = ex.name.split(".")[0]
        if find_schema_file(name):
            r.ok.append(f"예시 {ex.name}")
        else:
            w = excluded(f"example:{ex.name}")
            if w:
                r.na.append((f"예시 {ex.name}", f"제외({w})"))
            else:
                r.fail(f"예시 {ex.name}", f"모르는 대상: boundary-contracts/examples/{ex.name}  (짝이 되는 스키마 {name}.schema.json 이 없다)")
    r.info.append("제외 목록(scripts/check-all.exclude): " + ("; ".join(f"{k} = {w or '이유 없음'}" for _, k, w in EXCLUDE) if EXCLUDE else "비어 있음"))
    return r


# ---------- 규칙 1: 버전표 ----------
def rule_versions() -> R:
    r = R()
    areas = [a for a in known_areas()]
    app = [a for a in VERSION_AREAS if a in areas]
    for a in areas:
        if a not in VERSION_AREAS:
            r.na.append((a, "버전 표의 기준 또는 표를 소유한 영역이라 대조 대상이 아니다" if a in ("deploy", "boundary-contracts") else "태그 표기를 갖지 않는 영역"))
    for a in VERSION_AREAS:
        if a not in areas:
            r.un.append((a, "워크스페이스에 영역이 없다"))
    cmd = os.environ.get("CHECK_ALL_VERSIONS_CMD") or str(HERE / "check-versions.sh")
    try:
        p = subprocess.run(["bash", cmd] if cmd.endswith(".sh") else cmd.split(), capture_output=True, text=True, timeout=120)
    except Exception as e:
        r.fail("check-versions", f"deploy/scripts/check-versions.sh: 실행하지 못했다({type(e).__name__})")
        return r
    lines = [l for l in (p.stdout + p.stderr).splitlines() if l.strip()]
    if p.returncode == 3:   # 검증하지 못했다(빌드된 이미지가 없다): 통과로 세지 않는다. ADR 0042
        why = next((l.strip() for l in lines if "검증하지 못했다" in l), "빌드된 이미지가 없어 라벨을 볼 수 없다")
        if os.environ.get("CHECK_ALL_IMAGES") == "defer":   # e2e.sh 의 빌드 전 점검만 쓴다: 라벨 점검은 빌드 뒤 e2e.sh 가 같은 스크립트로 한다
            for a in app: r.na.append((a, "빌드 전이라 이미지 라벨을 아직 볼 수 없다(빌드 뒤 e2e.sh 가 check-versions.sh 를 실행한다)"))
        else:
            for a in app: r.un.append((a, why))
        return r
    if p.returncode == 0:
        r.ok += app
        if lines:
            r.info.append(lines[-1].strip())
    else:
        bad = [l.strip().replace("다름: ", "") for l in lines if "다름:" in l] or lines[-3:] or [f"deploy/scripts/check-versions.sh:1: 종료 코드 {p.returncode}"]
        for b in bad:
            r.fail(b.split(":")[0], b)
        r.ok += [a for a in app if a not in r.fail_targets]
    return r


# ---------- 규칙 2: 예시 키 순서 ----------
class Resolver:
    def __init__(self):
        self.cache: dict[Path, dict] = {}

    def doc(self, p: Path) -> dict:
        if p not in self.cache:
            self.cache[p] = json.loads(p.read_text(encoding="utf-8"))
        return self.cache[p]

    def resolve(self, node, cur: Path):
        seen = 0
        while isinstance(node, dict) and "$ref" in node and seen < 20:
            fpart, _, frag = node["$ref"].partition("#")
            target = cur if not fpart else (cur.parent / fpart)
            n = self.doc(target)
            for seg in [s for s in frag.split("/") if s]:
                n = n[seg.replace("~1", "/").replace("~0", "~")]
            node, cur = n, target
            seen += 1
        return node, cur


def prop_order(node: dict, rs: Resolver, cur: Path) -> list[str]:
    order: list[str] = []

    def add(n, c):
        n, c = rs.resolve(n, c)
        if not isinstance(n, dict):
            return
        for k in n.get("properties", {}):
            if k not in order:
                order.append(k)
        for b in n.get("allOf", []):
            add(b, c)
        for key in ("if", "then", "else"):
            if isinstance(n.get(key), dict):
                add(n[key], c)
    add(node, cur)
    return order


def child_schema(node: dict, key: str, rs: Resolver, cur: Path):
    node, cur = rs.resolve(node, cur)
    if not isinstance(node, dict):
        return None, cur
    if key in node.get("properties", {}):
        return node["properties"][key], cur
    for b in node.get("allOf", []):
        for part in (b, b.get("then"), b.get("else")):
            if isinstance(part, dict):
                p, c = rs.resolve(part, cur)
                if isinstance(p, dict) and key in p.get("properties", {}):
                    return p["properties"][key], c
    return None, cur


def order_problems(val, schema, cur: Path, rs: Resolver, path: str) -> list[tuple]:
    schema, cur = rs.resolve(schema, cur)
    if not isinstance(schema, dict):
        return []
    for key in ("anyOf", "oneOf"):
        if isinstance(schema.get(key), list):
            best = None
            for b in schema[key]:
                probs = order_problems(val, b, cur, rs, path)
                if not probs:
                    return []
                best = best if best is not None else probs
            return best or []
    probs: list[tuple] = []
    if isinstance(val, dict):
        order = prop_order(schema, rs, cur)
        known = [k for k in val if k in order]
        want = sorted(known, key=order.index)
        if known != want:
            first = next(k for k, w in zip(known, want) if k != w)
            probs.append((path, f"키 순서 {known} != 스키마 순서 {want}", first))
        for k, v in val.items():
            sub, c = child_schema(schema, k, rs, cur)
            if sub is not None:
                probs += order_problems(v, sub, c, rs, f"{path}/{k}")
    elif isinstance(val, list) and isinstance(schema.get("items"), dict):
        for i, v in enumerate(val):
            probs += order_problems(v, schema["items"], cur, rs, f"{path}/{i}")
    return probs


def line_of(lines: list[str], path: str, first: str) -> int:
    """어긋난 객체의 첫 어긋난 키가 있는 줄: 부모 키 줄 이후에서 찾는다. 못 찾으면 1."""
    keys = [s for s in path.split("/") if s and not s.isdigit()]
    start = 0
    for k in keys:
        for i in range(start, len(lines)):
            if re.match(rf'^\s*"{re.escape(k)}"\s*:', lines[i]):
                start = i
                break
    for i in range(start, len(lines)):
        if re.match(rf'^\s*"{re.escape(first)}"\s*:', lines[i]):
            return i + 1
    return 1


def rule_key_order() -> R:
    r = R()
    exs = example_files()
    if "boundary-contracts" not in enum_git_dirs() or not (WS / "boundary-contracts" / "examples").is_dir():
        r.un.append(("boundary-contracts/examples", "폴더가 없다"))
        return r
    rs = Resolver()
    have_example = set()
    for n, nm, why in ORDERED:
        if not why:
            r.fail(f"ordered:{nm}", f"deploy/scripts/check-all-ordered-schemas.txt:{n}: 대상 스키마 '{nm}' 에 이유가 없다")
        elif find_schema_file(nm) is None:
            r.fail(f"ordered:{nm}", f"deploy/scripts/check-all-ordered-schemas.txt:{n}: 스키마 '{nm}' 가 boundary-contracts 에 없다")
    ordered = {nm for _, nm, why in ORDERED if why}
    r.info.append("키 순서 대상 스키마(scripts/check-all-ordered-schemas.txt): " + (", ".join(f"{nm} ({why})" for _, nm, why in ORDERED) or "비어 있음"))
    for ex in exs:
        name = ex.name.split(".")[0]
        have_example.add(name)
        w = excluded(f"example:{ex.name}")
        if w:
            r.na.append((ex.name, f"제외({w})"))
            continue
        sp = find_schema_file(name)
        if sp is None:
            r.fail(ex.name, f"모르는 대상: boundary-contracts/examples/{ex.name}:1: 짝이 되는 스키마가 없다")
            continue
        if name not in ordered:
            r.na.append((ex.name, "모델 생성 출력이 아님(키 순서가 의미 없다)"))
            continue
        try:
            text = ex.read_text(encoding="utf-8")
            val = json.loads(text)
            schema = rs.doc(sp)
        except (OSError, ValueError) as e:
            r.fail(ex.name, f"boundary-contracts/examples/{ex.name}:1: 읽지 못했다({type(e).__name__})")
            continue
        r.ok.append(ex.name)
        lines = text.splitlines()
        for path, msg, first in order_problems(val, schema, sp, rs, ""):
            r.fail(ex.name, f"boundary-contracts/examples/{ex.name}:{line_of(lines, path, first)}: {path or '/'} {msg}")
    for s in schema_names():
        if s not in have_example:
            r.na.append((f"스키마 {s}", "비교할 예시가 없다"))
    return r


# ---------- 규칙 3: 완화 정책 ----------
RELAX_ALLOWED = {"allOf->anyOf", "oneOf->enum", "oneOf->anyOf"}
RELAX_SNIPPET = (
    "import json\nimport model_runtime as mr\nfrom boundary_contracts import load_schema\nfrom model_runtime.schema_guard import relax\n"
    "_, removed = relax(load_schema('ActionExtraction'), mr.DEFAULT_SUPPORTED_FEATURES)\nprint(json.dumps(sorted(removed)))\n")


def rule_relax() -> R:
    r = R()
    T = "ActionExtraction 완화"
    # 파이썬 위치는 model-runtime 의 setup-env 보고(SetupEnvReport.environment)에서 얻는다(U43: 이웃의 환경 배치를 짐작하지 않는다). 시험은 CHECK_ALL_MR_PY 로 대신한다
    py = os.environ.get("CHECK_ALL_MR_PY") or (str(SER.env_python("model-runtime", WS) or ""))
    if not py or not os.path.exists(py):
        _, why = SER.env_status("model-runtime", WS)
        r.un.append((T, why or "model-runtime 의 환경이 python-venv 가 아니다"))
        return r
    try:
        p = subprocess.run([py, "-I", "-c", RELAX_SNIPPET], capture_output=True, text=True, timeout=60, cwd="/")
    except Exception as e:
        r.fail(T, f"model-runtime: relax 를 부르지 못했다({type(e).__name__})")
        return r
    if p.returncode != 0:
        tail = (p.stderr.strip().splitlines() or ["?"])[-1][:200]
        r.fail(T, f"model-runtime/src/model_runtime/schema_guard.py:282: relax 호출 실패: {tail}")
        return r
    try:
        removed = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r.fail(T, "model-runtime/src/model_runtime/schema_guard.py:282: relax 출력을 읽지 못했다")
        return r
    extra = [x for x in removed if x not in RELAX_ALLOWED]
    if extra:
        r.fail(T, f"model-runtime/src/model_runtime/schema_guard.py:282: ActionExtraction 완화가 규칙을 뺀다: {extra} (허용 {sorted(RELAX_ALLOWED)})")
    else:
        r.ok.append(T)
        r.info.append(f"removed={removed} (허용 집합 안)")
    return r


# ---------- 규칙 4, 5: 코드 파일 (파서로 읽는다) ----------
# 왜 파서인가: 줄을 정규식으로 읽으면 쉼표 뒤 다음 인자를 값으로 읽거나(오탐) 별칭 import 를 놓친다(미탐). 파이썬은 ast, JSON 은 json, YAML 은 yaml, TOML 은 tomllib 로 읽는다.
# 파서가 없는 종류(.ts .sh Dockerfile 등)는 '대상 아님(파서 없음)'으로 센다. 읽은 것처럼 통과로 세지 않는다.
SKIP_DIR = re.compile(r"(^|/)(docs|build|dist|tests?|fixtures?|examples?|examples_invalid|runs|testdata|__pycache__)/")   # examples_invalid: 계약 2.2.0 의 거부 예시(일부러 틀린 값을 담은 시험 데이터)
PARSERS = {".py": "py", ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml"}


def classify(repo: str, f: str) -> str | None:
    """None 이면 대상(파서가 있는 종류), 아니면 '대상 아님' 이유."""
    if SKIP_DIR.search(f):
        return "문서·시험·시험 데이터·산출물 폴더"
    if re.search(r"(^|/)(test_[^/]*|[^/]*_test|conftest|verify)\.py$", f):
        return "시험·검증 스크립트(일부러 틀린 값을 만든다)"
    if os.path.splitext(f)[1] not in PARSERS:
        return "파서가 없는 종류(py·json·yaml·toml 이 아니다)"
    return None


def _load(path: Path, kind: str):
    """파싱 결과. 파싱하지 못하면 None(그 파일은 읽지 못한 것이다)."""
    try:
        text = path.read_text(encoding="utf-8")
        if kind == "py":
            return ast.parse(text)
        if kind == "json":
            return json.loads(text)
        if kind == "yaml":
            import yaml
            return list(yaml.safe_load_all(text))
        import tomllib
        return tomllib.loads(text)
    except Exception:
        return None


def scan_code(tree_check, data_check=None) -> R:
    """tree_check(repo, f, ast.Module) -> [(줄, 메시지)], data_check(repo, f, 파싱된 데이터) -> [(0, 메시지)]."""
    r = R()
    reasons: Counter = Counter()
    for repo in known_areas():
        for f in files(repo):
            rel = f"{repo}/{f}"
            why = classify(repo, f)
            if why:
                reasons[why] += 1
                continue
            kind = PARSERS[os.path.splitext(f)[1]]
            parsed = _load(WS / repo / f, kind)
            if parsed is None:
                r.un.append((rel, "파싱하지 못했다(문법 오류이거나 읽을 수 없다)"))
                continue
            if kind == "py":
                found = tree_check(repo, f, parsed)
            else:
                found = data_check(repo, f, parsed) if data_check else []
            if found:
                for i, m in found:
                    r.fail(rel, f"{rel}:{i}: {m}")
            else:
                r.ok.append(rel)
    r.na = [(f"{why}#{i}", why) for why, n in reasons.items() for i in range(n)]
    return r


def areas_missing(r: R) -> R:
    """영역 목록이 없거나 비면 분모 0 의 통과가 되므로 FAIL 이다."""
    if not _AREAS["areas"]:
        r.fail("영역 목록", "head/shared/areas.json:1: 파일이 없거나 영역이 0개다(분모 0 은 통과가 아니다)")
    return r


# ---------- 정본에서 읽는 값 ----------
# 낡은 용어를 이 파일에 적어 막지 않는다(용어는 계속 바뀐다). '지금 있는 것'을 정본에서 읽고, 정본에 없는 것을 쓰면 실패한다.
def _module_assigns(rel: str, name: str):
    """정본 파이썬 파일의 최상위 name 에 대한 (연산, 값 노드) 목록을 코드 실행 없이(ast) 모은다. 파일을 못 읽으면 (None, None).
    연산: '=' (Assign·AnnAssign), '+=' (AugAssign Add), '|=' (AugAssign BitOr)."""
    try:
        tree = ast.parse((WS / rel).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None, None
    out = []
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            out.append(("=", n.value))
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == name and n.value is not None:
            out.append(("=", n.value))
        elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name) and n.target.id == name:
            out.append(("+=" if isinstance(n.op, ast.Add) else "|=" if isinstance(n.op, ast.BitOr) else "?", n.value))
    return out, tree


def _dict_items(v):
    """{...} 리터럴 또는 dict(k=...) 호출의 (키, 값 노드) 목록. 읽을 수 없는 모양이면 None."""
    if isinstance(v, ast.Dict):
        if any(k is None or not isinstance(k, ast.Constant) for k in v.keys):
            return None
        return [(k.value, val) for k, val in zip(v.keys, v.values)]
    if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "dict" and not v.args and all(k.arg for k in v.keywords):
        return [(k.arg, k.value) for k in v.keywords]
    return None


def truth_templates():
    """지원하는 프롬프트 템플릿 버전: model-runtime 이 정한다. (집합, 문제 문자열). 못 읽으면 (None, 이유) -- 이유는 FAIL 이다.
    정본이 거짓일 수 있으므로 키마다 값이 같은 파일에 정의된 함수인지 교차 검증한다."""
    rel = "model-runtime/src/model_runtime/prompts.py"
    ops, tree = _module_assigns(rel, "_USER")
    if not ops:
        return None, f"{rel}:1: _USER 를 읽지 못했다"
    funcs = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    keys = set()
    for op, v in ops:
        if op not in ("=", "|="):
            return None, f"{rel}:1: _USER 의 {op} 대입을 해석하지 못했다"
        items = _dict_items(v)
        if items is None:
            return None, f"{rel}:1: _USER 의 값이 읽을 수 있는 dict 리터럴이 아니다"
        for k, val in items:
            # 값은 함수 이름 하나이거나, 역할별 함수의 dict 리터럴이다(model-runtime 0.7.7: LORA_A/LORA_B 컴포넌트 분리). 어느 쪽이든 함수가 이 파일에 정의돼 있어야 한다.
            ok = isinstance(val, ast.Name) and val.id in funcs
            if not ok:
                sub = _dict_items(val)
                ok = bool(sub) and all(isinstance(v2, ast.Name) and v2.id in funcs for _, v2 in sub)
            if not ok:
                return None, f"{rel}:1: _USER[{k!r}] 에 대응하는 템플릿 함수가 이 파일에 없다(정본이 거짓이다)"
            keys.add(k)
    return keys, ""


def truth_schema_version():
    """계약의 파이프라인 스키마 버전. (값, 문제 문자열)."""
    rel = "boundary-contracts/boundary_contracts/schemas_api.py"
    ops, _ = _module_assigns(rel, "PIPELINE_SCHEMA_VERSION")
    if not ops or len(ops) != 1 or ops[0][0] != "=" or not (isinstance(ops[0][1], ast.Constant) and isinstance(ops[0][1].value, str)):
        return None, f"{rel}:1: PIPELINE_SCHEMA_VERSION 을 문자열 상수 하나로 읽지 못했다"
    return ops[0][1].value, ""


PROMPT_NAME = re.compile(r"prompt-\d+")


def rule_removed_names() -> R:
    tpl, tpl_why = truth_templates()
    unread = 0   # 읽지 못한 동적 import 수

    def tree_check(repo, f, tree):
        nonlocal unread
        out = []
        # turn-engine 은 퇴역했다(D109, 계약 3.0): 어느 영역도 turn_engine 을 import 하면 안 된다. 정적 import, __import__, importlib.import_module 의 문자열 상수를 본다
        for n in ([] if repo == "turn-engine" else ast.walk(tree)):   # 퇴역한 turn-engine 리포 자신은 제외한다
            mods = []
            if isinstance(n, ast.Import): mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module: mods = [n.module]
            elif isinstance(n, ast.Call):
                fn = n.func
                dyn = (isinstance(fn, ast.Name) and fn.id == "__import__") or (isinstance(fn, ast.Attribute) and fn.attr == "import_module" and isinstance(fn.value, ast.Name) and fn.value.id == "importlib")
                if dyn and n.args:
                    a0 = n.args[0]
                    if isinstance(a0, ast.Constant) and isinstance(a0.value, str): mods = [a0.value]
                    else: unread += 1
            for m in mods:
                if m == "turn_engine" or m.startswith("turn_engine."):
                    out.append((n.lineno, f"turn_engine 은 퇴역했다(D109, 계약 3.0): {m} 를 import 하지 않는다"))
        if tpl is not None:
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and PROMPT_NAME.fullmatch(n.value) and n.value not in tpl:
                    out.append((n.lineno, f"지원하지 않는 프롬프트 템플릿 {n.value}(model-runtime 의 지원 목록 {sorted(tpl)})"))
        return out

    def data_check(repo, f, data):
        out = []
        if tpl is None:
            return out
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                stack += list(x.keys()) + list(x.values())
            elif isinstance(x, (list, tuple)):
                stack += list(x)
            elif isinstance(x, str) and PROMPT_NAME.fullmatch(x) and x not in tpl:
                out.append((0, f"지원하지 않는 프롬프트 템플릿 {x}(model-runtime 의 지원 목록 {sorted(tpl)})"))
        return out
    r = scan_code(tree_check, data_check)
    for why in (tpl_why,):
        if why:
            r.fail("정본", why)   # 정본을 못 읽거나 정본이 거짓이면 SKIP 이 아니라 FAIL 이다
    r.info.append("읽는 방법: 파이썬은 ast(import·별칭 속성·__import__·importlib.import_module 의 문자열 상수·문자열 상수 노드), JSON/YAML/TOML 은 파서. 상대 import 는 자기 패키지 내부라 보지 않는다. 하위 모듈은 turn-engine 의 파일 존재로 판단한다.")
    r.info.append(f"읽지 못하는 것: 문자열을 조합·f-string 으로 만든 템플릿 이름과 상수가 아닌 동적 import 인자({unread}건)는 보지 못한다.")
    return areas_missing(r)


def rule_hardcoded_contract() -> R:
    cur, cur_why = truth_schema_version()
    KEY = "pipeline_schema_version"

    def bad(v):
        return isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value != cur

    def tree_check(repo, f, tree):
        if cur is None:
            return []
        out = []

        def msg(v):
            return f'pipeline_schema_version 에 "{v}" 를 박았다(계약의 현재 값은 "{cur}". 계약 패키지의 상수를 쓴다)'

        def target_is_key(t):
            return (isinstance(t, ast.Name) and t.id == KEY) or (isinstance(t, ast.Attribute) and t.attr == KEY) \
                or (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value == KEY)
        for n in ast.walk(tree):
            if isinstance(n, ast.Dict):
                for k, v in zip(n.keys, n.values):
                    if isinstance(k, ast.Constant) and k.value == KEY and bad(v):
                        out.append((v.lineno, msg(v.value)))
            elif isinstance(n, ast.keyword) and n.arg == KEY and bad(n.value):   # kwarg 와 dict(...)
                out.append((n.value.lineno, msg(n.value.value)))
            elif isinstance(n, ast.Assign) and any(target_is_key(t) for t in n.targets) and bad(n.value):
                out.append((n.value.lineno, msg(n.value.value)))
            elif isinstance(n, (ast.AnnAssign, ast.AugAssign)) and target_is_key(n.target) and n.value is not None and bad(n.value):
                out.append((n.value.lineno, msg(n.value.value)))
        return out

    def data_check(repo, f, data):
        out = []
        if cur is None:
            return out
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                for k, v in x.items():
                    if k == KEY and isinstance(v, str) and v != cur:
                        out.append((0, f'pipeline_schema_version 에 "{v}" 를 박았다(계약의 현재 값은 "{cur}")'))
                stack += list(x.values())
            elif isinstance(x, (list, tuple)):
                stack += list(x)
        return out
    r = scan_code(tree_check, data_check)
    if cur_why:
        r.fail("정본", cur_why)
    r.info.append("읽는 방법: 파이썬은 ast(dict 키·kwarg·dict(...)·대입), JSON/YAML/TOML 은 파서. 값이 이름·표현식이면 보지 않는다(문자열 상수만 비교).")
    return areas_missing(r)


# ---------- yaml 노드 ----------
def yaml_ok() -> bool:
    try:
        import yaml  # noqa: F401
        return True
    except ImportError:
        return False


def compose_doc(text: str):
    import yaml
    return yaml.compose(text, Loader=yaml.SafeLoader)


def walk(node, path=""):
    import yaml
    if isinstance(node, yaml.MappingNode):
        for k, v in node.value:
            kn = str(getattr(k, "value", ""))
            p = f"{path}.{kn}" if path else kn
            yield p, kn, v
            yield from walk(v, p)
    elif isinstance(node, yaml.SequenceNode):
        for i, v in enumerate(node.value):
            yield from walk(v, f"{path}[{i}]")


SECRET_KEY = re.compile(r"token|secret|password|credential|api_key|authorization|private_key", re.I)
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]+$")
CONFIG_FILE = re.compile(r"(^|/)configs?/.*\.(yaml|yml|json)$")


def str_scalars(node):
    import yaml
    if isinstance(node, yaml.ScalarNode):
        if node.tag == "tag:yaml.org,2002:str" and node.value != "":
            yield node
    elif isinstance(node, yaml.SequenceNode):
        for v in node.value:
            yield from str_scalars(v)


def rule_inline_secrets() -> R:
    r = R()
    if not yaml_ok():
        r.un.append(("모든 설정 파일", "PyYAML 을 쓸 수 없다"))
        return r
    for repo in known_areas():
        for f in files(repo):
            if not CONFIG_FILE.search(f):
                continue
            rel = f"{repo}/{f}"
            try:
                root = compose_doc((WS / repo / f).read_text(encoding="utf-8"))
            except Exception:
                r.fail(rel, f"{rel}:1: 읽지 못했다(문법 오류)")
                continue
            if root is None:
                r.na.append((rel, "빈 파일"))
                continue
            r.ok.append(rel)
            for path, key, val in walk(root):
                if not SECRET_KEY.search(key):
                    continue
                for s in str_scalars(val):
                    if not ENV_NAME.match(s.value):
                        r.fail(rel, f"{rel}:{s.start_mark.line + 1}: {path} 에 인라인 값(환경 변수 이름이나 {{secret|env: NAME}} 형식이 아니다; 값은 출력하지 않는다)")
    return r


# ---------- 규칙 7 ----------
COMPOSE_FILE = re.compile(r"(^|/)compose[^/]*\.ya?ml$")
SECRET_ENV = re.compile(r"(^|_)(TOKENS?|SALT|PASSWORD|SECRET|PRIVATE_KEY|API_KEY)$")
ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def default_path(s: str) -> str:
    return re.sub(r"\$\{[A-Za-z_]+:?-([^}]*)\}", r"\1", s)


def rule_compose_secrets() -> R:
    r = R()
    if not yaml_ok():
        r.un.append(("모든 compose 서비스", "PyYAML 을 쓸 수 없다"))
        return r
    import yaml
    for repo in known_areas():
        for f in files(repo):
            if not COMPOSE_FILE.search(f):
                continue
            rel = f"{repo}/{f}"
            base = (WS / repo / f).parent
            try:
                root = compose_doc((WS / repo / f).read_text(encoding="utf-8"))
            except Exception:
                r.fail(rel, f"{rel}:1: 읽지 못했다(문법 오류)")
                continue
            services = next((v for k, v in root.value if k.value == "services"), None) if isinstance(root, yaml.MappingNode) else None
            if not isinstance(services, yaml.MappingNode):
                r.na.append((rel, "services 가 없는 compose 파일(서비스 0개)"))
                continue
            for sk, sv in services.value:
                tgt = f"{rel}:{sk.value}"
                w = excluded(f"service:{tgt}")
                if w:
                    r.na.append((tgt, f"제외({w})"))
                    continue
                r.ok.append(tgt)
                if not isinstance(sv, yaml.MappingNode):
                    continue
                for k, v in sv.value:
                    if k.value == "environment":
                        items = []
                        if isinstance(v, yaml.MappingNode):
                            items = [(str(kk.value), vv) for kk, vv in v.value
                                     if isinstance(vv, yaml.ScalarNode) and vv.tag != "tag:yaml.org,2002:null" and vv.value != ""]
                        elif isinstance(v, yaml.SequenceNode):
                            for it in v.value:
                                m = isinstance(it, yaml.ScalarNode) and re.match(r"^([^=]+)=(.+)$", it.value)
                                if m:
                                    items.append((m.group(1), it))
                        for name, vv in items:
                            if SECRET_ENV.search(name):
                                r.fail(tgt, f"{rel}:{vv.start_mark.line + 1}: 서비스 {sk.value} 의 {name} 에 값을 직접 준다(NAME_FILE 경로를 쓴다; 값은 출력하지 않는다)")
                    elif k.value == "env_file":
                        for nd in (v.value if isinstance(v, yaml.SequenceNode) else [v]):
                            if isinstance(nd, yaml.MappingNode):
                                nd = next((x for kk, x in nd.value if kk.value == "path"), None)
                            if not isinstance(nd, yaml.ScalarNode):
                                continue
                            p = Path(default_path(nd.value))
                            p = p if p.is_absolute() else base / p
                            for i, l in enumerate(read_lines(p), 1):
                                m = ENV_LINE.match(l)
                                if m and m.group(2).strip().strip("'\"") and SECRET_ENV.search(m.group(1)):
                                    r.fail(tgt, f"{rel}:{nd.start_mark.line + 1}: 서비스 {sk.value} 의 env_file {nd.value} {i}번째 줄 {m.group(1)} 에 값이 있다(값은 출력하지 않는다)")
    return r


# ---------- 규칙 8 ----------
def collect_area(repo: str):
    d = WS / repo
    kind = AREA_KIND[repo]
    if kind == "docs":
        return "na", "설계 문서 영역이라 시험이 없다"
    if kind == "shell":
        scripts = sorted((d / "scripts").glob("test-*.sh")) if (d / "scripts").is_dir() else []
        if not scripts:
            return "fail", "시험 스크립트(scripts/test-*.sh)가 없다"
        errs = [s.name for s in scripts if subprocess.run(["bash", "-n", str(s)], capture_output=True).returncode != 0]
        return ("fail", f"문법 오류 {errs}") if errs else ("ok", f"시험 스크립트 {len(scripts)}개 수집(bash -n)")
    return run_area_tests(repo, d)


def run_area_tests(repo: str, d: Path):
    """영역의 setup-env 보고(SetupEnvReport)가 알려 준 시험 명령을 영역 루트에서 그대로 실행한다. 환경 모양(.venv, node_modules)·시험 도구는 deploy 가 모른다(U43)."""
    rep, why = SER.env_status(repo, WS)
    if why:
        return "un", why
    cmd = rep["environment"]["test_command"]
    try:
        p = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=900)
    except Exception as e:
        return "fail", f"{cmd[0]} 시험 명령을 실행하지 못했다({type(e).__name__})"
    out = p.stdout + p.stderr
    # 시험 개수는 러너마다 다른 요약 줄에서 읽는다(pytest '12 passed', node:test 'tests 12', unittest 'Ran 12 tests'). 읽지 못하면 0개로 본다
    m = re.search(r"(\d+) passed", out) or re.search(r"\btests\s+(\d+)", out) or re.search(r"Ran (\d+) tests?", out)
    total = int(m.group(1)) if m else 0
    if p.returncode != 0:
        return "fail", f"시험 명령 종료 코드 {p.returncode} (통과 {total}개 확인)"
    return ("fail", "통과한 시험 개수를 확인하지 못했다(0개)") if total == 0 else ("ok", f"시험 {total}개 통과")


def rule_collect() -> R:
    r = R()
    areas = known_areas()
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(collect_area, areas))
    for a, (st, msg) in zip(areas, res):
        if st == "ok":
            r.ok.append(a)
            r.info.append(f"{a}: {msg}")
        elif st == "fail":
            r.fail(a, f"{a}/: {msg}")
        elif st == "na":
            r.na.append((a, msg))
        else:
            r.un.append((a, msg))
    return r


# ---------- 규칙 11 ----------
def rule_mount_sources() -> R:
    """compose 의 바인드 마운트 원본 중 확장자가 있는 것(설정 파일)은 실제 파일이어야 한다.
    파일이 없는 채로 마운트하면 Docker 가 그 자리에 빈 디렉터리를 만들고(root 소유) 서비스가 설정을 못 읽는다(config/ops-feedback-job.yaml 결함의 재발 방지)."""
    r = R()
    if not yaml_ok():
        r.un.append(("모든 compose 마운트", "PyYAML 을 쓸 수 없다"))
        return r
    import yaml
    for repo in known_areas():
        for f in files(repo):
            if not COMPOSE_FILE.search(f):
                continue
            rel = f"{repo}/{f}"
            base = (WS / repo / f).parent
            try:
                doc = yaml.safe_load((WS / repo / f).read_text(encoding="utf-8")) or {}
            except Exception:
                r.fail(rel, f"{rel}:1: 읽지 못했다(문법 오류)")
                continue
            for sname, svc in ((doc.get("services") or {}) if isinstance(doc, dict) else {}).items():
                for v in (svc or {}).get("volumes") or []:
                    src = (v.get("source") if v.get("type") == "bind" else None) if isinstance(v, dict) else (default_path(v).split(":")[0] if isinstance(v, str) else None)
                    if not src:
                        continue
                    src = default_path(src)
                    if "${" in src or not (src.startswith("./") or src.startswith("../") or src.startswith("/")):
                        continue   # 이름 있는 볼륨이거나 값을 알 수 없는 변수
                    tgt = f"{rel}:{sname}:{src}"
                    if not os.path.splitext(src)[1]:
                        r.na.append((tgt, "확장자가 없어 디렉터리로 본다"))
                        continue
                    p = Path(src) if src.startswith("/") else base / src
                    if p.is_file():
                        r.ok.append(tgt)
                    elif p.is_dir():
                        r.fail(tgt, f"{rel}: 서비스 {sname} 의 마운트 원본 {src} 가 파일이 아니라 디렉터리다(파일이 없을 때 Docker 가 만든 빈 디렉터리일 수 있다: 지우고 실제 파일을 둔다)")
                    else:
                        r.fail(tgt, f"{rel}: 서비스 {sname} 의 마운트 원본 {src} 가 없다(없는 채로 기동하면 Docker 가 디렉터리를 만든다)")
    return r


RULES = [
    ("0", "대상 열거(모르는 대상)", rule_enumerate),
    ("1", "버전표 일치", rule_versions),
    ("2", "계약 예시 키 순서", rule_key_order),
    ("3", "완화 정책이 규칙을 빼지 않음", rule_relax),
    ("4", "삭제된 이름의 잔존", rule_removed_names),
    ("5", "하드코딩된 계약 문자열", rule_hardcoded_contract),
    ("6", "설정 파일의 인라인 비밀", rule_inline_secrets),
    ("7", "compose 의 환경 변수 비밀", rule_compose_secrets),
    ("8", "영역별 시험 실행", rule_collect),
    ("11", "compose 마운트 원본이 실제 파일", rule_mount_sources),
]


def counts_text(r: R) -> str:
    s = f"검증됨 {r.verified}/{r.total}, 어긋남 {len(r.fail_targets)}, 대상 아님 {len(r.na)}, 검증 안 함 {len(r.un)}"
    return s


def main(argv=None) -> int:
    strict = "--strict" in (sys.argv[1:] if argv is None else argv)
    only = {x for x in (os.environ.get("CHECK_ALL_ONLY") or "").split(",") if x}
    t0 = time.time()
    sel = [x for x in RULES if not only or x[0] in only]
    print(f"== check-all (워크스페이스 {WS})")
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [(x, ex.submit(x[2])) for x in sel]
        results = []
        for x, fu in futs:
            try:
                r = fu.result()
            except Exception as e:
                r = R()
                r.fail("규칙", f"deploy/scripts/check_all.py:1: 규칙 실행 오류 {type(e).__name__}: {str(e)[:150]}")
            results.append((x, r))
    for (num, name, _), r in results:
        print(f"{name}: {r.status}")
        print(f"  {counts_text(r)}")
        if r.na:
            print(f"  대상 아님 이유: {grouped([(n.split('#')[0] if '#' in n else n, w) for n, w in r.na])}")
        if r.un:
            print(f"  검증 안 함 이유: {grouped(r.un)}")
        for b in r.bad:
            print(f"  FAIL {b}")
        for i in r.info:
            print(f"  · {i}")
    print("-- 요약 (규칙별. 세 상태를 합치지 않는다. SKIP 은 '검증 안 함'이 있다는 뜻이고 통과로 세지 않는다)")
    for (num, name, _), r in results:
        print(f"  [{r.status}] {name}: 검증됨 {r.verified}/{r.total} | 어긋남 {len(r.fail_targets)} | 대상 아님 {len(r.na)} | 검증 안 함 {len(r.un)}")
    st = Counter(r.status for _, r in results)
    print(f"-- 결과: FAIL {st['FAIL']}, SKIP {st['SKIP']}, PASS {st['PASS']} / 규칙 {len(results)}개, 소요 {time.time() - t0:.1f}s")
    return 1 if st["FAIL"] or (strict and st["SKIP"]) else 0


if __name__ == "__main__":
    sys.exit(main())
