"""컴포넌트 internal_file_check: deploy 내부 파일(build/images.env, locks/images.lock, config/verify-areas.yaml)을 schemas/*.schema.json 으로 검증한다(R5, audit DP-15, ADR 0034).
입력 InternalFileCheckRequest(파일 내용), 출력 InternalFileCheckResult. build/images.env 가 없으면(빌드 전) 그 항목은 SKIP.
왜 파서를 여기 두는가: 저장 형식(공백 텍스트, KEY=value)을 바꾸지 않고 기계가 읽는 정의만 더하는 것이 가장 작은 수정이다. 값(digest 포함)은 결과에 싣지 않고 위치·검증기 이름만 싣는다."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import InternalFileCheckRequest, InternalFileCheckResult

import json
import pathlib

SCHEMA_DIR = pathlib.Path(__file__).resolve().parents[2] / "schemas"


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


def validate(schema_name, doc, schema_dir=SCHEMA_DIR):
    from jsonschema import Draft202012Validator
    schema = json.loads((pathlib.Path(schema_dir) / f"{schema_name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return sorted(Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(map(str, e.path)))


def _failure(e, line=None):   # 값(digest 등)은 싣지 않는다: 검증기 이름과 위치만
    f = {"where": "/".join(map(str, e.path)) or "(최상위)", "validator": e.validator}
    if e.validator == "pattern": f["pattern"] = e.validator_value
    if line is not None: f["line"] = line
    return f


def run(request: "InternalFileCheckRequest", *, schema_dir=SCHEMA_DIR) -> "InternalFileCheckResult":
    checks = []
    if request.get("images_env_text") is None:
        checks.append({"label": "images.env", "status": "SKIP", "failures": []})
    else:
        fs = [_failure(e, n) for n, row in parse_images_env(request["images_env_text"]) for e in validate("ImagesEnvRow", row, schema_dir)]
        checks.append({"label": "images.env", "status": "FAIL" if fs else "OK", "failures": fs})
    for label, schema, doc in (("images.lock", "ImagesLock", parse_lock(request["images_lock_text"])), ("verify-areas.yaml", "VerifyAreas", request["verify_areas"])):
        fs = [_failure(e) for e in validate(schema, doc, schema_dir)]
        checks.append({"label": label, "status": "FAIL" if fs else "OK", "failures": fs})
    return {"checks": checks, "failed": sum(len(c["failures"]) for c in checks)}
