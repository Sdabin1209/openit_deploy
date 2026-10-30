"""컴포넌트 secret_name_check: 비밀 `*_FILE` 환경 변수 이름 대조(구조화된 정본끼리만 비교한다; 영역 docs/boundary.md 의 산문은 읽지 않는다). 입력 SecretNameCheckRequest, 출력 SecretNameCheckResult.
정본 A = deploy 의 compose*.yaml 서비스별 environment 에서 `_FILE` 로 끝나는 키(yaml 은 wiring 이 읽어 문서로 넘긴다).
정본 B = 각 영역의 파이썬 코드(ast)가 읽는 이름: 문자열 상수 노드 중 `^[A-Z][A-Z0-9_]*_FILE$`, 그리고 `read_secret("NAME")` 의 첫 인자 상수(NAME_FILE 로 센다).
판정: (1) 비밀 꼴(TOKEN/PASSWORD/SECRET/SALT/KEY/URL + _FILE)인 B 의 이름이 A 에 없으면(단수·복수 변형 포함) FAIL(코드는 읽는데 deploy 가 주지 않는다. 선택 비밀일 수 있어 영역이 확인한다). (2) A 의 이름 X_FILE 을 어떤 영역 코드도 읽지 않으면 WARN.
읽지 못하는 것: 이름을 조합한 문자열, node 영역(.ts)의 코드, 파이썬 코드가 아닌 소비자."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import SecretNameCheckRequest, SecretNameCheckResult

import ast
import re

FILE_NAME = re.compile(r"[A-Z][A-Z0-9_]*_FILE")
SECRET = re.compile(r".*(TOKEN|TOKENS|PASSWORD|SECRET|SALT|KEY|URL)_FILE")   # 비밀 이름의 꼴. RULES_FILE·POLICY_FILE 같은 설정 파일 경로는 비밀이 아니다
SKIP = re.compile(r"(^|/)(tests?|docs|build|dist|examples?|\.venv|node_modules)/|(^|/)(test_[^/]*|conftest)\.py$")
BASE_NAME = re.compile(r"[A-Z][A-Z0-9_]{3,}")


def compose_names(compose_docs) -> dict:
    """{이름: [compose파일:서비스]}"""
    out: dict = {}
    for item in compose_docs:
        for sname, svc in ((item["doc"] or {}).get("services") or {}).items():
            env = (svc or {}).get("environment") or {}
            keys = list(env.keys()) if isinstance(env, dict) else [str(e).split("=", 1)[0] for e in env]
            for k in keys:
                if FILE_NAME.fullmatch(k):
                    out.setdefault(k, []).append(f"{item['file']}:{sname}")
    return out


def code_names(files, base: set) -> dict:
    """{이름: [파일:줄]}. base 에는 코드에 상수로 나온 NAME 들을 모은다(NAME 을 받아 NAME_FILE 을 읽는 도우미용)."""
    out: dict = {}
    for f in files:
        if SKIP.search(f["path"]):
            continue
        try:
            tree = ast.parse(f["text"])
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and FILE_NAME.fullmatch(n.value):
                out.setdefault(n.value, []).append(f"{f['path']}:{n.lineno}")
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and BASE_NAME.fullmatch(n.value):
                base.add(n.value)
            elif isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                fn = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                if fn == "read_secret" and re.fullmatch(r"[A-Z][A-Z0-9_]*", n.args[0].value):
                    out.setdefault(n.args[0].value + "_FILE", []).append(f"{f['path']}:{n.lineno}")
    return out


def run(request: "SecretNameCheckRequest") -> "SecretNameCheckResult":
    if not request["areas"]:
        return {"status": "NO_AREAS", "fails": [], "warns": [], "compose_names": 0, "code_names": 0}
    comp = compose_names(request["compose_docs"])
    if not comp:
        return {"status": "NO_COMPOSE_NAMES", "fails": [], "warns": [], "compose_names": 0, "code_names": 0}
    seen: set = set(); fails = []
    for a in request["areas"]:
        base: set = set()
        cn = code_names(a["files"], base)
        seen |= {b + "_FILE" for b in base}
        for k, where in sorted(cn.items()):
            seen.add(k)
            alt = re.sub(r"_TOKENS?_FILE$", lambda m: "_TOKEN_FILE" if m.group(0).startswith("_TOKENS") else "_TOKENS_FILE", k)   # 단수·복수는 코드가 둘 다 받는다(둘 중 하나가 compose 에 있으면 충족)
            if k not in comp and alt not in comp and SECRET.fullmatch(k):
                fails.append({"area": a["name"], "where": where[0], "name": k})
    warns = [{"name": k, "services": sorted(set(w))} for k, w in sorted(comp.items()) if k not in seen]
    return {"status": "FAIL" if fails else "OK", "fails": fails, "warns": warns, "compose_names": len(comp), "code_names": len(seen)}
