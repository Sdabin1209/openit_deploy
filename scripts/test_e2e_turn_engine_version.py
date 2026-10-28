#!/usr/bin/env python3
"""E2E 가 쓰는 turn-engine 버전은 lib.sh 의 DEPLOY_TE_TAG 한 출처에서만 온다(audit DP-04 부수 결함).
e2e_steps.py 는 import 하면 인자 해석과 환경 준비가 돌아서, 소스를 AST 로 읽어 확인한다. Docker 불필요.
사용: python3 scripts/test_e2e_turn_engine_version.py"""
import ast, pathlib, unittest

SRC = (pathlib.Path(__file__).resolve().parent / "e2e_steps.py").read_text(encoding="utf-8")


class T(unittest.TestCase):
    def test_no_literal_turn_engine_version_anywhere(self):
        """왜: 같은 사실이 한 E2E 안에서 "0.2.0"(리터럴)과 DEPLOY_TE_TAG(v0.4.2) 두 값으로 갈라져 있었다."""
        lits = [(n.lineno, v.value) for n in ast.walk(ast.parse(SRC)) if isinstance(n, ast.Dict)
                for k, v in zip(n.keys, n.values)
                if isinstance(k, ast.Constant) and k.value == "turn_engine_version" and isinstance(v, ast.Constant)]
        self.assertEqual(lits, [], f"turn_engine_version 리터럴이 있다(행, 값): {lits}")

    def test_every_use_reads_the_single_argument(self):
        """모든 dict 항목이 a.turn_engine_version 만 읽고, 그 인자의 기본값이 DEPLOY_TE_TAG 에서 온다."""
        tree = ast.parse(SRC)
        vals = [ast.unparse(v) for n in ast.walk(tree) if isinstance(n, ast.Dict)
                for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant) and k.value == "turn_engine_version"]
        self.assertTrue(vals)
        self.assertEqual(set(vals), {"a.turn_engine_version"}, vals)
        self.assertIn('os.environ["DEPLOY_TE_TAG"]', SRC)


if __name__ == "__main__":
    unittest.main()
