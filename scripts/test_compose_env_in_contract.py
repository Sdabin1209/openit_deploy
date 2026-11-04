#!/usr/bin/env python3
"""정적 점검(계약 3.4.10, CONVENTIONS 13절, 구조 규칙 1·6): compose 의 모든 서비스가 받는 환경 이름은 받는 쪽 계약 Env 스키마(NAME 또는 NAME_FILE)에 있다.
왜: deploy 가 이웃 이미지의 입력을 계약 밖에서 정하면(이웃 구조를 안다) 이웃이 이미지를 바꿀 때 조용히 깨진다. 계약에 없는 이름은 헤드에게 변경 요청할 일이거나 deploy 가 줄일 일이다.
반환 규칙: 서비스 -> 받는 쪽 Env 스키마 대응표(아래 SCHEMA_OF)는 이름 규칙이다. 대응이 없는 서비스에 환경 변수가 있으면 위반이다(대응을 만들 일이 아니라 환경을 줄이거나 계약을 청구할 일).
x-common-env(CommonEnv)와 SSL_CERT_FILE(표준 이름, CommonEnv 설명)은 모든 서비스에 허용한다.
지금 위반이 있으면 그것이 deploy 의 3.4.10 정렬 일 목록이다: 위반 목록을 출력하고 실패한다. 변이 확인: --self-test 가 가짜 compose 로 위반이 잡히는지 본다."""
import re, sys, pathlib, yaml
from boundary_contracts import load_schema

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = ["compose.yaml", "compose.monitoring.yaml", "compose.inference.yaml"]
ALWAYS = {"SSL_CERT_FILE"}   # 표준 이름(OpenSSL). CommonEnv 가 따로 정하지 않는다
AREA_ENV = {"survey-service": "SurveyServiceEnv", "question-authoring": "QuestionAuthoringEnv", "ops-feedback": "OpsFeedbackServerEnv",
            "ops-feedback-ingest": "OpsFeedbackServerEnv", "release-gate": "GateEnv", "model-serving": "ModelServingEnv",
            "model-registry": "ModelRegistryEnv", "dataset-store": "DatasetStoreEnv", "admin-console": "AdminConsoleEnv", "kiosk-frontend": "KioskFrontendEnv"}

JOB_OWNER = {"survey": "SurveyServiceEnv", "question-authoring": "QuestionAuthoringEnv", "ops-feedback": "OpsFeedbackServerEnv", "release-gate": "GateEnv"}

def schema_of(svc: str):
    if svc in AREA_ENV: return AREA_ENV[svc]
    if svc.endswith("-gw"): return "AreaGatewayEnv"
    if svc.endswith(("-cert",)) or svc in ("step-ca", "pki-root", "pki-tokens"): return "StepCaEnv"
    if svc.endswith("-db"): return "AreaDatabaseEnv"
    if svc == "backup-store": return "BackupStoreEnv"
    if svc == "gateway": return "PublicIngressEnv"
    if svc == "identity": return "IdentityEnv"
    if svc == "identity-proxy": return "IdentityProxyEnv"
    if svc in ("prometheus", "alertmanager", "gateway-root", "monitoring-root", "blackbox-exporter", "json-exporter", "node-exporter"): return "MonitoringEnv"
    if svc.startswith("job-"):   # 잡은 소유 영역 이미지(job-<영역 짧은 이름>-...)
        for k, v in JOB_OWNER.items():
            if svc.startswith("job-" + k): return v
        return None
    if svc.endswith("-migrate"): return AREA_ENV.get(svc[:-len("-migrate")] + "-ingest") or AREA_ENV.get(svc[:-len("-migrate")])
    return None

class L(yaml.SafeLoader): pass
for t in ("!reset", "!override"): L.add_multi_constructor(t, lambda l, s, n: None)

def env_of(svc: dict) -> dict:
    e = svc.get("environment") or {}
    if isinstance(e, list): e = dict(x.split("=", 1) if "=" in x else (x, "") for x in e)
    return e

def allowed(name: str, schemas: list) -> bool:
    base = name[:-5] if name.endswith("_FILE") else name
    for s in schemas:
        props = s.get("properties", {})
        if "env" in props and isinstance(props["env"], dict) and "properties" in props["env"]: props = props["env"]["properties"]   # OpsFeedbackServerEnv 는 env 아래에 이름을 둔다
        if name in props or base in props: return True
        if any(re.search(p, name) for p in s.get("patternProperties", {})): return True
    return False

def violations(compose: dict, common: dict) -> list:
    out = []
    common_s = load_schema("CommonEnv")
    for svc, spec in (compose.get("services") or {}).items():
        env = env_of(spec)
        if not env: continue
        sn = schema_of(svc)
        schemas = [common_s] + ([load_schema(sn)] if sn else [])
        for name in sorted(env):
            if name in ALWAYS or name in common: continue
            if not allowed(name, schemas):
                out.append(f"{svc}: {name} 는 {sn or '(받는 쪽 계약 Env 없음)'} 에 없다")
    return out

def run(files) -> list:
    out = []
    for f in files:
        c = yaml.load((ROOT / f).read_text(encoding="utf-8"), Loader=L)
        out += [f"{f}: {v}" for v in violations(c, c.get("x-common-env") or {})]
    return out

if __name__ == "__main__":
    if "--self-test" in sys.argv:   # 변이: 계약에 없는 이름이 잡히고, 계약에 있는 이름은 통과한다
        bad = violations({"services": {"survey-service": {"environment": {"NO_SUCH_INPUT_X": "1"}}}}, {})
        good = violations({"services": {"survey-service": {"environment": {"SSL_CERT_FILE": "/x"}}}}, {})
        assert bad and not good, (bad, good); print("self-test OK"); sys.exit(0)
    v = run(FILES)
    for x in v: print("FAIL", x)
    print(f"계약 밖 환경 이름 {len(v)}개" if v else "OK 모든 환경 이름이 받는 쪽 계약 Env 에 있다")
    sys.exit(1 if v else 0)
