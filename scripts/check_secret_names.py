#!/usr/bin/env python3
"""비밀 `*_FILE` 환경 변수 이름 대조(구조화된 정본끼리만 비교한다; 영역 docs/boundary.md 의 산문은 읽지 않는다).
정본 A = deploy 의 compose*.yaml 을 yaml 로 읽어 서비스별 environment 에서 `_FILE` 로 끝나는 키.
정본 B = 각 영역의 파이썬 코드(ast)가 읽는 이름: 문자열 상수 노드 중 `^[A-Z][A-Z0-9_]*_FILE$`, 그리고 `read_secret("NAME")` 의 첫 인자 상수(NAME_FILE 로 센다).
판정: (1) 비밀 꼴(TOKEN/PASSWORD/SECRET/SALT/KEY/URL + _FILE)인 B 의 이름이 A 에 없으면(단수·복수 변형 포함) FAIL(코드는 읽는데 deploy 가 주지 않는다. 선택 비밀일 수 있어 영역이 확인한다). (2) A 의 이름 X_FILE 에 대해 어떤 영역 코드에도 상수 X_FILE 도 X 도 없으면 WARN(코드가 아닌 곳(Caddy·postgres 이미지·셸)이 읽을 수 있다).
읽지 못하는 것: 이름을 조합한 문자열, node 영역(.ts)의 코드, 파이썬 코드가 아닌 소비자.
영역 문서(docs/boundary.md)는 이 대조가 맞는 이름만 적도록 사람이 고친다. 사용: check_secret_names.py [--ws DIR]  종료 코드: FAIL 이 있으면 1."""
import argparse, ast, os, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import areas as _areas

FILE_NAME = re.compile(r"[A-Z][A-Z0-9_]*_FILE")
SECRET = re.compile(r".*(TOKEN|TOKENS|PASSWORD|SECRET|SALT|KEY|URL)_FILE")   # 비밀 이름의 꼴. RULES_FILE·POLICY_FILE 같은 설정 파일 경로는 비밀이 아니다
SKIP = re.compile(r"(^|/)(tests?|docs|build|dist|examples?|\.venv|node_modules)/|(^|/)(test_[^/]*|conftest)\.py$")


def compose_names(deploy: Path) -> dict:
    """{이름: [compose파일:서비스]} -- yaml 파서로 environment(맵 또는 KEY=VAL 목록)를 읽는다."""
    import yaml
    out: dict = {}
    for f in sorted(deploy.glob("compose*.y*ml")) + sorted((deploy / "test").glob("compose*.y*ml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for sname, svc in (doc.get("services") or {}).items():
            env = (svc or {}).get("environment") or {}
            keys = list(env.keys()) if isinstance(env, dict) else [str(e).split("=", 1)[0] for e in env]
            for k in keys:
                if FILE_NAME.fullmatch(k):
                    out.setdefault(k, []).append(f"{f.name}:{sname}")
    return out


BASE_NAME = re.compile(r"[A-Z][A-Z0-9_]{3,}")


def code_names(repo: Path, base: set) -> dict:
    """{이름: [파일:줄]} -- 영역의 파이썬 코드가 읽는 *_FILE 이름. base 에는 코드에 상수로 나온 NAME 들을 모은다(NAME 을 받아 NAME_FILE 을 읽는 도우미용)."""
    out: dict = {}
    try:
        fs = subprocess.run(["git", "-C", str(repo), "ls-files", "*.py"], capture_output=True, text=True, check=True).stdout.split()
    except Exception:
        fs = [str(p.relative_to(repo)) for p in repo.rglob("*.py")]
    for f in fs:
        if SKIP.search(f):
            continue
        try:
            tree = ast.parse((repo / f).read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and FILE_NAME.fullmatch(n.value):
                out.setdefault(n.value, []).append(f"{f}:{n.lineno}")
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and BASE_NAME.fullmatch(n.value):
                base.add(n.value)
            elif isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                fn = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                if fn == "read_secret" and re.fullmatch(r"[A-Z][A-Z0-9_]*", n.args[0].value):
                    out.setdefault(n.args[0].value + "_FILE", []).append(f"{f}:{n.lineno}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--ws", default=str(HERE.parent.parent))
    ws = Path(ap.parse_args().ws)
    names = _areas.names(ws / "head" / "shared" / "areas.json", kinds={"python", "library"})
    if not names:
        print("FAIL: 영역 목록이 비었다"); return 1
    comp = compose_names(ws / "deploy")
    if not comp:
        print("FAIL: compose 에서 *_FILE 을 하나도 읽지 못했다"); return 1
    seen: set = set(); fails = 0
    for a in names:
        if not (ws / a).is_dir():
            continue
        base: set = set()
        cn = code_names(ws / a, base)
        seen |= {b + "_FILE" for b in base}
        for k, where in sorted(cn.items()):
            seen.add(k)
            alt = re.sub(r"_TOKENS?_FILE$", lambda m: "_TOKEN_FILE" if m.group(0).startswith("_TOKENS") else "_TOKENS_FILE", k)   # 단수·복수는 코드가 둘 다 받는다(둘 중 하나가 compose 에 있으면 충족)
            if k not in comp and alt not in comp and SECRET.fullmatch(k):
                fails += 1; print(f"FAIL {a}/{where[0]}: 코드가 읽는 {k} 를 deploy compose 가 주지 않는다")
    for k, where in sorted(comp.items()):
        if k not in seen:
            print(f"WARN {k}: compose({', '.join(sorted(set(where)))})가 주지만 어떤 영역의 파이썬 코드도 읽지 않는다")
    print(f"-- compose *_FILE {len(comp)}개, 영역 코드가 쓰는 이름 후보 {len(seen)}개, FAIL {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
