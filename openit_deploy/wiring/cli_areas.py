"""wiring/진입: 셸이 부르는 `areas.py` 명령. 인자를 읽어 AreaListRequest 로 만들고 결과를 공백으로 이어 출력한다."""
import argparse
import sys
from pathlib import Path

from openit_deploy.wiring import areas_file
from openit_deploy.wiring.schema_check import SchemaError


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws"); ap.add_argument("--file")
    ap.add_argument("--kind", default=""); ap.add_argument("--train", action="store_true"); ap.add_argument("--except", dest="exc", default="")
    a = ap.parse_args(argv)
    f = a.file or (str(Path(a.ws) / "head" / "shared" / "areas.json") if a.ws else None)
    try:
        print(" ".join(areas_file.names(f, set(filter(None, a.kind.split(","))), a.train, set(filter(None, a.exc.split(","))))))
    except (OSError, ValueError, KeyError, SchemaError) as e:   # SchemaError 는 ValueError 의 하위
        print(f"영역 목록을 읽지 못했다: {e}", file=sys.stderr)
        return 1
    return 0
