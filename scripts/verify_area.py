#!/usr/bin/env python3
"""진입점: 영역 하나가 바뀌었을 때 전체 E2E 없이 확인할 범위를 정하고 돌린다 (사용: scripts/verify-area.sh <영역>). 계획은 openit_deploy/components/verify_plan.py, 연결은 openit_deploy/wiring/verify_area.py (ADR 0014, 0045)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.verify_area import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
