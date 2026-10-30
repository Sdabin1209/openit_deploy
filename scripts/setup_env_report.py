#!/usr/bin/env python3
"""진입점: 영역 scripts/setup-env.sh 의 SetupEnvReport(표준 출력 마지막 줄)를 검증해 state/setup-env/<영역>.json 에 모으고, 읽는 쪽(doctor, check-all)에 환경 위치를 알려 준다.
사용:
  <setup-env 출력> | setup_env_report.py record <영역>     마지막 비어 있지 않은 줄을 SetupEnvReport 로 검증해 저장(0 저장, 1 계약 위반·영역 이름 불일치, 2 줄 없음)
  setup_env_report.py check <영역> [--ws DIR]               환경 경로가 있는지(0 있음, 1 없음·보고 없음: 사유를 표준 출력에)
  setup_env_report.py show <영역>                           저장된 보고 JSON (0, 없으면 1)
  setup_env_report.py field <영역> kind|path|command0       보고의 environment.kind / path / test_command[0] 한 값 (없으면 1)
환경 변수 SETUP_ENV_DIR 로 저장 폴더를 바꾼다(시험용). 판정은 openit_deploy/components/setup_env_{record,status}.py, 저장소는 wiring/setup_env.py (ADR 0045)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_setup_env_report import main  # noqa: E402
from openit_deploy.wiring.setup_env import store, load, env_status, env_python  # noqa: E402,F401

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
