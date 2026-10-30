#!/usr/bin/env python3
"""E2E 가 응답 필드를 문자열 상수와 비교할 때 그 상수가 계약·문진 스키마의 해당 열거 안에 있는지 AST 로 검사한다(재발 방지: 5n-reask 가 SessionState.state 를 StaffSessionView.status 의 값 "IN_PROGRESS" 와 비교해 실패했다).
검사 1(출처 추적): `c, X = state_dev(...)`/`state_of(...)` 로 받은 X 의 ["state"]·["pause_reason"] 비교는 계약 SessionState 의 열거여야 하고, `X = staff_sv(...)`(또는 staff_sv(...)["status"] 직접)의 ["status"] 비교는 문진 스키마(DEPLOY_SS_TAG)의 StaffSessionView.status 열거여야 한다.
검사 2(일반): 아무 응답이나 `x["키"] == "상수"`, `x.get("키") in ("상수", ...)` 로 비교하면, 계약·문진 스키마 어디에든 이름이 같은 열거 속성이 있는데 상수가 그 열거 어디에도 없으면 어긋남이다. 이름이 같은 열거 속성이 하나도 없으면(스키마에 없는 모양: 잡 출력, 추론 서버 상태 등) 이 검사는 판단하지 않고 그 개수를 알린다(통과로 세지 않는다: 아래 UNCHECKED).
이웃 소스를 읽지 않는다: 계약은 설치된 boundary_contracts 패키지, 문진 스키마는 survey-service 태그 DEPLOY_SS_TAG 의 읽기 전용 복사(git archive)다. 사용: <deploy .venv>/bin/python scripts/test_e2e_enum_constants.py"""
import ast, json, pathlib, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
STEPS = ROOT / "scripts" / "e2e_steps.py"
WS = ROOT.parent if (ROOT.parent / "survey-service").is_dir() else ROOT.parent.parent.parent


# 판단하지 않는 비교(이유 필수): (키, 대상 식, 이유). 대상 식이 "details" 로 시작하는 꼴이 아니라 정확히 같거나(status) details 를 포함해야(reason) 한다
ALLOW = [("reason", "details", "BoundaryError.details 는 사유 코드를 담는 열린 객체다(계약이 값 목록을 열거하지 않는다): 그 키의 사유는 계약 HTTP.md 의 409 사유 규약이 정한다"),
         ("status", "m", "계약 지표 레지스트리(metrics) 항목의 status: 스키마 열거가 아니라 레지스트리 파일의 값(ACTIVE 등)이다"),
         ("status", "by[n]", "같은 지표 레지스트리 항목")]


def ss_tag():
    return subprocess.run(["bash", "-c", 'DEPLOY_NO_DOCKER=1; source "$1/scripts/lib.sh"; echo "$DEPLOY_SS_TAG"', "_", str(ROOT)], capture_output=True, text=True, check=True).stdout.strip()


def enums_of(doc: dict) -> dict:
    """스키마 문서 안의 모든 속성 이름 -> 열거 값 집합(같은 문서의 $ref 를 따라간다)."""
    out = {}

    def resolve(node, depth=0):
        if depth > 8 or not isinstance(node, dict): return None
        if "$ref" in node and node["$ref"].startswith("#/"):
            cur = doc
            for part in node["$ref"][2:].split("/"): cur = cur.get(part, {}) if isinstance(cur, dict) else {}
            return resolve(cur, depth + 1)
        if "enum" in node: return {v for v in node["enum"] if isinstance(v, str)}
        if "const" in node and isinstance(node["const"], str): return {node["const"]}
        vals = set()
        for k in ("oneOf", "anyOf"):
            for sub in node.get(k, []) or []:
                r = resolve(sub, depth + 1)
                if r: vals |= r
        return vals or None

    def walk(node):
        if isinstance(node, dict):
            for name, sub in (node.get("properties") or {}).items():
                r = resolve(sub)
                if r: out.setdefault(name, set()).update(r)
            for v in node.values(): walk(v)
        elif isinstance(node, list):
            for v in node: walk(v)
    walk(doc)
    return out


def load_all():
    import boundary_contracts as bc
    contract = {}
    d = pathlib.Path(bc.__file__).parent / "schemas"
    for f in d.glob("*.schema.json"):
        contract[f.name[:-len(".schema.json")]] = enums_of(json.loads(f.read_text(encoding="utf-8")))
    tmp = tempfile.TemporaryDirectory()
    r = subprocess.run(f'git -C "{WS / "survey-service"}" archive "{ss_tag()}" schema | tar -x -C "{tmp.name}"', shell=True, capture_output=True, text=True)
    assert r.returncode == 0, f"survey-service 에 태그 {ss_tag()} 가 없다: {r.stderr[-200:]}"
    survey = {}
    for f in (pathlib.Path(tmp.name) / "schema" / "schemas").glob("*.json"):
        try: survey[f.stem] = enums_of(json.loads(f.read_text(encoding="utf-8")))
        except ValueError: pass
    return contract, survey, tmp


