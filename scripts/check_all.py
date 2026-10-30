#!/usr/bin/env python3
"""진입점: 영역을 가로지르는 정적 일관성 점검(check-all.sh 가 부른다). 사용: check_all.py [--strict]. 환경 변수(시험용)는 openit_deploy/wiring/cli_check_all.py 머리말.
일은 openit_deploy/components/consistency_check.py (ADR 0012, 0045)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_check_all import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
