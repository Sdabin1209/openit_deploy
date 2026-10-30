#!/usr/bin/env python3
"""진입점: config/Caddyfile 이 이미지 노출 선언(라벨 io.openit.exposure)과 같은지 대조한다. 사용: check_exposure.py --inspect <JSON> [--caddyfile ...] [--known ...]
종료 코드: 0 일치, 1 어긋남, 2 사용 오류, 3 검증하지 못함. 일은 openit_deploy/components/exposure_check.py (ADR 0043, 0045)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_check_exposure import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
