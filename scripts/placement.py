#!/usr/bin/env python3
"""진입점: 배치 정의(ansible 인벤토리) 검증과 서버별 산출물 계산(ADR 0061). 사용: placement.py validate|render <인벤토리> ... 일은 openit_deploy/wiring/placement_tool.py."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.placement_tool import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
