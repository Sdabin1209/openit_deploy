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
환경 변수(시험용): CHECK_ALL_WORKSPACE, CHECK_ALL_VERSIONS_CMD, CHECK_ALL_MR_PY, CHECK_ALL_ONLY(쉼표로 구분한 규칙 번호), CHECK_ALL_ALLOW, CHECK_ALL_EXCLUDE"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = Path(os.environ.get("CHECK_ALL_WORKSPACE") or HERE.parent.parent)
ALLOW_FILE = Path(os.environ.get("CHECK_ALL_ALLOW") or HERE / "check-all-allow.txt")
EXCLUDE_FILE = Path(os.environ.get("CHECK_ALL_EXCLUDE") or HERE / "check-all.exclude")

# 점검이 처리 방법을 아는 영역과 종류. 표에 없는 .git 폴더는 '모르는 대상'이다.
AREA_KIND = {
    "admin-console": "node", "kiosk-frontend": "node",
    "boundary-contracts": "contract", "deploy": "shell", "head": "docs",
    "model-lab": "py", "model-runtime": "py", "ops-feedback": "py", "question-authoring": "py",
    "release-gate": "py", "survey-service": "py", "synthetic-data": "py", "turn-engine": "py",
}
VERSION_AREAS = ["survey-service", "release-gate", "model-lab", "ops-feedback", "question-authoring", "synthetic-data",
                 "turn-engine", "model-runtime", "kiosk-frontend", "admin-console"]   # scripts/check-versions.sh 가 보는 10개


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


ALLOW = [(p[0], p[1]) for _, p in load_pipe_file(ALLOW_FILE) if len(p) >= 2]
ORDERED_FILE = Path(os.environ.get("CHECK_ALL_ORDERED") or HERE / "check-all-ordered-schemas.txt")
ORDERED = [(n, p[0], p[1] if len(p) > 1 else "") for n, p in load_pipe_file(ORDERED_FILE)]   # (줄, 스키마 이름, 이유)
EXCLUDE = [(n, p[0], p[1] if len(p) > 1 else "") for n, p in load_pipe_file(EXCLUDE_FILE)]   # (줄, 종류:이름, 이유)


def allowed(rule: str, path: str) -> bool:
    return any(r == rule and fnmatch.fnmatch(path, g) for r, g in ALLOW)


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
                r.fail(f"영역 {a}", f"모르는 대상: {a}  (워크스페이스의 .git 폴더인데 점검의 영역 표에 없다. scripts/check_all.py 의 AREA_KIND 에 넣거나 scripts/check-all.exclude 에 이유와 함께 적는다)")
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
    r.info.append("허용 목록(scripts/check-all-allow.txt): " + (f"{len(ALLOW)}건 " + "; ".join(f"{a}|{b}" for a, b in ALLOW) if ALLOW else "비어 있음"))
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
    if p.returncode == 0:
        r.ok += app
        if lines:
            r.info.append(lines[-1].strip())
    else:
        bad = [l.strip().replace("다름: ", "") for l in lines if "다름:" in l] or lines[-3:] or [f"deploy/scripts/check-versions.sh:1: 종료 코드 {p.returncode}"]
        for b in bad:
            r.fail(b.split("/")[0], b)
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
    py = os.environ.get("CHECK_ALL_MR_PY") or str(WS / "model-runtime" / ".venv" / "bin" / "python")
    if not os.path.exists(py):
        r.un.append((T, "model-runtime/.venv 가 없다"))
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


# ---------- 규칙 4, 5: 코드 파일 ----------
SKIP_DIR = re.compile(r"(^|/)(docs|build|dist|tests?|fixtures?|examples?|runs|testdata|__pycache__)/")
SKIP_NAME = re.compile(r"(\.md$|CHANGELOG|STATUS|HISTORY|\.lock$|\.egg-info)", re.I)
CODE_EXT = re.compile(r"(\.(py|sh|ts|tsx|js|mjs|cjs|yaml|yml|toml|cfg|ini|json|env)$|(^|/)Dockerfile[^/]*$|(^|/)requirements[^/]*\.txt$)")
COMMENT = re.compile(r"^\s*(#|//|\*|/\*|<!--)")
JSON_DESC = re.compile(r'^\s*"(description|\$comment|title)"\s*:')


