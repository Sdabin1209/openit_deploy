#!/usr/bin/env python3
"""E2E 에서 세션을 만든 기기 토큰과 같은 세션 ID 로 공개 API(상태·발화·종료)를 부르는 토큰이 같은지 AST 로 본다.
왜: survey-service 는 세션을 기기별로 구분해 다른 기기 토큰으로 조회하면 404 다(단계 5n-reask 가 기본 기기 토큰으로 기기 A 의 세션을 조회해 실패했다).
방법: 함수(중첩 포함)마다 (1) 세션 시작 호출 `kiosk("/v1/sessions", {"session_id": X, ...})`(기본 기기 토큰 KDEV) 또는 `tcall(T, ...)`·`gk(T, ...)`(토큰 T)에서 X 의 토큰을 정하고
(2) 같은 X 를 기본 기기 토큰(KDEV)으로 부르는 도우미(state_of/public_turn/gk_turn/kiosk)로 부르면, X 를 만든 토큰이 KDEV 가 아닐 때 어긋남이다(5n-reask 의 실수).
다른 토큰으로 일부러 부르는 음성 시험(tcall(B, ...), 위조·없는 토큰이 404/401 이어야 함)과 토큰을 인자로 받는 도우미(state_dev)는 보지 않는다.
읽는 한계: 세션 ID 를 변수 이름으로 따라간다(같은 함수 안, 문자열 조합·다른 함수로 넘긴 경우는 보지 못한다). 사용: python3 scripts/test_e2e_session_tokens.py"""
import ast, pathlib, unittest

SRC = (pathlib.Path(__file__).resolve().parent / "e2e_steps.py").read_text(encoding="utf-8")
DEFAULT_TOKEN_HELPERS = {"state_of", "public_turn", "gk_turn", "kiosk"}   # 기본 기기 토큰(KDEV)으로 부르는 도우미


def names_in(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def analyse(tree):
    problems = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        owner = {}   # 세션 ID 변수 -> 토큰 식
        for c in calls:
            f = c.func.id
            tok = "KDEV" if f == "kiosk" else (ast.unparse(c.args[0]) if f in ("tcall", "gk") and c.args else None)
            if tok is None: continue
            args = [ast.unparse(a) for a in c.args]
            if not any("/v1/sessions" == getattr(a, "value", None) for a in c.args if isinstance(a, ast.Constant)): continue
            for a in c.args:
                if isinstance(a, ast.Dict):
                    for k, v in zip(a.keys, a.values):
                        if isinstance(k, ast.Constant) and k.value == "session_id" and isinstance(v, ast.Name) and (isinstance(a, ast.Dict)):
                            if any(isinstance(x, ast.Constant) and x.value == "SESSION_START" for x in a.values): owner[v.id] = tok
        for c in calls:
            f = c.func.id
            if f not in DEFAULT_TOKEN_HELPERS: continue
            tok = "KDEV"
            for var in set().union(*[names_in(a) for a in c.args] or [set()]) & set(owner):
                if owner[var] != tok:
                    problems.append(f"{fn.name}:{c.lineno}: 세션 {var} 은 {owner[var]} 토큰으로 만들었는데 {f}() 는 {tok} 토큰으로 부른다")
    return problems


class T(unittest.TestCase):
    def test_session_token_matches_creator(self):
        p = analyse(ast.parse(SRC))
        self.assertEqual(p, [], "세션을 만든 토큰과 다른 토큰으로 같은 세션을 부르는 곳이 있다:\n" + "\n".join(p))

    def test_detects_the_5n_reask_mistake(self):
        bad = ast.parse('def f():\n    sid2 = "x"\n    tcall(A, "POST", "/v1/sessions", {"session_id": sid2, "kind": "SESSION_START"})\n    state_of(sid2)\n')
        self.assertEqual(len(analyse(bad)), 1)
        ok = ast.parse('def f():\n    sid2 = "x"\n    tcall(A, "POST", "/v1/sessions", {"session_id": sid2, "kind": "SESSION_START"})\n    state_dev(A, sid2)\n    tcall(A, "GET", f"/v1/sessions/{sid2}/state")\n')
        self.assertEqual(analyse(ok), [])

    def test_finds_creation_calls(self):
        tree = ast.parse(SRC); n = sum(1 for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in ("kiosk", "tcall")
                                       and any(isinstance(a, ast.Constant) and a.value == "/v1/sessions" for a in c.args))
        self.assertGreater(n, 5, "세션 시작 호출을 거의 찾지 못했다(시험이 낡았다)")


if __name__ == "__main__":
    unittest.main()