def key_of(node):
    """x["k"] 또는 x.get("k") -> (대상 노드, k). 아니면 None."""
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str): return node.value, node.slice.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str): return node.func.value, node.args[0].value
    return None


def consts_of(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str): return {node.value}
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)) and node.elts and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts): return {e.value for e in node.elts}
    return None


def comparisons(tree):
    """(줄, 대상 노드, 키, 상수 집합) 목록. ==, !=, in, not in 만 본다."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
            for a, b in ((n.left, n.comparators[0]), (n.comparators[0], n.left)):
                k, c = key_of(a), consts_of(b)
                if k and c: out.append((n.lineno, k[0], k[1], c)); break
    return out


def provenance(tree):
    """변수 이름 -> 'SessionState' | 'StaffSessionView' (함수 안 범위를 가리지 않고 이름으로 모은다: E2E 의 변수 이름이 그 용도로만 쓰인다는 가정이고, 아니면 일반 검사가 잡는다)."""
    prov = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name):
            fn = n.value.func.id
            for t in n.targets:
                if fn in ("state_dev", "state_of") and isinstance(t, ast.Tuple) and len(t.elts) == 2 and isinstance(t.elts[1], ast.Name): prov[t.elts[1].id] = "SessionState"
                if fn == "staff_sv" and isinstance(t, ast.Name): prov[t.id] = "StaffSessionView"
    return prov


class EnumConstants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract, cls.survey, cls._tmp = load_all()
        cls.tree = ast.parse(STEPS.read_text(encoding="utf-8"))
        cls.cmp = comparisons(cls.tree)
        cls.prov = provenance(cls.tree)

    def test_schemas_have_the_enums_we_rely_on(self):
        self.assertEqual(self.contract["SessionState"]["state"], {"ACTIVE", "PAUSED_RISK", "ENDED"})
        self.assertIn("PAUSED_RISK", self.survey["StaffSessionView"]["status"]); self.assertIn("IN_PROGRESS", self.survey["StaffSessionView"]["status"]); self.assertNotIn("IN_PROGRESS", self.contract["SessionState"]["state"])

    def test_provenance_comparisons_use_the_right_schema_enum(self):
        bad, seen = [], 0
        for line, target, key, consts in self.cmp:
            base = target
            while isinstance(base, ast.Call) and isinstance(base.func, ast.Name) and base.func.id == "staff_sv": base = ast.Name(id="__staff_sv__")
            name = base.id if isinstance(base, ast.Name) else None
            kind = "StaffSessionView" if name == "__staff_sv__" else self.prov.get(name)
            if kind == "SessionState" and key in self.contract["SessionState"]:
                seen += 1
                if not consts <= self.contract["SessionState"][key]: bad.append(f"e2e_steps.py:{line}: SessionState.{key} 를 {sorted(consts - self.contract['SessionState'][key])} 와 비교한다(계약 열거 {sorted(self.contract['SessionState'][key])})")
            if kind == "StaffSessionView" and key in self.survey["StaffSessionView"]:
                seen += 1
                if not consts <= self.survey["StaffSessionView"][key]: bad.append(f"e2e_steps.py:{line}: StaffSessionView.{key} 를 {sorted(consts - self.survey['StaffSessionView'][key])} 와 비교한다(문진 스키마 열거 {sorted(self.survey['StaffSessionView'][key])})")
        self.assertGreaterEqual(seen, 8, "출처 추적이 비교를 거의 못 찾았다: 검사가 껍데기가 아닌지 본다")
        self.assertEqual(bad, [])

    def test_general_enum_membership(self):
        pool = {}
        for sch in list(self.contract.values()) + list(self.survey.values()):
            for k, v in sch.items(): pool.setdefault(k, set()).update(v)
        bad, unchecked = [], set()
        for line, target, key, consts in self.cmp:
            text = ast.unparse(target)
            if any(k == key and ((pat in text) if pat == "details" else (pat == text)) for k, pat, _ in ALLOW): unchecked.add(f"{key}(허용: {text[:30]})"); continue
            if key not in pool: unchecked.add(key); continue
            if not consts <= pool[key]: bad.append(f"e2e_steps.py:{line}: [{key!r}] 를 {sorted(consts - pool[key])} 와 비교한다(스키마의 같은 이름 열거 어디에도 없다: {sorted(pool[key])[:8]})")
        print(f"UNCHECKED(스키마에 같은 이름 열거가 없어 판단하지 않은 키): {sorted(unchecked)}")
        self.assertEqual(bad, [])

    def test_old_bug_would_be_caught(self):
        """5n-reask 의 옛 실수: SessionState 응답의 ["state"] 를 "IN_PROGRESS" 와 비교."""
        t = ast.parse('c, s_ = state_dev(A, sid2)\nassert s_["state"] == "IN_PROGRESS"\n')
        prov = provenance(t); (line, target, key, consts), = comparisons(t)
        self.assertEqual(prov.get(target.id), "SessionState")
        self.assertFalse(consts <= self.contract["SessionState"][key])


if __name__ == "__main__":
    unittest.main()