def classify(rule: str, repo: str, f: str) -> str | None:
    """None 이면 대상, 아니면 '대상 아님' 이유."""
    if SKIP_DIR.search(f):
        return "문서·시험·시험 데이터·산출물 폴더"
    if SKIP_NAME.search(f):
        return "문서·이력·잠금 파일"
    if not CODE_EXT.search(f):
        return "코드·설정·스크립트가 아닌 파일"
    if allowed(rule, f"{repo}/{f}"):
        return "허용 목록(scripts/check-all-allow.txt)"
    return None


def scan_code(rule: str, line_check, text_check=None) -> R:
    r = R()
    reasons: Counter = Counter()
    for repo in known_areas():
        for f in files(repo):
            rel = f"{repo}/{f}"
            why = classify(rule, repo, f)
            if why:
                reasons[why] += 1
                continue
            lines = read_lines(WS / repo / f)
            found = []
            for i, l in enumerate(lines, 1):
                if COMMENT.match(l) or JSON_DESC.match(l):
                    continue
                found += [(i, m) for m in line_check(l)]
            if text_check:
                found += text_check("\n".join(lines))
            if found:
                for i, m in found:
                    r.fail(rel, f"{rel}:{i}: {m}")
            else:
                r.ok.append(rel)
    r.na = [(f"{n}개 파일", why) for why, n in reasons.items()]
    r.na = [(w, why) for (w, why) in r.na]
    # 대상 아님은 개수가 분모에 들어가야 하므로 파일 단위로 펼친다
    r.na = [(f"{why}#{i}", why) for why, n in reasons.items() for i in range(n)]
    return r


TE_IMPORT = re.compile(r"from\s+turn_engine(?:\.\w+)*\s+import\s+(\([^)]*\)|[^\n]*)")
TE_REMOVED = re.compile(r"\b(normalize|judge|write_record|plan)\b")
P4 = [("prompt-3", re.compile(r"prompt-3")), ("계약 v1 표기 v1.3.", re.compile(r"v1\.3\.")),
      ("계약 v1 열거값", re.compile(r"""["'](PARSER|GENERATOR)["']"""))]


def rule_removed_names() -> R:
    def line_check(l):
        return [f"삭제된 이름 {label}" for label, rx in P4 if rx.search(l)]

    def text_check(text):
        out = []
        for m in TE_IMPORT.finditer(text):
            gone = sorted(set(TE_REMOVED.findall(re.sub(r"#[^\n]*", "", m.group(1)))))
            if gone:
                out.append((text.count("\n", 0, m.start()) + 1, f"turn_engine 에서 제거된 함수 import {gone}"))
        return out
    return scan_code("4", line_check, text_check)


PSV = re.compile(r"""pipeline_schema_version["']?\s*(?:[:=]|,)\s*["']1\.""")


