"""wiring: 영역 목록 파일(areas.json)의 위치와 읽기. 정본은 <워크스페이스>/head/shared/areas.json 하나다(읽기 전용)."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def default_file() -> Path:
    if os.environ.get("AREAS_FILE"):
        return Path(os.environ["AREAS_FILE"])
    return ROOT.parent / "head" / "shared" / "areas.json"


def read(path=None) -> dict:
    return json.loads(Path(path or default_file()).read_text(encoding="utf-8"))


def names(path=None, kinds=None, train=False, exclude=()) -> list:
    """다른 wiring 이 영역 이름이 필요할 때 쓰는 입구(컴포넌트 area_list 를 거친다)."""
    from openit_deploy.components import area_list
    from openit_deploy.wiring.call import call
    return call(area_list, "AreaListRequest", "AreaListResult",
                {"areas_doc": read(path), "kinds": sorted(kinds or ()), "train": bool(train), "exclude": sorted(exclude)})["names"]
