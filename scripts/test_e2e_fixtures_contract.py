#!/usr/bin/env python3
"""E2E 가 이웃 서비스에 주는 입력의 모양을 E2E 전에 정적으로 확인한다(단계 5~8 감사에서 놓쳤던 세 가지).
(1) 문항 양식 fixture(test/fixtures/question-form-v2.txt)의 모든 칸에 자료형이 있고 값(단위·범위·선택지)이 학습 데이터셋 question_fields 와 같다: survey-service 는 3.0.0부터 칸 규격이
    없는 칸이 하나라도 있으면 릴리스를 MISSING_FIELD_SPEC 으로 거부한다(option 칸은 선택지도 필요). 양식 문법은 question-authoring ADR 0018(`자료형:`, `값 단위:`, `최소:`, `최대:`, `초과 최소:`, `선택지:`).
(2) e2e_steps.py 가 /v1/approvals 로 보내는 본문(decision·approver_role 을 가진 dict)이 계약 ApprovalRequest 의 키 집합을 지킨다(approver_id·pipeline_schema_version 금지, report_hash 필수).
(3) /readyz 의 reask_limit 은 {"active", "max_consecutive"} 객체다: E2E 가 정수로 읽지 않는다.
사용: <deploy .venv>/bin/python scripts/test_e2e_fixtures_contract.py   (계약 패키지가 설치된 파이썬)"""
import ast, json, pathlib, re, unittest

H = pathlib.Path(__file__).resolve().parent
ROOT = H.parent
FORM = (ROOT / "test/fixtures/question-form-v2.txt").read_text(encoding="utf-8")
REF = json.loads((ROOT / "test/fixtures/question-fields-ref.json").read_text(encoding="utf-8"))["fields"]
STEPS = (H / "e2e_steps.py").read_text(encoding="utf-8")
SPEC_KEYS = {"자료형": "data_type", "값 단위": "unit", "최소": "minimum", "최대": "maximum", "초과 최소": "exclusive_minimum", "선택지": "options"}


def parse_form():
    """양식에서 문항.칸 -> 칸 규격 줄(자료형·값 단위·최소·최대·초과 최소·선택지)을 읽는다. 슬롯 줄 이후 다음 슬롯/문항/빈 줄 전까지가 그 칸의 줄이다."""
    slots, q, cur = {}, None, None
    for line in FORM.splitlines():
        m = re.match(r"문항 (\S+):", line)
        if m: q, cur = m.group(1), None; continue
        m = re.match(r"슬롯 (\w+):", line)
        if m: cur = f"{q}.{m.group(1)}"; slots[cur] = {}; continue
        if not line.strip(): cur = None; continue
        k, _, v = line.partition(":")
        if cur and k.strip() in SPEC_KEYS:
            key = SPEC_KEYS[k.strip()]; v = v.strip()
            slots[cur][key] = [x.strip() for x in v.split(",")] if key == "options" else (v if key in ("data_type", "unit") else (float(v) if "." in v else int(v)))
    return slots


class T(unittest.TestCase):
    def test_every_slot_has_a_field_spec_equal_to_dataset(self):
        slots = parse_form()
        self.assertEqual(sorted(slots), sorted(REF), "양식의 칸 집합이 데이터셋 question_fields 와 다르다")
        missing = [k for k, v in slots.items() if "data_type" not in v or (v["data_type"] == "option" and not v.get("options"))]
        self.assertEqual(missing, [], f"칸 규격이 없는 칸(survey-service 가 MISSING_FIELD_SPEC 으로 거부): {missing}")
        for k, v in slots.items():
            self.assertEqual(v, REF[k], f"{k}: 양식의 칸 규격이 데이터셋과 다르다")

    def test_ref_covers_52_fields(self):
        self.assertEqual(len(REF), 52)

    def test_approval_bodies_follow_contract(self):
        from boundary_contracts import load_schema
        sch = load_schema("ApprovalRequest"); allowed, required = set(sch["properties"]), set(sch["required"])
        bodies = []
        for n in ast.walk(ast.parse(STEPS)):
            if isinstance(n, ast.Dict):
                keys = [k.value for k in n.keys if isinstance(k, ast.Constant)]
                if "decision" in keys and "approver_role" in keys: bodies.append((n.lineno, set(keys), None in n.keys))
        self.assertTrue(bodies, "승인 본문 dict 를 찾지 못했다(시험이 낡았다)")
        for ln, keys, spread in bodies:
            self.assertEqual(sorted(keys - allowed), [], f"행 {ln}: ApprovalRequest 에 없는 키(approver_id·pipeline_schema_version 은 금지)")
            if not spread: self.assertEqual(sorted(required - keys), [], f"행 {ln}: ApprovalRequest 필수 키가 없다")

    def test_reask_limit_is_read_as_object(self):
        self.assertIn('rl.get("max_consecutive")', STEPS)
        self.assertIn('rl.get("active")', STEPS)
        self.assertNotRegex(STEPS, r'N = rz\.get\("reask_limit"\)')


if __name__ == "__main__":
    unittest.main()
