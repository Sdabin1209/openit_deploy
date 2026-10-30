#!/usr/bin/env python3
"""진입점: deploy 내부 파일(images.env, images.lock, verify-areas.yaml)을 schemas/ 로 검증한다. 사용: check_schemas.py [--root DIR] [--files images-env=PATH ...]
종료 코드 0 통과, 1 어긋남, 2 사용법. 일은 openit_deploy/components/internal_file_check.py (ADR 0034, 0045)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_check_schemas import main, run, ROOT  # noqa: E402,F401
from openit_deploy.components.internal_file_check import parse_images_env, parse_lock, validate as _validate  # noqa: E402,F401


def validate(schema_name, doc, root):
    return _validate(schema_name, doc, pathlib.Path(root) / "schemas")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
