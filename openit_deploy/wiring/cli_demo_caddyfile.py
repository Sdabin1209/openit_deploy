"""wiring/진입: demo_caddyfile.py <운영 Caddyfile> <출력 경로>. 파일 읽기·쓰기는 여기서 한다(컴포넌트는 텍스트만 안다)."""
import sys

from openit_deploy.components import caddyfile_demo
from openit_deploy.wiring.call import call

USAGE = "사용: demo_caddyfile.py <운영 Caddyfile> <출력 경로>"


def main(argv) -> int:
    if len(argv) != 2:
        print(USAGE, file=sys.stderr); return 2
    r = call(caddyfile_demo, "CaddyfileDemoRequest", "CaddyfileDemoResult", {"caddyfile": open(argv[0], encoding="utf-8").read()})
    if r["status"] != "OK":
        print(f"/config.json 404 블록이 정확히 한 번 있어야 한다(찾은 수 {r['found']}): {argv[0]}", file=sys.stderr); return 1
    open(argv[1], "w", encoding="utf-8").write(r["demo_caddyfile"])
    return 0
