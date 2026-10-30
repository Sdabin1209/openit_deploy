#!/usr/bin/env python3
"""진입점: 영역 잠금 파일의 openit-link 태그를 기준표(DEPLOY_LINK_TAG)와 대조한다(U59). 사용: check_link_pins.py [--ws DIR] [--tag vX.Y.Z]. 종료 코드 0 같다, 1 어긋남, 3 검증하지 못함.
일은 openit_deploy/components/link_pin_check.py (ADR 0046)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_check_link_pins import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
