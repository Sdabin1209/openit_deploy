#!/usr/bin/env python3
"""진입점: 백업 보관 기간 <= 운영 데이터 보존 기간 중 가장 짧은 값인지 본다(ADR 0044). 사용: retention_check.py [--backup-days N | --backup-env <backup.env>] [--config-dir DIR] [--compose FILE]
종료 코드: 0 통과, 1 백업 보관이 더 길다, 2 값을 읽지 못함. 일은 openit_deploy/components/retention_check.py (ADR 0045)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_retention_check import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
