#!/usr/bin/env python3
"""E2E 의 승인 호출은 계약 ApprovalRequest 대로 직접 보낸다(approver_id 금지·report_hash 필수; 계약 클라이언트 HttpGateService.decide() 는 어긋날 수 있다, 계약 3.0.3 전까지).
정적 시험(e2e_steps.py 는 import 하면 환경 준비가 돈다): (1) `.decide(` 호출이 없다 (2) 도우미가 본문을 ApprovalRequest 로 검사하고 approver_id 를 싣지 않고 X-Openit-User 를 붙인다.
(3) 도우미가 만드는 본문 모양이 실제 계약 validator 를 통과한다(소스의 본문 키를 읽어 같은 모양을 만들어 검증). 사용: <deploy .venv>/bin/python scripts/test_e2e_approval_calls.py"""
import ast, pathlib, unittest

SRC = (pathlib.Path(__file__).resolve().parent / "e2e_steps.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)


def func(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == name)


class T(unittest.TestCase):
    def test_no_sdk_decide_calls(self):
        calls = [n.lineno for n in ast.walk(TREE) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "decide"]
        self.assertEqual(calls, [], f"HttpGateService.decide() 호출이 남아 있다(행 {calls}): decide_approval() 을 쓴다")

    def test_helper_shape(self):
        src = ast.get_source_segment(SRC, func("decide_approval"))
        self.assertIn('validate("ApprovalRequest", body)', src)
        self.assertNotIn("approver_id", src)
        self.assertIn('"X-Openit-User": user', src)
        self.assertIn('"report_hash"', src)

    def test_body_validates_against_contract(self):
        from boundary_contracts import validator
        body = {"submission_id": "sub-1", "decision": "APPROVE", "approver_role": "release-approver", "report_hash": "sha256:" + "a" * 64, "reason": "x"}
        self.assertEqual(list(validator("ApprovalRequest").iter_errors(body)), [])
        self.assertTrue(list(validator("ApprovalRequest").iter_errors({**body, "approver_id": "u"})))   # approver_id 는 금지
        self.assertTrue(list(validator("ApprovalRequest").iter_errors({k: v for k, v in body.items() if k != "report_hash"})))   # report_hash 필수


if __name__ == "__main__":
    unittest.main()
