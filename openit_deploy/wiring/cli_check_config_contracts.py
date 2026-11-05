"""wiring/진입: check_config_contracts.py [--compose-json 파일|-]  — 컨테이너에 주입·배치하는 설정이 기동 전에 계약을 따르는지 본다(R7). up.sh 가 `compose up` 전에 부른다(합쳐진 compose 설정을 `dc ... config --format json` 으로 받아 표준 입력으로 넘긴다).
검증 대상: 서비스 환경(ENV_SERVICES 표: 서비스마다 계약의 *Env 선언 스키마, 3.2.0 U73), 배치 파일(config/ops-feedback-job.yaml=OpsFeedbackJobConfig, test/fake-model/question_flow.json=RuntimeFlowFile).
수집 잡 설정은 GateJobConfig로 검증한다. GatePolicy는 O11 확정 전이라 만들지 않는다. 종료 코드: 0 통과, 1 위반(위치만 출력, 값은 출력하지 않는다)."""
import argparse
import json
import re
import os
import pathlib
import sys

import yaml

from openit_deploy.components import config_contract_check
from openit_deploy.wiring.call import call

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV_SERVICES = {   # compose 서비스 -> (계약 스키마, 환경 문서로 바꾸는 규칙). 3.2.0(U73): 모든 서비스 컨테이너의 환경을 그 서비스의 선언 스키마로 검증한다
    "survey-service": ("SurveyServiceEnv", lambda env: env),
    "ops-feedback": ("OpsFeedbackServerEnv", lambda env: {"env": {k: v for k, v in env.items() if k.startswith("OPS_")}}),   # 스키마: OPS_ 접두 변수만 넣는다
    "question-authoring": ("QuestionAuthoringEnv", lambda env: env),
    "release-gate": ("GateEnv", lambda env: env),
    "model-serving": ("ModelServingEnv", lambda env: env),
    "model-registry": ("ModelRegistryEnv", lambda env: env),
    "dataset-store": ("DatasetStoreEnv", lambda env: env),
    "kiosk-frontend": ("KioskFrontendEnv", lambda env: env),
    # 관리 잡(일회성 프로세스)도 서버와 같은 선언 스키마로 검증한다: 12-Factor XII, 잡은 서버와 같은 환경이다. 3차 E2E 에서 question-authoring 정리 잡이 토큰 anyOf 로 거부됐는데 서버만 검사해 E2E 에서야 드러났다
    "job-survey-purge": ("SurveyServiceEnv", lambda env: env),
    "job-question-authoring-purge": ("QuestionAuthoringEnv", lambda env: env),
    "job-release-gate-prune": ("GateEnv", lambda env: env),
    "job-release-gate-collect": ("GateEnv", lambda env: env),
    "gateway": ("GatewayEnv", lambda env: env),   # deploy 소유 컨테이너: 내부 스키마 schemas/GatewayEnv(L20). 계약에 같은 이름이 없다
}
FILES = {"config/ops-feedback-job.yaml": "OpsFeedbackJobConfig",
         "config/release-gate-job.json": "GateJobConfig",
         "test/fake-model/question_flow.json": "RuntimeFlowFile"}   # E2E·데모의 가짜 백엔드가 읽는 문항 흐름 파일(compose.fake-model.yaml 이 마운트): deploy 의 시험 설정


def make_validators(names):
    from boundary_contracts import load_schema, validator
    from jsonschema import Draft202012Validator
    out = {}
    for n in names:
        local = ROOT / "schemas" / f"{n}.schema.json"
        if local.exists():   # deploy 내부 스키마(schemas/*.schema.json): 영역 사이 계약이 아닌 deploy 소유 컨테이너(gateway)의 선언. 계약 이름과 겹치지 않게 둔다
            s = json.loads(local.read_text(encoding="utf-8"))
            vv = Draft202012Validator(s)
            out[n] = (lambda v: lambda doc: [("/".join(map(str, e.absolute_path)), f"{e.validator} 위반") for e in sorted(v.iter_errors(doc), key=lambda e: list(map(str, e.absolute_path)))])(vv)
            continue
        base, _, sub = n.partition("#")
        try:
            v = validator(n)
        except Exception:
            continue   # 없는 스키마는 컴포넌트가 NO_SCHEMA 위반으로 센다(건너뛰지 않는다)
        out[n] = (lambda vv: lambda doc: [("/".join(map(str, e.absolute_path)), f"{e.validator} 위반") for e in sorted(vv.iter_errors(doc), key=lambda e: list(map(str, e.absolute_path)))])(v)
    return out


def device_config_documents(secrets_dir) -> list:
    """기기 설정 산출물(secrets/kiosk-config/<ID>.json, kiosk-add-device.sh 가 만든다)을 계약 DeviceConfig 로 검증할 문서로 만든다(3.3.0: question_set_id 배치 칸 포함, ADR 0052). 라벨에는 기기 ID 만 쓴다(토큰 값은 위반 메시지에도 안 나온다: 위반은 위치와 규칙 이름뿐)."""
    d = pathlib.Path(secrets_dir) / "kiosk-config"
    out = []
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try: doc = json.loads(f.read_text(encoding="utf-8"))
        except ValueError: doc = "(JSON 이 아니다)"   # 값은 싣지 않는다. 문자열은 object 가 아니라 DeviceConfig 위반으로 센다
        out.append({"label": f"kiosk-config/{f.name}", "schema": "DeviceConfig", "document": doc})
    return out


