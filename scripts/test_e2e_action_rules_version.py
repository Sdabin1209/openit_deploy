#!/usr/bin/env python3
"""E2E 가 매니페스트·잡 설정에 쓰는 action_rules_version 은 설치된 계약의 규칙 데이터(ActionExtractionRules.rules_version)에서만 온다(계약 3.0, D109): 리터럴이 없다.
e2e_steps.py 는 import 하면 인자 해석과 환경 준비가 돌아서 소스를 AST 로 읽는다. Docker 불필요. 사용: python3 scripts/test_e2e_action_rules_version.py"""
import ast, pathlib, unittest

SRC = (pathlib.Path(__file__).resolve().parent / "e2e_steps.py").read_text(encoding="utf-8")


class T(unittest.TestCase):
    def test_no_literal_and_all_use_single_name(self):
        tree = ast.parse(SRC)
        vals = [(n.lineno, ast.unparse(v)) for n in ast.walk(tree) if isinstance(n, ast.Dict)
                for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant) and k.value == "action_rules_version"]
        self.assertTrue(vals)
        self.assertEqual({v for _, v in vals}, {"ACTION_RULES_VERSION"}, vals)

    def test_value_comes_from_contract_rules_data(self):
        self.assertIn('ACTION_RULES_VERSION = load_rules()["rules_version"]', SRC)
        self.assertIn("from boundary_contracts.action_rules import load_rules", SRC)

    def test_no_turn_engine_left(self):
        for bad in ("turn_engine_version", "DEPLOY_TE_TAG", "turn-engine-version"):
            self.assertNotIn(bad, SRC)


if __name__ == "__main__":
    unittest.main()
