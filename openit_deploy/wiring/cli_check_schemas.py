"""wiring/진입: check_schemas.py [--root DIR] [--files images-env=PATH ...]. 종료 코드 0 통과, 1 어긋남, 2 사용법. 파일 읽기·YAML 파싱·출력은 여기서 하고 판단은 internal_file_check 가 한다."""
import argparse
import pathlib
import sys

import yaml

from openit_deploy.components import internal_file_check
from openit_deploy.wiring.call import call

ROOT = pathlib.Path(__file__).resolve().parents[2]


def run(paths, root=ROOT) -> int:
    env = paths["images-env"]
    req = {"images_env_text": env.read_text(encoding="utf-8") if env.exists() else None,
           "images_lock_text": paths["images-lock"].read_text(encoding="utf-8"),
           "verify_areas": yaml.safe_load(paths["verify-areas"].read_text(encoding="utf-8"))}
    r = call(internal_file_check, "InternalFileCheckRequest", "InternalFileCheckResult", req, schema_dir=pathlib.Path(root) / "schemas")
    names = {"images.env": env.name}
    for c in r["checks"]:
        label = names.get(c["label"], c["label"])
        if c["status"] == "SKIP": print(f"SKIP {label} (없음: 빌드 전)"); continue
        for f in c["failures"]:
            why = f"{f['validator']} 위반" + (f" (패턴 {f['pattern']})" if "pattern" in f else "")
            where = f"{label} {f['line']}행" if "line" in f else label
            print(f"FAIL {where}: {f['where']}: {why}")
        if c["status"] == "OK": print(f"OK   {label}")
    return 1 if r["failed"] else 0


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="deploy 내부 파일을 schemas/ 로 검증한다")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--files", nargs="*", default=[], help="이름=경로 (images-env, images-lock, verify-areas)")
    a = ap.parse_args(argv)
    root = pathlib.Path(a.root)
    paths = {"images-env": root / "build/images.env", "images-lock": root / "locks/images.lock", "verify-areas": root / "config/verify-areas.yaml"}
    for kv in a.files:
        k, _, v = kv.partition("=")
        if k not in paths or not v: ap.error(f"알 수 없는 이름: {kv}")
        paths[k] = pathlib.Path(v)
    return run(paths, ROOT)
