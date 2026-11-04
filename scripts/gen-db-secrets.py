#!/usr/bin/env python3
"""진입점: 영역 DB 이미지 라벨 io.openit.database 에서 계정 암호·접속 URI 파일을 만든다(계약 3.4.10). 일은 openit_deploy/components/db_secrets.py."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_gen_db_secrets import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
