"""wiring/진입: check_config_contracts.py [--compose-json 파일|-]  — 컨테이너에 주입·배치하는 설정이 기동 전에 계약을 따르는지 본다(R7). up.sh 가 `compose up` 전에 부른다(합쳐진 compose 설정을 `dc ... config --format json` 으로 받아 표준 입력으로 넘긴다).
검증 대상: 서비스 환경(survey-service=SurveyServiceEnv, ops-feedback-ingest=OpsFeedbackServerEnv(OPS_ 접두 변수만), question-authoring=QuestionAuthoringDeployInterface 의 Environment), 배치 파일(config/ops-feedback-job.yaml=OpsFeedbackJobConfig, test/fake-model/question_flow.json=RuntimeFlowFile).
GateJobConfig·GatePolicy 는 deploy 가 만들지 않는다(release-gate 잡은 환경 변수로 설정되고 정책 파일은 O11 확정 전이라 없다): 만드는 코드가 생기면 여기에 문서를 더한다. 종료 코드: 0 통과, 1 위반(위치만 출력, 값은 출력하지 않는다)."""
import argparse
import json
import pathlib
import sys

import yaml

from openit_deploy.components import config_contract_check
from openit_deploy.wiring.call import call

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV_SERVICES = {   # compose 서비스 -> (계약 스키마, 환경 문서로 바꾸는 규칙)
    "survey-service": ("SurveyServiceEnv", lambda env: env),
    "ops-feedback-ingest": ("OpsFeedbackServerEnv", lambda env: {"env": {k: v for k, v in env.items() if k.startswith("OPS_")}}),   # 스키마: OPS_ 접두 변수만 넣는다
    "question-authoring": ("QuestionAuthoringDeployInterface#Environment", lambda env: env),
}
FILES = {"config/ops-feedback-job.yaml": "OpsFeedbackJobConfig",
         "test/fake-model/question_flow.json": "RuntimeFlowFile"}   # E2E·데모의 가짜 백엔드가 읽는 문항 흐름 파일(compose.fake-model.yaml 이 마운트): deploy 의 시험 설정


def make_validators(names):
    from boundary_contracts import load_schema, validator
    from jsonschema import Draft202012Validator
    out = {}
    for n in names:
        base, _, sub = n.partition("#")
        try:
            if sub:
                s = load_schema(base)
                v = Draft202012Validator({"$ref": f"#/$defs/{sub}", "$defs": s["$defs"], "$schema": s.get("$schema")})
            else:
                v = validator(base)
        except Exception:
            continue   # 없는 스키마는 컴포넌트가 NO_SCHEMA 위반으로 센다(건너뛰지 않는다)
        out[n] = (lambda vv: lambda doc: [("/".join(map(str, e.absolute_path)), f"{e.validator} 위반") for e in sorted(vv.iter_errors(doc), key=lambda e: list(map(str, e.absolute_path)))])(v)
    return out


def build_documents(compose: dict) -> list:
    docs = []
    for svc, (schema, wrap) in ENV_SERVICES.items():
        spec = (compose.get("services") or {}).get(svc)
        if spec is None: continue   # 이 구성(예: 외부 추론 서버만)에 없는 서비스
        env = {k: ("" if v is None else str(v)) for k, v in (spec.get("environment") or {}).items()}
        docs.append({"label": svc, "schema": schema, "document": wrap(env)})
    for rel, schema in FILES.items():
        docs.append({"label": rel, "schema": schema, "document": (json.loads if rel.endswith(".json") else yaml.safe_load)((ROOT / rel).read_text(encoding="utf-8"))})
    return docs


def main(argv, stdin=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--compose-json", default="-")
    a = ap.parse_args(argv)
    raw = (stdin or sys.stdin).read() if a.compose_json == "-" else pathlib.Path(a.compose_json).read_text(encoding="utf-8")
    docs = build_documents(json.loads(raw))
    r = call(config_contract_check, "ConfigContractCheckRequest", "ConfigContractCheckResult", {"documents": docs}, validators=make_validators({d["schema"] for d in docs}))
    for v in r["violations"]:
        print(f"FAIL {v['label']} ({v['schema']}) {v['where']}: {v['message']}", file=sys.stderr)
    print(f"{'통과' if r['ok'] else '실패'}: 설정·환경 문서 {r['checked']}개를 계약으로 검증했다" + ("" if r["ok"] else f", 위반 {len(r['violations'])}건"))
    return 0 if r["ok"] else 1
