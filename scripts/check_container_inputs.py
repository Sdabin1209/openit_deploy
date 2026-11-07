#!/usr/bin/env python3
"""진입점: compose 가 우리 이미지에 주입하는 것이 이미지의 주입 선언(계약 ContainerInputs 3.5.0)과 같은지 본다. up.sh 가 기동 전에 부른다.
사용: check_container_inputs.py --compose-json <파일|-> [--declarations-dir 폴더]. 일은 openit_deploy/components/container_inputs_check.py."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_check_container_inputs import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
