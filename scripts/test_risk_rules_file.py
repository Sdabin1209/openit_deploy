#!/usr/bin/env python3
"""E2E 용 시험 위험 규칙 파일(test/risk-rules.e2e.json, U48 안 A)이 계약 SurveyRiskRulesFile 을 따르고, 운영 compose 에는 연결돼 있지 않고 E2E 전용 compose 에만 연결돼 있는지 본다.
계약 패키지에 SurveyRiskRulesFile 스키마가 없으면(2.8.0 이전) 스키마 검증은 SKIP 으로 출력하고 통과로 세지 않는다. 사용: <deploy .venv>/bin/python scripts/test_risk_rules_file.py"""
import json, pathlib, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = json.loads((ROOT / "test/risk-rules.e2e.json").read_text(encoding="utf-8"))


class T(unittest.TestCase):
    def test_matches_contract(self):
        from boundary_contracts import validator
        try: v = validator("SurveyRiskRulesFile")
        except Exception: self.skipTest("SKIP: 설치된 계약 패키지에 SurveyRiskRulesFile 이 없다(2.8.0 이상 필요): 확인 못 함")
        self.assertEqual([e.message for e in v.iter_errors(DOC)], [])

    def test_has_a_usable_phrase(self):
        self.assertTrue(DOC["rules"][0]["match"]["any_of"][0]["contains"].strip())

    def test_only_e2e_compose_connects_it(self):
        prod = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertNotIn("SURVEY_RISK_RULES_FILE", prod, "운영 compose 에 시험 규칙이 연결됐다")
        self.assertNotIn("risk-rules.e2e", prod)
        t = (ROOT / "test/compose.risk-rules.yaml").read_text(encoding="utf-8")
        self.assertIn("SURVEY_RISK_RULES_FILE", t); self.assertIn("risk-rules.e2e.json", t)
        self.assertIn("compose.risk-rules.yaml", (ROOT / "scripts/e2e.sh").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
