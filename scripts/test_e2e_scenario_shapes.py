#!/usr/bin/env python3
"""E2E 문진표 시나리오(단계 1·4·5k)가 보내는 요청의 모양이 계약 3.3.0·문진 스키마 4.0.0 을 따르는지 보는 정적 시험(Docker 불필요, e2e_steps.py 를 실행하지 않고 AST 로 읽는다).
확인: (1) SESSION_START 본문마다 question_set_id 가 있고 FrontendMessage 를 통과한다(문진표가 둘이라 고르지 않은 시작은 400 이므로 시나리오 시작 본문은 모두 싣는다. 의도한 예외는 5k 의 '고르지 않은 시작' 한 곳),
(2) 제출 대상 subject 가 question_sets 목록(1개 이상, ArtifactRef)이라 GateSubmissionRequest 를 통과하고 옛 question_set 이 없다, (3) 문진표 ID 상수가 ID 패턴을 따른다, (4) 기기 설정 배치 칸이 DeviceConfig 를 통과한다.
사용: <deploy .venv>/bin/python -W ignore scripts/test_e2e_scenario_shapes.py"""
import ast, json, pathlib, re, unittest

import boundary_contracts as bc
import jsonschema
import survey_schema
from referencing import Registry, Resource

HERE = pathlib.Path(__file__).resolve().parent
SRC = (HERE / "e2e_steps.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def consts():
    out = {}
    for n in TREE.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Tuple) and all(isinstance(e, ast.Constant) for e in n.value.elts):
            for t, e in zip(n.targets[0].elts if isinstance(n.targets[0], ast.Tuple) else [], n.value.elts): out[t.id] = e.value
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Tuple) and isinstance(n.value, ast.Tuple):
            for t, e in zip(n.targets[0].elts, n.value.elts):
                if isinstance(e, ast.Constant): out[t.id] = e.value
    return out


def survey_validator(name):
    d = pathlib.Path(survey_schema.schema_dir()); reg = Registry()
    for f in d.glob("*.json"): reg = reg.with_resource(f.name, Resource.from_contents(json.loads(f.read_text())))
    s = survey_schema.load_schema(name)
    return jsonschema.validators.validator_for(s)(s, registry=reg)


def start_dicts():
    """kind == SESSION_START 인 딕셔너리 리터럴 -> (줄, {키: 상수 또는 자리표시 값})"""
    out = []
    for n in ast.walk(TREE):
        if isinstance(n, ast.Dict):
            kv = {k.value: v for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant)}
            if isinstance(kv.get("kind"), ast.Constant) and kv["kind"].value == "SESSION_START":
                d = {}
                for k, v in kv.items():
                    d[k] = v.value if isinstance(v, ast.Constant) else ("sess-x" if k == "session_id" else ("qs-ref" if isinstance(v, ast.Name) and v.id == "QS" else "x-1"))
                    if isinstance(v, ast.Name) and v.id == "QS": d[k] = C["QS"]
                    if isinstance(v, ast.Name) and v.id == "QSB": d[k] = C["QSB"]
                    if isinstance(v, ast.Subscript) and k == "question_set_id": d[k] = C["QS"]   # cfg_a["question_set_id"]
                out.append((n.lineno, d))
    return out


C = consts()


class Shapes(unittest.TestCase):
    def test_question_set_ids_follow_the_id_pattern(self):
        for k in ("QS", "QSB"): self.assertRegex(C[k], ID_RE, k)
        self.assertEqual((C["QS"], C["QSB"]), ("health-screening", "health-screening-b"))

    def test_every_session_start_carries_a_valid_question_set_id_except_the_deliberate_one(self):
        v = survey_validator("FrontendMessage"); no_qs = []
        for ln, d in start_dicts():
            errs = list(v.iter_errors(d)); self.assertFalse(errs, f"e2e_steps.py:{ln} SESSION_START 가 FrontendMessage 를 어긴다: {errs[0].message if errs else ''}")
            if "question_set_id" not in d: no_qs.append(ln)
            else: self.assertRegex(d["question_set_id"], ID_RE, f"e2e_steps.py:{ln}")
        self.assertEqual(len(no_qs), 1, f"고르지 않은 시작은 5k 의 한 곳뿐이어야 한다: {no_qs}")

    def test_submission_subject_is_a_question_sets_list(self):
        ns = {"STATE": {"qsb": {"id": "health-screening-b", "version": "1", "content_hash": "sha256:" + "b" * 64}, "qsu": {"id": "qs-u", "version": "1", "content_hash": "sha256:" + "c" * 64}}}
        for n in TREE.body:
            if isinstance(n, ast.FunctionDef) and n.name in ("_subj", "_subj_u"): exec(compile(ast.Module([n], []), "e2e_steps.py", "exec"), ns)
        ref = lambda i, h: {"id": i, "version": "1", "content_hash": "sha256:" + h * 64}
        v = bc.validator("GateSubmissionRequest")
        for subj in (ns["_subj"](ref("health-screening", "a"), ref("lora-a", "d"), ref("lora-b", "e")), ns["_subj_u"](ref("lora-a", "d"), ref("lora-b", "e"))):
            self.assertNotIn("question_set", subj)
            req = {"subject": subj, "requested_by_role": "operator"}
            errs = list(v.iter_errors(req)); self.assertFalse(errs, errs[0].message if errs else "")
        self.assertEqual(len(ns["_subj"](ref("health-screening", "a"), ref("lora-a", "d"), ref("lora-b", "e"))["question_sets"]), 2)

    def test_device_config_placement_field(self):
        v = bc.validator("DeviceConfig")
        self.assertFalse(list(v.iter_errors({"device_token": "t" * 20, "allow_remote_stt": False, "question_set_id": C["QS"]})))
        self.assertTrue(list(v.iter_errors({"device_token": "t" * 20, "question_set_id": "bad id"})))


if __name__ == "__main__":
    unittest.main()
