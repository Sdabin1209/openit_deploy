#!/usr/bin/env python3
"""deploy 가 내는 설정 파일과 컨테이너 환경(compose 병합 결과) 중 계약 스키마가 있는 것은 전부 계약 validator 로 검증한다(U-config: 옛 `rollback: null` 이 2.7.0 부터 계약을 어기고도 아무 시험에도 걸리지 않았다).
대상 표(CONTRACT)는 파일 -> 스키마 이름. config/ 바로 아래 *.yaml·*.json 이 이 표에도 OWN(deploy 자신의 형식, 이유 필수)에도 없으면 실패한다: 새 설정 파일을 만들 때 계약이 있는지 먼저 따지게 한다.
사용: <deploy .venv>/bin/python scripts/test_config_contracts.py   (계약 패키지가 설치된 파이썬)"""
import json, os, pathlib, re, subprocess, unittest

import yaml
from boundary_contracts import validator

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT = {
    "config/ops-feedback-job.yaml": "OpsFeedbackJobConfig",
    "test/ops-job/test-ops-job.yaml": "OpsFeedbackJobConfig",
    "test/risk-rules.e2e.json": "SurveyRiskRulesFile",
}
OWN = {   # deploy 자신의 형식(계약 스키마 없음)
    "config/exposure-hosts.json": "Caddyfile 상류 호스트 -> 서비스 이름 대응(check-exposure 입력, ADR 0043)",
    "config/exposure-known-diffs.json": "알려진 노출 어긋남 목록과 이유(ADR 0043)",
    "config/verify-areas.yaml": "영역 -> 시험·E2E 단계 대응표(verify_area.py)",
}


# 컨테이너에 주는 최종 환경(compose 병합 결과: environment + env_file + 덧붙임 파일)을 계약 Env 스키마로 검증한다. 서비스 -> (스키마, 감싸기)
ENV_CONTRACT = {
    "survey-service": ("SurveyServiceEnv", lambda env: env),
    "ops-feedback-ingest": ("OpsFeedbackServerEnv", lambda env: {"env": {k: v for k, v in env.items() if k.startswith("OPS_")}}),   # 스키마: OPS_ 접두 변수만 넣는다
}


def compose_sets():
    """검증할 compose 파일 조합: 운영(compose.yaml 단독) + e2e.sh·demo.sh 가 COMPOSE_EXTRA 로 덧붙이는 조합(문자열 그대로 읽는다: 두 번째 목록을 만들지 않는다)."""
    sets = {"운영": ["compose.yaml"]}
    for sh in ("scripts/e2e.sh", "scripts/demo.sh"):
        text = (ROOT / sh).read_text(encoding="utf-8")
        for i, m in enumerate(re.finditer(r'COMPOSE_EXTRA="([^"]*)"', text)):
            parts = m.group(1).split()
            if parts and all(p.startswith("$DEPLOY_ROOT/") for p in parts):
                sets[f"{sh}#{i}"] = ["compose.yaml"] + [p[len("$DEPLOY_ROOT/"):] for p in parts]
    return sets


def render(files):
    """docker compose config 로 병합한 서비스 환경. 필수 변수(${X:?})는 자리표시 값으로 채운다(값은 환경 검증에 쓰이지 않는 이미지 이름 등)."""
    env = dict(os.environ)
    for f in files:
        for v in re.findall(r"\$\{([A-Za-z0-9_]+):\?", (ROOT / f).read_text(encoding="utf-8")): env.setdefault(v, "x")
    cmd = ["docker", "compose", "--project-directory", str(ROOT)] + [a for f in files for a in ("-f", str(ROOT / f))] + ["--profile", "jobs", "config", "--format", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode != 0: return None, r.stderr[-300:]
    return json.loads(r.stdout)["services"], ""


def load(rel):
    p = ROOT / rel
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.suffix in (".yaml", ".yml") else json.loads(p.read_text(encoding="utf-8"))


class T(unittest.TestCase):
    def test_each_config_matches_its_contract(self):
        for rel, schema in CONTRACT.items():
            with self.subTest(rel):
                try: v = validator(schema)
                except Exception: self.skipTest(f"SKIP: 설치된 계약 패키지에 {schema} 가 없다(확인 못 함)")
                errs = [f"{'/'.join(map(str, e.path))}: {e.message[:100]}" for e in v.iter_errors(load(rel))]
                self.assertEqual(errs, [], f"{rel} 가 계약 {schema} 를 어긴다")

    def test_container_env_matches_contract_env_schemas(self):
        """compose 가 서비스에 주는 최종 환경이 계약 Env 스키마를 따른다. 계약 SurveyServiceEnv 결함(SURVEY_MODEL_BACKEND 필수)은 E2E 에서야 survey-service 기동 실패로 드러났다."""
        sets = compose_sets()
        self.assertGreater(len(sets), 1, "e2e.sh/demo.sh 에서 COMPOSE_EXTRA 조합을 읽지 못했다")
        for name, files in sets.items():
            services, err = render(files)
            if services is None:
                self.skipTest(f"SKIP: docker compose config 를 못 돌렸다({name}): {err}")
            for svc, (schema, wrap) in ENV_CONTRACT.items():
                with self.subTest(f"{name} / {svc}"):
                    try: v = validator(schema)
                    except Exception: self.skipTest(f"SKIP: 설치된 계약 패키지에 {schema} 가 없다(확인 못 함)")
                    self.assertIn(svc, services, f"{name}: 서비스 {svc} 가 없다")
                    env = {k: ("" if val is None else str(val)) for k, val in (services[svc].get("environment") or {}).items()}
                    errs = [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:140]}" for e in v.iter_errors(wrap(env))]
                    self.assertEqual(errs, [], f"{name} 의 {svc} 환경이 계약 {schema} 를 어긴다")

    def test_every_config_file_is_classified(self):
        files = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "config").iterdir() if p.is_file() and p.suffix in (".yaml", ".yml", ".json"))
        unknown = [f for f in files if f not in CONTRACT and f not in OWN]
        self.assertEqual(unknown, [], f"계약 스키마 대상인지 deploy 자신의 형식인지 정하지 않은 설정 파일: {unknown} (이 시험의 CONTRACT 또는 OWN 에 이유와 함께 적는다)")

    def test_tables_point_at_existing_files(self):
        for rel in list(CONTRACT) + list(OWN):
            self.assertTrue((ROOT / rel).is_file(), f"{rel} 가 없다(표를 고친다)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
