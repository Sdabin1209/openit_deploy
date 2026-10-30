#!/usr/bin/env python3
"""진입점: 복구한 저장소를 실제 서비스의 HTTP 로 다시 읽어 검증한다(E2E 9단계). 사용: e2e_verify_restore.py --secrets DIR --ports JSON --work DIR --run-id ID
일은 openit_deploy/components/link_restore_verify.py (ADR 0045)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_e2e_verify_restore import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
