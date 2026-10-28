#!/usr/bin/env python3
"""버전 표 드리프트 점검(check-versions.sh 가 부른다). 기준은 scripts/lib.sh 의 표 하나다.
형제 영역의 구조화된 파일(pyproject.toml, requirements*/*.lock/*.in, Dockerfile ARG, compose, package.json, 그 밖의 JSON/YAML/TOML)과
빌드 셸의 `NAME_TAG=vX` 기본값이 적은 boundary-contracts·turn-engine·model-runtime 태그를 표와 비교한다. 문서(*.md)와 tests/ 는 보지 않는다.
읽는 방법: toml·json·yaml 은 파서로 문자열 값과 `*_TAG` 류 키를 모두 걸어 본다. requirements/lock/Dockerfile/셸은 줄 형식이 정해진 파일이라 주석을 뺀 줄에서 `이름@vX`·`ARG NAME=vX`·`NAME=${NAME:-vX}` 만 읽는다.
.py 의 상수 리터럴은 코드이므로 이 점검이 읽지 않는다(코드는 표를 읽거나 환경 변수로 받는다)."""
import json, os, re, subprocess, sys, tomllib
from pathlib import Path

ws = Path(os.environ["WS"])
TABLE = {"boundary-contracts": os.environ["EXP_BC"], "turn-engine": os.environ["EXP_TE"], "model-runtime": os.environ["EXP_MR"]}
REPOS = os.environ["VERSION_REPOS"].split()
LINEFILE = re.compile(r"(^|/)(requirements[^/]*\.(txt|lock|in)|[^/]*\.lock|Dockerfile[^/]*|[^/]*\.sh)$")
DATAFILE = {".toml": "toml", ".json": "json", ".yaml": "yaml", ".yml": "yaml"}
SKIP_DIR = re.compile(r"(^|/)(tests?|docs|\.venv|node_modules|build|dist|examples?|schemas?)/")
SKIP_NAME = re.compile(r"(package-lock\.json|pnpm-lock|tsconfig[^/]*\.json|CHANGELOG)")
PKG = re.compile(r"(boundary-contracts|turn-engine|model-runtime)(?:\.git)?[@#](v\d+\.\d+\.\d+)")
VAR = re.compile(r"\b(BOUNDARY|TURN_ENGINE|MODEL_RUNTIME)_(?:TAG|CONTRACTS?)\b[^\n]*?\b(v\d+\.\d+\.\d+)")
VARPKG = {"BOUNDARY": "boundary-contracts", "TURN_ENGINE": "turn-engine", "MODEL_RUNTIME": "model-runtime"}
KEYVAR = re.compile(r"^(BOUNDARY|TURN_ENGINE|MODEL_RUNTIME)_(?:TAG|CONTRACTS?)$")
TAG = re.compile(r"v\d+\.\d+\.\d+")


def files(repo):
    d = ws / repo
    try:
        out = subprocess.run(["git", "-C", str(d), "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n")
    except Exception:
        out = [str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [f for f in out if f and not SKIP_DIR.search(f) and not SKIP_NAME.search(f)]


def strings(node, key=None):
    """파싱된 데이터의 (키, 문자열 값)을 모두 낸다."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from strings(v, k)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from strings(v, key)
    elif isinstance(node, str):
        yield key, node


def found_in_string(key, s):
    out = [(m.group(1), m.group(2)) for m in PKG.finditer(s)]
    if key and (m := KEYVAR.match(str(key))) and TAG.fullmatch(s):
        out.append((VARPKG[m.group(1)], s))
    return out


bad = []; seen = 0; missing = []; unparsed = []
for repo in REPOS:
    if not (ws / repo).is_dir():
        missing.append(repo); continue
    for rel in files(repo):
        p = ws / repo / rel
        ext = os.path.splitext(rel)[1]
        hits = []   # (줄, 패키지, 태그)
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        if ext in DATAFILE:
            try:
                data = tomllib.loads(text) if DATAFILE[ext] == "toml" else json.loads(text) if DATAFILE[ext] == "json" else list(__import__("yaml").safe_load_all(text))
            except Exception:
                unparsed.append(f"{repo}/{rel}"); continue
            for key, s in strings(data):
                for pkg, tag in found_in_string(key, s):
                    n = next((i for i, l in enumerate(text.splitlines(), 1) if tag in l and (pkg in l or str(key) in l)), 1)
                    hits.append((n, pkg, tag))
        elif LINEFILE.search(rel):
            for n, line in enumerate(text.splitlines(), 1):
                if re.match(r"^\s*(#|//)", line):
                    continue
                hits += [(n, m.group(1), m.group(2)) for m in PKG.finditer(line)] + [(n, VARPKG[m.group(1)], m.group(2)) for m in VAR.finditer(line)]
        for n, pkg, tag in hits:
            seen += 1
            if tag != TABLE[pkg]:
                bad.append(f"{repo}/{rel}:{n}: {pkg} {tag} (표: {TABLE[pkg]})")
print(f"기준 표(scripts/lib.sh): boundary-contracts {TABLE['boundary-contracts']}, turn-engine {TABLE['turn-engine']}, model-runtime {TABLE['model-runtime']}")
print(f"검사한 태그 표기 {seen}건, 영역 {len(REPOS) - len(missing)}개" + (f", 폴더가 없어 건너뜀: {' '.join(missing)}" if missing else ""))
for u in unparsed:
    print("  파싱 못 함:", u)
for b in bad:
    print("  다름:", b)
if bad:
    print(f"실패: 표와 다른 표기 {len(bad)}건. 영역의 해당 파일을 표에 맞추거나(영역 세션), 표를 바꾼다(deploy)"); sys.exit(1)
if unparsed:
    print(f"실패: 파싱하지 못한 파일 {len(unparsed)}개(읽지 못한 것을 통과로 세지 않는다)"); sys.exit(1)
if seen == 0:
    print("실패: 태그 표기를 하나도 찾지 못했다(워크스페이스 경로 확인)"); sys.exit(2)
print("통과: 모든 표기가 표와 같다")
