#!/usr/bin/env python3
"""E2E 가 계약의 열거 값을 낡은 이름으로 기대하지 않는지 보는 정적 자체 시험(Docker 불필요). 사용: python3 scripts/test_e2e_contract_values.py
기대값의 출처: boundary-contracts PUBLIC_API.md StaffAlert: kind 의 알려진 값은 RISK_STOP, CALL_STAFF, USER_CALLED_STAFF 이고 목록 StaffAlert 와 세션 보기 StaffSessionView.alerts[] 가 같은 이름을 쓴다.
`pause_reason` 의 RISK 와 신호 `severity` 의 RISK 는 다른 필드라 그대로다. 서비스의 실제 응답이 아니라 계약이 기대값이다."""
import ast, os, pathlib, unittest

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ.get("E2E_STEPS", HERE / "e2e_steps.py")).read_text(encoding="utf-8")
TREE = ast.parse(SRC)
ALERT_KINDS = {"RISK_STOP", "CALL_STAFF", "USER_CALLED_STAFF"}


class T(unittest.TestCase):
    def test_alert_kind_is_never_compared_with_bare_RISK(self):
        """x["kind"] == "RISK" 꼴(알림 kind 를 뜻하는 비교)이 없다. 검사 종류의 kind(HUMAN_APPROVAL 등)와 섞이지 않게 RISK 만 본다."""
        bad = []
        for n in ast.walk(TREE):
            if isinstance(n, ast.Compare) and isinstance(n.left, ast.Subscript) and isinstance(n.left.slice, ast.Constant) and n.left.slice.value == "kind":
                if any(isinstance(c, ast.Constant) and c.value == "RISK" for c in n.comparators): bad.append(f"e2e_steps.py:{n.lineno}")
        self.assertEqual(bad, [], "알림 kind 를 RISK 로 기대한다(계약: RISK_STOP): " + ", ".join(bad))

    def test_no_stale_comment_saying_session_view_kind_is_RISK(self):
        stale = [i + 1 for i, l in enumerate(SRC.splitlines()) if "StaffViewAlert" in l or "kind 는 RISK(" in l]
        self.assertEqual(stale, [], f"낡은 주석(세션 조회 kind 가 RISK): e2e_steps.py:{stale}")

    def test_risk_alert_kind_asserted_as_RISK_STOP_in_both_views(self):
        n = sum(1 for l in SRC.splitlines() if '["kind"] == "RISK_STOP"' in l)
        self.assertGreaterEqual(n, 2, "목록과 세션 조회 둘 다 RISK_STOP 을 확인해야 한다")


if __name__ == "__main__":
    unittest.main(verbosity=2)
