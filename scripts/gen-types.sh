#!/usr/bin/env bash
# schemas/*.schema.json 에서 openit_deploy/types/deploy_types.py 를 생성한다(DESIGN.md 3절). 손으로 고치지 않는다. 생성기: datamodel-code-generator(requirements-types.txt 로 고정).
# 사용: scripts/gen-types.sh [출력 파일]   (기본 openit_deploy/types/deploy_types.py). 생성기 환경: python3 -m venv build/venv-types && build/venv-types/bin/pip install -r requirements-types.txt
# 왜 스키마를 하나로 묶어 생성하나: 스키마마다 파일을 만들면 생성기가 스키마 사이 $ref 를 올바르지 않은 상대 import 로 쓴다(0.25.9 에서 확인). 묶으면 $ref 가 같은 모듈 안에서 풀린다. 예시(schemas/examples/)는 읽지 않는다.
# 왜 TypedDict: 컴포넌트의 입출력은 JSON 문서(dict)이고 런타임 의존(pydantic)을 늘리지 않으려는 것이다(ADR 0045).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
GEN="${TYPES_GEN:-$ROOT/build/venv-types/bin/datamodel-codegen}"
[ -x "$GEN" ] || GEN="$(cd "$(git -C "$ROOT" rev-parse --git-common-dir)/.." && pwd)/build/venv-types/bin/datamodel-codegen"
[ -x "$GEN" ] || { echo "datamodel-codegen 이 없다: python3 -m venv build/venv-types && build/venv-types/bin/pip install -r requirements-types.txt" >&2; exit 2; }
PY="$(dirname "$GEN")/python"
OUT="${1:-$ROOT/openit_deploy/types/deploy_types.py}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
"$PY" - "$ROOT/schemas" "$T/deploy_types.schema.json" <<'PY'
import json, pathlib, sys
src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
defs = {}
def fix(node, name):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in ("$schema", "$id"): continue
            if k == "$ref" and isinstance(v, str):
                v = f"#/$defs/{v[:-len('.schema.json')]}" if v.endswith(".schema.json") else v.replace("#/$defs/", f"#/$defs/{name}_", 1)   # 스키마 안의 $defs 는 최상위로 올리고 이름 앞에 스키마 이름을 붙인다
            out[k] = fix(v, name)
        return out
    if isinstance(node, list):
        return [fix(x, name) for x in node]
    return node
for f in sorted(src.glob("*.schema.json")):
    name = f.name[:-len(".schema.json")]
    doc = fix(json.loads(f.read_text(encoding="utf-8")), name)
    for k, v in (doc.pop("$defs", None) or {}).items():
        defs[f"{name}_{k}"] = v
    defs[name] = doc
dst.write_text(json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "DeployTypes", "type": "object", "$defs": defs}, ensure_ascii=False), encoding="utf-8")
PY
mkdir -p "$(dirname "$OUT")"; rm -f "$OUT"
"$GEN" --input "$T/deploy_types.schema.json" --input-file-type jsonschema --output "$OUT" --output-model-type typing.TypedDict --target-python-version 3.10 --disable-timestamp --use-title-as-name

