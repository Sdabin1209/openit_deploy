#!/usr/bin/env python3
"""진입점: 기기 인증서 허용 목록(계약 DeviceAllowlist, D136)을 읽고 바꾼다. 사용법·잠금·원자적 교체는 openit_deploy/wiring/cli_device_allowlist.py, 판정은 openit_deploy/components/device_allowlist.py."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_device_allowlist import main  # noqa: E402

if __name__ == "__main__":
    main(sys.argv)
