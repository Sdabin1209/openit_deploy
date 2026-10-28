#!/usr/bin/env python3
"""deploy 내부 파일(build/images.env, locks/images.lock, config/verify-areas.yaml)을 schemas/*.schema.json 으로 검증한다(R5, audit DP-15).
사용: check_schemas.py [--root DIR] [--files images-env=PATH ...]   종료 코드 0 통과, 1 어긋남, 2 사용법.
build/images.env 가 없으면(빌드 전) 그 항목은 SKIP 으로 알린다. 왜 파서를 여기 두는가: 저장 형식(공백 텍스트, KEY=value)을 바꾸지 않고 기계가 읽는 정의만 더하는 것이 가장 작은 수정이다(docs/adr/0034-deploy-internal-schemas.md).
값(digest 포함)은 출력하지 않고 줄 번호와 이유만 낸다."""
import argparse, json, pathlib, re, sys
import yaml
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parent.parent


def parse_images_env(text):
    rows = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"): continue
        c = line.split()
        row = {"name": c[0], "image": c[1] if len(c) > 1 else "", "commit": c[2] if len(c) > 2 else ""}
        if len(c) > 3: row["tags"] = c[3]
        if len(c) > 4: row["extra"] = c[4:]   # 5열 이상은 정의에 없다 -> 스키마가 거부한다
        rows.append((n, row))
    return rows


def parse_lock(text):
    out = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"): continue
        k, _, v = line.partition("=")
        out[k] = v
    return out


def validate(schema_name, doc, root):
    schema = json.loads((root / "schemas" / f"{schema_name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return sorted(Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(map(str, e.path)))


def run(paths, root=ROOT):
    bad = 0
    def say(e):   # 값(digest 등)은 출력하지 않는다: 검증기 이름과 위치만
        return f"{e.validator} 위반" + (f" (패턴 {e.validator_value})" if e.validator == "pattern" else "")
    def report(label, errs):
        nonlocal bad
        for e in errs: print(f"FAIL {label}: {'/'.join(map(str, e.path)) or '(최상위)'}: {say(e)}"); bad += 1
        if not errs: print(f"OK   {label}")
    p = paths["images-env"]
    if p.exists():
        errs = []
        for n, row in parse_images_env(p.read_text(encoding="utf-8")):
            for e in validate("images-env", row, root): errs.append((n, e))
        for n, e in errs: print(f"FAIL {p.name} {n}행: {'/'.join(map(str, e.path)) or '(줄)'}: {say(e)}"); bad += 1
        if not errs: print(f"OK   {p.name}")
    else: print(f"SKIP {p.name} (없음: 빌드 전)")
    report("images.lock", validate("images-lock", parse_lock(paths["images-lock"].read_text(encoding="utf-8")), root))
    report("verify-areas.yaml", validate("verify-areas", yaml.safe_load(paths["verify-areas"].read_text(encoding="utf-8")), root))
    return 1 if bad else 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--files", nargs="*", default=[], help="이름=경로 (images-env, images-lock, verify-areas)")
    a = ap.parse_args(argv[1:])
    root = pathlib.Path(a.root)
    paths = {"images-env": root / "build/images.env", "images-lock": root / "locks/images.lock", "verify-areas": root / "config/verify-areas.yaml"}
    for kv in a.files:
        k, _, v = kv.partition("=")
        if k not in paths or not v: ap.error(f"알 수 없는 이름: {kv}")
        paths[k] = pathlib.Path(v)
    return run(paths, pathlib.Path(__file__).resolve().parent.parent)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
