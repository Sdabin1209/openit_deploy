#!/usr/bin/env python3
"""진입점: 영역 게이트웨이(<서비스>-gw)마다 그 서비스 이미지의 Exposure 선언 라벨을 state/gateways/<서비스>/exposure.json 으로 쓴다.
사용: dc <프로젝트> config --format json | gen-gateways.py --out state/gateways. 종료 코드 0 성공, 1 선언 없음·위반. 일은 openit_deploy/components/gateway_exposure.py."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_gen_gateways import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
