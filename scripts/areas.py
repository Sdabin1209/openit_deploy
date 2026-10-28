#!/usr/bin/env python3
"""영역 목록 읽기. 정본은 <워크스페이스>/head/shared/areas.json 하나다(왜: 영역 이름을 스크립트마다 따로 적으면 영역을 더할 때 한 곳을 빠뜨린다).
사용(셸): areas.py [--ws DIR | --file F] [--kind k1,k2] [--train] [--except n1,n2] ...   (한 줄에 이름 하나를 공백으로 이어 출력)
"""
import argparse, json, os, sys
from pathlib import Path

KINDS = {"python", "node", "library", "compose", "docs"}


def default_file() -> Path:
    if os.environ.get("AREAS_FILE"):
        return Path(os.environ["AREAS_FILE"])
    return Path(__file__).resolve().parent.parent.parent / "head" / "shared" / "areas.json"


def load(path=None) -> dict:
    p = Path(path) if path else default_file()
    d = json.loads(p.read_text(encoding="utf-8"))
    bad = [a for a in d["areas"] if a.get("kind") not in KINDS]
    if bad:
        raise ValueError(f"{p}: 알 수 없는 kind: {bad}")
    return d


def names(path=None, kinds=None, train=False, exclude=()):
    return [a["name"] for a in load(path)["areas"]
            if (not kinds or a["kind"] in kinds) and (not train or a["version_train"]) and a["name"] not in exclude]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws"); ap.add_argument("--file")
    ap.add_argument("--kind", default=""); ap.add_argument("--train", action="store_true"); ap.add_argument("--except", dest="exc", default="")
    ap.add_argument("--sections", action="store_true")
    a = ap.parse_args()
    f = a.file or (str(Path(a.ws) / "head" / "shared" / "areas.json") if a.ws else None)
    try:
        if a.sections:
            print("\n".join(load(f)["readme_sections"]))
        else:
            print(" ".join(names(f, set(filter(None, a.kind.split(","))), a.train, set(filter(None, a.exc.split(","))))))
    except (OSError, ValueError, KeyError) as e:
        print(f"영역 목록을 읽지 못했다: {e}", file=sys.stderr); sys.exit(1)
