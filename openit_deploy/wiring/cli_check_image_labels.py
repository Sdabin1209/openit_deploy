"""wiring/진입: docker image inspect <이미지> --format '{{json .Config.Labels}}' | check_image_labels.py [--schema-dir <폴더>] [--name <이미지 이름>]
종료 코드: 0 통과, 1 어긋남, 2 검사를 못 했다(스키마·jsonschema 없음). 못 한 검사를 통과로 세지 않는다.
스키마 출처: --schema-dir 또는 IMAGE_LABELS_SCHEMA_DIR(시험용), 없으면 설치된 계약 패키지 boundary_contracts 의 schemas/. deploy 는 스키마 사본을 두지 않는다. 스키마 읽기(바깥 자원)는 여기서 하고 컴포넌트에는 검증 함수로 주입한다."""
import argparse
import json
import os
import pathlib
import sys

from openit_deploy.components import image_label_check
from openit_deploy.wiring.call import call


def _find_dir(schema_dir):
    if schema_dir:
        return pathlib.Path(schema_dir), "지정한 폴더"
    try:
        import boundary_contracts
        d = pathlib.Path(boundary_contracts.__file__).parent / "schemas"
        if (d / "ImageLabels.schema.json").is_file():
            return d, f"계약 패키지 boundary_contracts {getattr(boundary_contracts, '__version__', '')}".strip()
    except Exception:
        pass
    print("검사를 못 했다: 계약 패키지(boundary_contracts)가 없거나 ImageLabels.schema.json 이 없다. deploy .venv 를 쓴다(prepare-host.sh)", file=sys.stderr); sys.exit(2)


def main(argv) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--schema-dir", default=os.environ.get("IMAGE_LABELS_SCHEMA_DIR", "")); ap.add_argument("--name", default="")
    a = ap.parse_args(argv)
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError as e:
        print(f"검사를 못 했다: jsonschema/referencing 가 없다({e.name}). deploy .venv 를 쓴다(requirements.txt)", file=sys.stderr); return 2
    d, src = _find_dir(a.schema_dir)
    try:
        schemas = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in d.glob("*.schema.json")}
        assert "ImageLabels.schema.json" in schemas
    except Exception:
        print(f"검사를 못 했다: {d} 에서 ImageLabels.schema.json 을 읽지 못했다", file=sys.stderr); return 2
    reg = Registry().with_resources([(n, Resource.from_contents(s)) for n, s in schemas.items()])
    validators = {n[:-len(".schema.json")]: (lambda doc, n=n: [(".".join(map(str, e.path)), e.message) for e in
                                                               sorted(Draft202012Validator(schemas[n], registry=reg).iter_errors(doc), key=lambda e: list(map(str, e.path)))])
                  for n in schemas if n in ("ImageLabels.schema.json", "JobsDeclaration.schema.json", "Exposure.schema.json")}
    raw = sys.stdin.read().strip()
    try: labels = json.loads(raw) if raw else None
    except ValueError: print("검사를 못 했다: 표준 입력이 JSON 이 아니다", file=sys.stderr); return 2
    if labels is not None and not isinstance(labels, dict): print("검사를 못 했다: 라벨이 객체가 아니다", file=sys.stderr); return 2
    if isinstance(labels, dict) and any(not isinstance(v, str) for v in labels.values()):
        print("검사를 못 했다: 라벨 값이 문자열이 아니다", file=sys.stderr); return 2
    r = call(image_label_check, "ImageLabelCheckRequest", "ImageLabelCheckResult", {"name": a.name, "labels": labels}, validators=validators)
    print(f"스키마 출처: {src}")
    for e in r["errors"]: print(f"FAIL {a.name + ' ' if a.name else ''}{e}")
    print("OK 이미지 라벨이 ImageLabels 를 따른다" if r["ok"] else f"FAIL 이미지 라벨 {len(r['errors'])}건이 ImageLabels 를 어긴다")
    return 0 if r["ok"] else 1
