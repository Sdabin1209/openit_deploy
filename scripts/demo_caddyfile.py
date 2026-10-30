#!/usr/bin/env python3
"""진입점: 데모 전용 gateway 설정 사본을 만든다. 사용: demo_caddyfile.py <운영 Caddyfile> <출력 경로>
일은 openit_deploy/components/caddyfile_demo.py, 파일 읽기·쓰기는 wiring/cli_demo_caddyfile.py (ADR 0045)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_demo_caddyfile import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
