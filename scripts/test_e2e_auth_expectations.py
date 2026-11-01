#!/usr/bin/env python3
"""E2E 가 인증 실패 응답에 거는 기대가 계약과 같은지 보는 자체 시험(Docker·전체 E2E 불필요). 사용: python3 scripts/test_e2e_auth_expectations.py
기대값의 출처: boundary-contracts CONVENTIONS.md 6절 "401과 403"(RFC 9110 15.5.2·11.6.1, RFC 6750 3절; D106): 토큰이 없거나 틀리면 401 + WWW-Authenticate: Bearer,
맞는 토큰의 권한 부족만 403. 서버 구현의 실제 동작이 아니라 계약이 기대값이다.
1) e2e_steps.py 에 토큰 없이(token 인자 없음/None) 부른 http() 의 상태를 403 과 견주는 곳이 없다(정적, AST).
2) 헬퍼 assert_401_bearer 가 401 + Bearer 만 통과시키고 403, 헤더 없는 401, Basic 안내는 거부한다(가짜 서버로 실제 동작)."""
import ast, json, os, pathlib, unittest

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ.get("E2E_STEPS", HERE / "e2e_steps.py")).read_text(encoding="utf-8")
TREE = ast.parse(SRC)
CALLERS = {"http": 3, "_ds_call": 2}   # 이름 -> 토큰 인자의 위치(0부터)


def _has_403(node):
    return any(isinstance(n, ast.Constant) and n.value == 403 for n in ast.walk(node))


class Static(unittest.TestCase):
    def test_no_403_expected_for_tokenless_calls(self):
        bad = []
        for n in ast.walk(TREE):
            if isinstance(n, ast.Compare) and any(_has_403(c) for c in n.comparators):
                sub = n.left
                call = sub.value if isinstance(sub, ast.Subscript) else None
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in CALLERS:
                    i = CALLERS[call.func.id]
                    tok = call.args[i] if len(call.args) > i else next((k.value for k in call.keywords if k.arg == "token"), None)
                    if tok is None or (isinstance(tok, ast.Constant) and tok.value is None):
                        bad.append(f"e2e_steps.py:{n.lineno}")
        self.assertEqual(bad, [], "토큰 없는 호출에 403 을 기대한다(계약은 401 + WWW-Authenticate: Bearer): " + ", ".join(bad))


class Helper(unittest.TestCase):
    """샌드박스(D123) 뒤 도우미는 순수 함수다: 요청은 게이트웨이·컨테이너 안에서 하고 (상태, 머리글)만 판정한다."""
    @classmethod
    def setUpClass(cls):
        want = {"status_www", "assert_401_bearer"}
        funcs = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name in want]
        cls.ns = {}
        for f in funcs: exec(compile(ast.Module([f], []), "e2e_steps.py", "exec"), cls.ns)
        cls.have = {f.name for f in funcs}

    def test_helper_exists(self):
        self.assertEqual(self.have, {"status_www", "assert_401_bearer"}, "e2e_steps.py 에 401+Bearer 헬퍼가 없다")

    def test_accepts_only_401_with_bearer(self):
        f = self.ns["assert_401_bearer"]
        f("ok", 401, {"WWW-Authenticate": "Bearer realm=x"})
        f("ok-lower", 401, {"www-authenticate": "Bearer"})
        for st, h in ((403, {"WWW-Authenticate": "Bearer"}), (401, {}), (401, {"WWW-Authenticate": "Basic realm=x"}), (200, {"WWW-Authenticate": "Bearer"})):
            with self.assertRaises(AssertionError, msg=(st, h)): f("bad", st, h)


if __name__ == "__main__":
    unittest.main(verbosity=2)
