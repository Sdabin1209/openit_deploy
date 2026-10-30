#!/usr/bin/env python3
"""진입점: 비밀 `*_FILE` 환경 변수 이름 대조(compose 대 영역 코드). 사용: check_secret_names.py [--ws DIR]  종료 코드: FAIL 이 있으면 1.
일은 openit_deploy/components/secret_name_check.py, 파일 읽기는 wiring/cli_check_secret_names.py (ADR 0045)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_check_secret_names import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
