"""wiring/진입: setup_env_report.py record|check|show|field <영역> ... (사용법은 scripts/setup_env_report.py 머리말)."""
import json
import pathlib
import sys

from openit_deploy.wiring import setup_env as SE

USAGE = "사용: <setup-env 출력> | setup_env_report.py record <영역> / check <영역> [--ws DIR] / show <영역> / field <영역> kind|path|command0"


def main(argv) -> int:
    argv = ["x"] + list(argv)
    if len(argv) < 3 or argv[1] not in ("record", "check", "show", "field"):
        print(USAGE, file=sys.stderr); return 2
    cmd, area = argv[1], argv[2]
    if cmd == "show":
        rep = SE.load(area)
        if rep is None: return 1
        print(json.dumps(rep, ensure_ascii=False)); return 0
    if cmd == "field":
        rep = SE.load(area)
        if rep is None or len(argv) < 4: return 1
        env = rep["environment"]; v = {"kind": env["kind"], "path": env["path"], "command0": env["test_command"][0]}.get(argv[3])
        if v is None: return 1
        print(v); return 0
    if cmd == "check":
        ws = pathlib.Path(argv[argv.index("--ws") + 1]) if "--ws" in argv else SE.ROOT.parent
        _, why = SE.env_status(area, ws)
        if why: print(why); return 1
        return 0
    rc, msg = SE.record(area, sys.stdin.read().splitlines())
    if rc: print(msg, file=sys.stderr)
    return rc
