#!/usr/bin/env python3
"""진입점: 컨테이너에 주입·배치하는 설정이 기동 전에 계약을 따르는지 본다(R7). up.sh 가 부른다. 사용: dc <프로젝트> config --format json | check_config_contracts.py --compose-json -
종료 코드 0 통과, 1 위반. 일은 openit_deploy/components/config_contract_check.py."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_check_config_contracts import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
