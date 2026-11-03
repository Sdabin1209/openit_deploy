#!/usr/bin/env python3
"""E2E 저작 시나리오가 question-authoring 의 2인 승인 설정(QA_REQUIRE_TWO_PERSON)과 맞는지 읽어서 본다(4차 데모: false 구성에 4-eyes 시나리오를 돌려 /v1/reviews 가 403).
설정 값은 deploy 가 정한다: 구성 어디에도 true 가 없으면 서비스 기본(false, 사용자 결정 L13)이다. 사용: python3 scripts/test_e2e_two_person_scenario.py"""
import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
STEPS = (ROOT / "scripts/e2e_steps.py").read_text(encoding="utf-8")


def two_person_on():
    for f in [ROOT / "config/question-authoring.env", ROOT / "compose.yaml", *(ROOT / "test").glob("compose*.yaml"), ROOT / "demo/compose.demo-mimic.yaml"]:
        if f.exists() and re.search(r"QA_REQUIRE_TWO_PERSON[:=]\s*[\"']?(true|1)\b", f.read_text(encoding="utf-8")): return True
    return False


class T(unittest.TestCase):
    def test_review_calls_match_the_configured_mode(self):
        calls = [l for l in STEPS.splitlines() if '"/v1/reviews"' in l and not l.lstrip().startswith("#")]
        self.assertTrue(calls, "E2E 에 /v1/reviews 호출이 없다(1인 운영의 거부 단언도 없다)")
        for l in calls:
            expects_403 = "== 403" in l
            if two_person_on(): continue   # 2인 승인 구성에서는 성공 시나리오도 허용
            self.assertTrue(expects_403, "2인 승인이 꺼진 구성에서 /v1/reviews 가 성공하길 기대하는 시나리오다: " + l.strip()[:120])

    def test_one_person_flow_asserts_basis_approved_by_author_confirm(self):
        if two_person_on(): self.skipTest("2인 승인 구성")
        self.assertIn('rv["clinical_basis_approved"] is True', STEPS)
        self.assertNotIn("저자 확인 + 검수자 승인 두 검수", STEPS)


if __name__ == "__main__":
    unittest.main()
