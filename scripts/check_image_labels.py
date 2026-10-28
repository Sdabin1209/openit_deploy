#!/usr/bin/env python3
"""이미지 라벨(docker inspect 의 .Config.Labels JSON)이 계약 ImageLabels 스키마를 따르는지 검사한다.
사용: docker image inspect <이미지> --format '{{json .Config.Labels}}' | python3 check_image_labels.py [--schema-dir <폴더>] [--name <이미지 이름>]
종료 코드: 0 통과, 1 어긋남, 2 검사를 못 했다(스키마·jsonschema 없음). 못 한 검사를 통과로 세지 않는다.
스키마 출처(위에서부터): --schema-dir 또는 IMAGE_LABELS_SCHEMA_DIR / 설치된 계약 패키지 boundary_contracts 의 schemas/ImageLabels.schema.json (계약 태그가 ImageLabels 를 싣게 되면 이 경로가 쓰인다) /
deploy 의 사본 docs/change-requests/contract-ready/schemas (계약 릴리스 전의 임시 정본). 왜 사본을 두는가: 헤드가 계약에 올리기 전에도 게시 검사를 이 스키마로 하기 위해서다. 계약 패키지에 올라오면 사본은 지운다.
io.openit.jobs·io.openit.exposure 값은 JSON 문자열이라 풀어서 JobsDeclaration·Exposure 로 한 번 더 검증한다(contentSchema 는 주석이라 검증기가 강제하지 않는다)."""
import argparse, json, os, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
ap = argparse.ArgumentParser(); ap.add_argument("--schema-dir", default=os.environ.get("IMAGE_LABELS_SCHEMA_DIR", "")); ap.add_argument("--name", default="")
a = ap.parse_args()


def find_dir():
    if a.schema_dir: return pathlib.Path(a.schema_dir), "지정한 폴더"
    try:
        import boundary_contracts
        d = pathlib.Path(boundary_contracts.__file__).parent / "schemas"
        if (d / "ImageLabels.schema.json").is_file(): return d, f"계약 패키지 boundary_contracts {getattr(boundary_contracts, '__version__', '')}".strip()
    except Exception: pass
    return HERE.parent / "docs/change-requests/contract-ready/schemas", "deploy 사본(contract-ready, 계약 릴리스 전)"


try:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
except ImportError as e:
    print(f"검사를 못 했다: jsonschema/referencing 가 없다({e.name}). deploy .venv 를 쓴다(requirements.txt)", file=sys.stderr); sys.exit(2)
d, src = find_dir()
try:
    schemas = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in d.glob("*.schema.json")}
    assert "ImageLabels.schema.json" in schemas
except Exception:
    print(f"검사를 못 했다: {d} 에서 ImageLabels.schema.json 을 읽지 못했다", file=sys.stderr); sys.exit(2)
reg = Registry().with_resources([(n, Resource.from_contents(s)) for n, s in schemas.items()])
V = lambda n: Draft202012Validator(schemas[n], registry=reg)
raw = sys.stdin.read().strip()
try: labels = json.loads(raw) if raw else None
except ValueError: print("검사를 못 했다: 표준 입력이 JSON 이 아니다", file=sys.stderr); sys.exit(2)
labels = labels or {}   # docker inspect 는 라벨이 없으면 null 을 낸다
if not isinstance(labels, dict): print("검사를 못 했다: 라벨이 객체가 아니다", file=sys.stderr); sys.exit(2)
errs = []
for e in sorted(V("ImageLabels.schema.json").iter_errors(labels), key=lambda e: list(map(str, e.path))):
    key = ".".join(map(str, e.path))
    errs.append(f"{key}: {e.message[:160]}" if key else e.message[:200])
for key, sub in (("io.openit.jobs", "JobsDeclaration.schema.json"), ("io.openit.exposure", "Exposure.schema.json")):
    if key in labels and sub in schemas:
        try: inner = json.loads(labels[key])
        except (ValueError, TypeError): errs.append(f"{key}: JSON 이 아니다"); continue
        errs += [f"{key}/{'/'.join(map(str, e.path))}: {e.message[:120]}" for e in V(sub).iter_errors(inner)]
print(f"스키마 출처: {src}")
for e in errs: print(f"FAIL {a.name + ' ' if a.name else ''}{e}")
print("OK 이미지 라벨이 ImageLabels 를 따른다" if not errs else f"FAIL 이미지 라벨 {len(errs)}건이 ImageLabels 를 어긴다")
sys.exit(1 if errs else 0)
