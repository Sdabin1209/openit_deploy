#!/usr/bin/env python3
"""진입점: 영역 목록 읽기(셸용). 사용: areas.py [--ws DIR | --file F] [--kind k1,k2] [--train] [--except n1,n2]   (한 줄에 이름을 공백으로 이어 출력)
일은 openit_deploy/components/area_list.py, 읽기·인자는 openit_deploy/wiring/ 가 한다(ADR 0045)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_areas import main  # noqa: E402
from openit_deploy.wiring.areas_file import names, default_file  # noqa: E402,F401

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
