#!/usr/bin/env python3
"""진입점: 이미지 라벨이 계약 ImageLabels 를 따르는지 검사한다(표준 입력의 docker inspect 라벨 JSON). 사용: ... | check_image_labels.py [--schema-dir <폴더>] [--name <이미지 이름>]
종료 코드: 0 통과, 1 어긋남, 2 검사를 못 했다. 일은 openit_deploy/components/image_label_check.py (ADR 0045)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_check_image_labels import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
