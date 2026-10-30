"""wiring/진입: check_secret_names.py [--ws DIR]. compose*.yaml 과 각 영역의 파이썬 소스를 읽어(읽기 전용) 컴포넌트 secret_name_check 에 넘기고 결과를 출력한다. 종료 코드: FAIL 이 있으면 1."""
import argparse
import pathlib
import subprocess
import sys

import yaml

from openit_deploy.components import secret_name_check
from openit_deploy.wiring import areas_file
from openit_deploy.wiring.call import call

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _py_files(repo: pathlib.Path):
    try:
        fs = subprocess.run(["git", "-C", str(repo), "ls-files", "*.py"], capture_output=True, text=True, check=True).stdout.split()
    except Exception:
        fs = [str(p.relative_to(repo)) for p in repo.rglob("*.py")]
    out = []
    for f in fs:
        try:
            out.append({"path": f, "text": (repo / f).read_text(encoding="utf-8")})
        except (OSError, UnicodeDecodeError):
            continue
    return out


def main(argv) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--ws", default=str(ROOT.parent))
    ws = pathlib.Path(ap.parse_args(argv).ws)
    names = areas_file.names(ws / "head" / "shared" / "areas.json", kinds={"python", "library"})
    deploy = ws / "deploy"
    docs = [{"file": f.name, "doc": yaml.safe_load(f.read_text(encoding="utf-8")) or {}}
            for f in sorted(deploy.glob("compose*.y*ml")) + sorted((deploy / "test").glob("compose*.y*ml"))]
    r = call(secret_name_check, "SecretNameCheckRequest", "SecretNameCheckResult",
             {"areas": [{"name": a, "files": _py_files(ws / a)} for a in names if (ws / a).is_dir()], "compose_docs": docs})
    if r["status"] == "NO_AREAS" or not names:
        print("FAIL: 영역 목록이 비었다"); return 1
    if r["status"] == "NO_COMPOSE_NAMES":
        print("FAIL: compose 에서 *_FILE 을 하나도 읽지 못했다"); return 1
    for f in r["fails"]:
        print(f"FAIL {f['area']}/{f['where']}: 코드가 읽는 {f['name']} 를 deploy compose 가 주지 않는다")
    for w in r["warns"]:
        print(f"WARN {w['name']}: compose({', '.join(w['services'])})가 주지만 어떤 영역의 파이썬 코드도 읽지 않는다")
    print(f"-- compose *_FILE {r['compose_names']}개, 영역 코드가 쓰는 이름 후보 {r['code_names']}개, FAIL {len(r['fails'])}")
    return 1 if r["fails"] else 0
