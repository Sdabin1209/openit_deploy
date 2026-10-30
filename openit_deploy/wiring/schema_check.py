"""wiring: 영역 내부 타입을 schemas/ 의 JSON Schema(draft 2020-12)로 검증한다(DESIGN.md 5절, ADR 0045).
왜 wiring 인가: 컴포넌트는 입력 검사를 하지 않는다. 내는 쪽(wiring)이 컴포넌트에 넘기기 전에 한 번 검증하고 받는 쪽은 다시 검증하지 않는다(R7, ADR 0010)."""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas"


class SchemaError(ValueError):
    pass


def load(type_name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{type_name}.schema.json").read_text(encoding="utf-8"))


def errors(type_name: str, doc) -> list:
    """위반 목록(위치: 이유). 값은 싣지 않는다(비밀·digest 가 섞일 수 있다). jsonschema 가 없으면 ImportError(통과로 세지 않는다)."""
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    schemas = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in SCHEMA_DIR.glob("*.schema.json")}
    reg = Registry().with_resources([(n, Resource.from_contents(s)) for n, s in schemas.items()])
    v = Draft202012Validator(schemas[f"{type_name}.schema.json"], registry=reg)
    return [f"{'/'.join(map(str, e.path)) or '(최상위)'}: {e.validator} 위반" + (f" ({e.message[:120]})" if e.validator in ("required", "enum", "const", "additionalProperties", "minItems", "minimum", "maximum") else "")
            for e in sorted(v.iter_errors(doc), key=lambda e: list(map(str, e.path)))]


def check(type_name: str, doc):
    errs = errors(type_name, doc)
    if errs:
        raise SchemaError(f"{type_name} 스키마 위반: " + "; ".join(errs[:5]))
    return doc
