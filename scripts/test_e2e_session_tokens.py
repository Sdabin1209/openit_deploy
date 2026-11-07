#!/usr/bin/env python3
"""E2E 에서 세션을 만든 기기(클라이언트 인증서)와 같은 세션 ID 로 공개 API(상태·발화·종료)를 부르는 기기가 같은지 AST 로 본다.
왜: survey-service 는 세션을 기기별로 구분해 다른 기기로 조회하면 404 다(단계 5n-reask 가 기본 기기로 기기 A 의 세션을 조회해 실패했다). 4.0.0(D136)부터 기기 자격은 토큰이 아니라 클라이언트 인증서(SB.DeviceId)이고, 세션 ID 는 서버가 발급한다.
방법: 함수(중첩 포함)마다 (1) 세션 시작 호출 `kiosk("/v1/sessions", {... "SESSION_START" ...})`(기본 기기 KDEV) 또는 `tcall(T, ...)`·`gk(T, ...)`·`dk(T, ...)`(기기 T)의 결과를 `X = _sid(*호출)` 또는 `c, st = 호출` 뒤 `X = _sid(c, st)` 로 받는 변수 X 의 기기를 정하고
(2) 같은 X 를 기본 기기(KDEV)로 부르는 도우미(state_of/public_turn/gk_turn/kiosk)로 부르면, X 를 만든 기기가 KDEV 가 아닐 때 어긋남이다(5n-reask 의 실수). 세션 시작 본문에 session_id 가 있으면 그 자체가 어긋남이다(SessionStartBody 에 없다).
다른 기기로 일부러 부르는 음성 시험(tcall(B, ...), 위조·없는 자격이 403 이어야 함)과 기기를 인자로 받는 도우미(state_dev)는 보지 않는다.
읽는 한계: 세션 ID 를 변수 이름으로 따라간다(같은 함수 안, 문자열 조합·다른 함수로 넘긴 경우는 보지 못한다). 사용: python3 scripts/test_e2e_session_tokens.py"""
import ast, pathlib, unittest

SRC = (pathlib.Path(__file__).resolve().parent / "e2e_steps.py").read_text(encoding="utf-8")
DEFAULT_TOKEN_HELPERS = {"state_of", "public_turn", "gk_turn", "kiosk"}   # 기본 기기 토큰(KDEV)으로 부르는 도우미


def names_in(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


START_FUNCS = {"kiosk", "_c2_kiosk", "tcall", "gk", "dk"}


def start_call(node):
    """세션 시작 호출이면 (기기 식, 본문 Dict) 아니면 None. 호출 뒤에 [:2] 같은 자르기가 붙어도 본다."""
    if isinstance(node, ast.Subscript): node = node.value
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in START_FUNCS): return None
    if not any(isinstance(a, ast.Constant) and a.value == "/v1/sessions" for a in node.args): return None
    body = next((a for a in node.args if isinstance(a, ast.Dict)), None)
    if body is None or not any(isinstance(v, ast.Constant) and v.value == "SESSION_START" for v in body.values): return None
    return ("KDEV" if node.func.id in ("kiosk", "_c2_kiosk") else ast.unparse(node.args[0])), body


def analyse(tree):
    problems = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        owner = {}   # 세션 ID 변수 -> 기기 식
        resp = {}    # 응답 변수(c, st 의 st) -> 기기 식
        assigns = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)]
        for n in assigns:
            sc = start_call(n.value)
            if sc and isinstance(n.targets[0], ast.Tuple) and len(n.targets[0].elts) >= 2 and isinstance(n.targets[0].elts[1], ast.Name):
                resp[n.targets[0].elts[1].id] = sc[0]
        for n in ast.walk(fn):
            sc = start_call(n) if isinstance(n, ast.Call) else None
            if sc and any(isinstance(k, ast.Constant) and k.value == "session_id" for k in sc[1].keys):
                problems.append(f"{fn.name}:{n.lineno}: 세션 시작 본문에 session_id 가 있다(서버가 발급한다)")
        for n in assigns:
            if isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name) and n.value.func.id == "_sid":
                tgt = n.targets[0]; names = {t.id for t in ast.walk(tgt) if isinstance(t, ast.Name)}
                tok = None
                for a in n.value.args:
                    if isinstance(a, ast.Starred) and start_call(a.value): tok = start_call(a.value)[0]
                    elif isinstance(a, ast.Name) and a.id in resp: tok = resp[a.id]
                if tok:
                    for v in names: owner[v] = tok
        for c in [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]:
            f = c.func.id
            if f not in DEFAULT_TOKEN_HELPERS: continue
            for var in set().union(*[names_in(a) for a in c.args] or [set()]) & set(owner):
                if owner[var] != "KDEV":
                    problems.append(f"{fn.name}:{c.lineno}: 세션 {var} 은 {owner[var]} 기기로 만들었는데 {f}() 는 KDEV 기기로 부른다")
    return problems


class T(unittest.TestCase):
    def test_session_token_matches_creator(self):
        p = analyse(ast.parse(SRC))
        self.assertEqual(p, [], "세션을 만든 토큰과 다른 토큰으로 같은 세션을 부르는 곳이 있다:\n" + "\n".join(p))

    def test_detects_the_5n_reask_mistake(self):
        bad = ast.parse('def f():\n    c, st = tcall(A, "POST", "/v1/sessions", {"kind": "SESSION_START"})[:2]\n    sid2 = _sid(c, st)\n    state_of(sid2)\n')
        self.assertEqual(len(analyse(bad)), 1)
        ok = ast.parse('def f():\n    c, st = tcall(A, "POST", "/v1/sessions", {"kind": "SESSION_START"})[:2]\n    sid2 = _sid(c, st)\n    state_dev(A, sid2)\n    tcall(A, "GET", f"/v1/sessions/{sid2}/state")\n')
        self.assertEqual(analyse(ok), [])
        ok2 = ast.parse('def f():\n    sid = _sid(*kiosk("/v1/sessions", {"kind": "SESSION_START"}))\n    state_of(sid)\n')
        self.assertEqual(analyse(ok2), [])

    def test_detects_client_chosen_session_id_in_start_body(self):
        bad = ast.parse('def f():\n    kiosk("/v1/sessions", {"session_id": sid, "kind": "SESSION_START"})\n')
        self.assertEqual(len(analyse(bad)), 1)

    def test_finds_creation_calls(self):
        tree = ast.parse(SRC); n = sum(1 for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in ("kiosk", "tcall", "_c2_kiosk")
                                       and any(isinstance(a, ast.Constant) and a.value == "/v1/sessions" for a in c.args))
        self.assertGreater(n, 5, "세션 시작 호출을 거의 찾지 못했다(시험이 낡았다)")


if __name__ == "__main__":
    unittest.main()