def rule_hardcoded_contract() -> R:
    return scan_code("5", lambda l: ["pipeline_schema_version 에 \"1.\" 값을 박았다(계약 패키지의 상수를 쓴다)"] if PSV.search(l) else [])


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
            w = allowed("6", rel)
            if w:
                r.na.append((rel, "허용 목록"))
                continue
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
    if kind == "node":
        if not (d / "node_modules").is_dir():
            return "un", "node_modules 가 없다"
        try:
            pj = json.loads((d / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "fail", "package.json 을 읽지 못했다"
        if "test" not in (pj.get("scripts") or {}):
            return "fail", "package.json 에 test 스크립트가 없다"
        try:
            p = subprocess.run(["npm", "test", "--silent"], cwd=d, capture_output=True, text=True, timeout=180)
        except Exception as e:
            return "fail", f"npm test 를 실행하지 못했다({type(e).__name__})"
        m = re.search(r"tests\s+(\d+)", p.stdout + p.stderr)
        total = int(m.group(1)) if m else 0
        if p.returncode != 0:
            return "fail", f"npm test 종료 코드 {p.returncode} (수집 {total}개)"
        return ("fail", "수집된 시험이 0개") if total == 0 else ("ok", f"npm test 시험 {total}개 수집·통과")
    py = d / ".venv" / "bin" / "python"
    if not py.exists():
        return "un", ".venv 가 없다"
    try:
        if subprocess.run([str(py), "-c", "import pytest"], capture_output=True, timeout=30).returncode != 0:
            return "un", ".venv 에 pytest 가 없다"
        p = subprocess.run([str(py), "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], cwd=d, capture_output=True, text=True, timeout=180)
    except Exception as e:
        return "fail", f"pytest 를 실행하지 못했다({type(e).__name__})"
    out = p.stdout
    m = re.search(r"(\d+) tests? collected", out)
    total = int(m.group(1)) if m else sum(int(x) for x in re.findall(r"^\S+\.py: (\d+)$", out, re.M))
    errs = len(re.findall(r"^ERROR ", out, re.M))
    em = re.search(r"(\d+) errors?", out.splitlines()[-1] if out.splitlines() else "")
    if em:
        errs = max(errs, int(em.group(1)))
    if p.returncode != 0 or errs:
        names = re.findall(r"^ERROR (?:collecting )?(\S+)", out, re.M)[:3]
        return "fail", f"수집 오류 {errs or '?'}건 (종료 코드 {p.returncode}) {names}"
    return ("fail", "수집된 시험이 0개") if total == 0 else ("ok", f"시험 {total}개 수집, 수집 오류 0")


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


# ---------- 규칙 9 ----------
# 규칙 9의 '필수 절 7개': 리포에 정의가 없어 이 점검이 다음 7개로 해석한다(미정, 헤드가 확정한다). 소개 = 제목 다음의 설명 문단 또는 '## 소개' 절,
# 나머지 6개는 '## [번호.] [이 영역의 ]<이름>' 제목이다.
README_SECTIONS = [("소개(제목 다음의 설명)", None), ("전체 속의 위치", r"전체 속의 위치"), ("구조", r"구조"), ("실행 방법", r"실행 방법"),
                   ("현재 상태", r"현재 상태"), ("열린 항목", r"열린 항목"), ("더 자세한 문서", r"더 자세한 문서")]


def rule_readme() -> R:
    r = R()
    r.info.append("필수 절 7개(헤드 확정 전의 해석): " + ", ".join(n for n, _ in README_SECTIONS) + " (앞의 '소개'는 제목 다음의 설명 문단 또는 '## 소개' 절)")
    for repo in known_areas():
        if AREA_KIND[repo] == "docs":
            r.na.append((repo, "설계 문서 영역이라 영역 README 형식이 아니다"))
            continue
        rp = WS / repo / "README.md"
        if not rp.is_file():
            r.fail(repo, f"{repo}/README.md:1: 파일이 없다")
            continue
        lines = read_lines(rp)
        heads = [l for l in lines if re.match(r"^##\s", l)]
        miss = []
        for name, rx in README_SECTIONS:
            if rx is None:
                first = next((i for i, l in enumerate(lines) if re.match(r"^##\s", l)), len(lines))
                intro = [l for l in lines[:first] if l.strip() and not l.startswith("#")]
                if not intro and not any(re.match(r"^##\s*(\d+\.\s*)?소개", l) for l in lines):
                    miss.append(name)
            elif not any(re.match(rf"^##\s*(\d+\.\s*)?(이 영역의 )?{rx}", h) for h in heads):
                miss.append(name)
        if miss:
            for m in miss:
                r.fail(repo, f"{repo}/README.md:1: 필수 절 없음: {m}")
        else:
            r.ok.append(repo)
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
    ("8", "영역별 시험 수집", rule_collect),
    ("9", "영역 README 필수 절", rule_readme),
]


def counts_text(r: R) -> str:
    s = f"검증됨 {r.verified}/{r.total}, 어긋남 {len(r.fail_targets)}, 대상 아님 {len(r.na)}, 검증 안 함 {len(r.un)}"
    return s


def main() -> int:
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
    return 1 if st["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