# 이미지 -> 그 이미지 컨테이너의 계약 Env 스키마(2026-11-05). ENV_SERVICES 에 없는 서비스·잡은 이미지로 정한다:
# 같은 이미지로 도는 잡도 그 이미지의 Env 계약을 지켜야 한다(12-Factor XII). 손으로 적은 서비스 목록이 platform 이미지와 영역 DB 를 빼먹어
# identity 사용자 등록 잡에 필수 IDENTITY_PUBLIC_URL 이 없는 것을 기동 전에 잡지 못했다(E2E 기동 실패).
IMAGE_ENV = {
    "admin-console": "AdminConsoleEnv", "area-gateway": "AreaGatewayEnv", "backup-store": "BackupStoreEnv",
    "identity": "IdentityEnv", "identity-proxy": "IdentityProxyEnv", "monitoring": "MonitoringEnv",
    "public-ingress": "PublicIngressEnv", "step-ca": "StepCaEnv",
    "survey-db": "AreaDatabaseEnv", "question-authoring-db": "AreaDatabaseEnv", "ops-feedback-db": "AreaDatabaseEnv",
    "release-gate-db": "AreaDatabaseEnv", "identity-db": "AreaDatabaseEnv",
}
_IMAGE_RE = re.compile(r"/openit/([a-z0-9-]+)@")


def _job_services():
    """잡 선언(io.openit.jobs)으로 명령을 받는 compose 서비스(job-* 와 일회성 선행 서비스): 잡 덧씌우기의 정본 표(cli_gen_jobs.JOB_NAMES)"""
    from openit_deploy.wiring.cli_gen_jobs import JOB_NAMES
    return set(JOB_NAMES)


def job_config_documents(services: dict) -> list:
    """Validate the actual mounted input, using the schema named by its owner."""
    docs = []
    for service, spec in sorted(services.items()):
        config = (spec.get("x-openit-job-input") or {}).get("config")
        if config is None:
            continue
        mounts = [v for v in spec.get("volumes", []) if isinstance(v, dict)
                  and v.get("type") == "bind" and v.get("target") == config["container_path"] and v.get("read_only") is True]
        if len(mounts) != 1:
            raise ValueError(f"{service}: declared config must have one read-only bind mount")
        path = pathlib.Path(mounts[0]["source"])
        if not path.is_absolute():
            path = ROOT / path
        try:
            text = path.read_text(encoding="utf-8")
            value = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
        except (OSError, ValueError, yaml.YAMLError):
            raise ValueError(f"{service}: declared config is missing, unreadable or invalid") from None
        docs.append({"label": service + ".config", "schema": config["schema"], "document": value})
    return docs


def build_documents(compose: dict, secrets_dir=None) -> list:
    docs = []
    services = compose.get("services") or {}
    for svc, (schema, wrap) in ENV_SERVICES.items():
        spec = services.get(svc)
        if spec is None: continue   # 이 구성(예: 외부 추론 서버만)에 없는 서비스
        env = {k: ("" if v is None else str(v)) for k, v in (spec.get("environment") or {}).items()}
        docs.append({"label": svc, "schema": schema, "document": wrap(env)})
    for svc, spec in sorted(services.items()):
        # 잡(job-*)은 이미지의 서버 Env 가 아니라 잡 선언 argv 를 그대로 실행한다(진입점이 절대 경로 명령을 그대로 실행, platform 2026-11-06).
        # 잡의 입력은 잡 선언(secret_files·config)이 정한다. 서버 Env 를 잡에 요구하지 않는다
        if svc in ENV_SERVICES or svc.startswith("job-") or svc in _job_services():
            continue
        m = _IMAGE_RE.search(str((spec or {}).get("image", "")))
        if not m or m.group(1) not in IMAGE_ENV:
            continue
        env = {k: ("" if v is None else str(v)) for k, v in ((spec or {}).get("environment") or {}).items()}
        docs.append({"label": svc, "schema": IMAGE_ENV[m.group(1)], "document": env})
    for rel, schema in FILES.items():
        docs.append({"label": rel, "schema": schema, "document": (json.loads if rel.endswith(".json") else yaml.safe_load)((ROOT / rel).read_text(encoding="utf-8"))})
    docs += job_config_documents(services)
    docs += device_config_documents(secrets_dir if secrets_dir is not None else os.environ.get("SECRETS_DIR") or ROOT / "secrets")
    return docs


def main(argv, stdin=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--compose-json", default="-")
    a = ap.parse_args(argv)
    raw = (stdin or sys.stdin).read() if a.compose_json == "-" else pathlib.Path(a.compose_json).read_text(encoding="utf-8")
    try:
        docs = build_documents(json.loads(raw))
    except ValueError as error:
        print("FAIL " + str(error), file=sys.stderr)
        return 1
    r = call(config_contract_check, "ConfigContractCheckRequest", "ConfigContractCheckResult", {"documents": docs}, validators=make_validators({d["schema"] for d in docs}))
    for v in r["violations"]:
        print(f"FAIL {v['label']} ({v['schema']}) {v['where']}: {v['message']}", file=sys.stderr)
    print(f"{'통과' if r['ok'] else '실패'}: 설정·환경 문서 {r['checked']}개를 계약으로 검증했다" + ("" if r["ok"] else f", 위반 {len(r['violations'])}건"))
    return 0 if r["ok"] else 1
