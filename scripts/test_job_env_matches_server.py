#!/usr/bin/env python3
"""12-Factor XII: 일회성 관리 잡은 상시 서버와 같은 환경·비밀로 실행한다. 정리 잡이 서버와 갈라지면 계약 Env 선언이 잡을 거부한다(3차 E2E). 이 시험은 (1) 잡 서비스의 environment·secrets 가 서버와 같은지, (2) check_config_contracts 가 잡 서비스도 검사하는지 본다. 사용: python3 scripts/test_job_env_matches_server.py"""
import pathlib, sys, unittest, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
S = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
PAIRS = {"job-survey-purge": "survey-service", "job-question-authoring-purge": "question-authoring", "job-release-gate-prune": "release-gate", "job-release-gate-collect": "release-gate"}


class T(unittest.TestCase):
    def test_same_env_and_secrets(self):
        for j, sv in PAIRS.items():
            self.assertEqual(S[j].get("environment"), S[sv].get("environment"), j)
            self.assertEqual(S[j].get("secrets"), S[sv].get("secrets"), j)
            self.assertEqual(S[j].get("env_file"), S[sv].get("env_file"), j)

    def test_contract_check_covers_jobs(self):
        from openit_deploy.wiring.cli_check_config_contracts import ENV_SERVICES
        for j, sv in PAIRS.items(): self.assertEqual(ENV_SERVICES[j][0], ENV_SERVICES[sv][0], j)

    def test_question_authoring_four_eyes_is_explicit(self):
        # 서비스 기본이 false 로 바뀌었다(L13): 적지 않으면 /v1/reviews 가 403(4차 데모 단계 1). deploy 는 4-eyes 를 명시해서 켠다
        env = (ROOT / "config/question-authoring.env").read_text(encoding="utf-8")
        self.assertRegex(env, r"(?m)^QA_REQUIRE_TWO_PERSON=true$")


if __name__ == "__main__":
    unittest.main()
