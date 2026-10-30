#!/usr/bin/env python3
"""E2E 문항 양식(test/fixtures/question-form-v2.txt)이 만드는 QuestionBank 가 기준 문진 스키마(lib.sh 의 DEPLOY_SS_TAG, 3.0.0 부터 칸 data_type 필수·option 의 choices/choice_catalog·필수 고정 문장 4개·ID 패턴)를 통과하는지 정적으로 본다(U410).
양식 -> 은행 변환은 question-authoring 의 텍스트 양식 추출기(그 영역의 setup-env 보고가 알려 주는 파이썬으로 돌린다)가 하고, 검증은 survey-service 의 태그 DEPLOY_SS_TAG 의 문진 스키마(git archive 로 꺼낸 읽기 전용 복사)로 한다. 문진 스키마를 고치지 않는다. 추출기가 못 읽거나 이웃/태그가 없으면 건너뛰지 않고 실패한다(검증하지 못한 것을 통과로 세지 않는다).
version 은 저작 서비스가 정하는 값이라 이 시험이 정수 1 로 채운다. 사용: <deploy .venv>/bin/python scripts/test_e2e_form_survey_schema.py"""
import json, pathlib, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
WS = ROOT.parent
sys.path.insert(0, str(ROOT))
from openit_deploy.wiring import setup_env

EXTRACT = '''
import sys, base64, json
from question_authoring.components import extract_textform as X
r = X.run({"data_base64": base64.b64encode(open(sys.argv[1], "rb").read()).decode(), "filename": "form.txt"})
print(json.dumps(r, ensure_ascii=False))
'''


def ss_tag():
    out = subprocess.run(["bash", "-c", 'DEPLOY_NO_DOCKER=1; source "$1/scripts/lib.sh"; echo "$DEPLOY_SS_TAG"', "_", str(ROOT)], capture_output=True, text=True, check=True).stdout.strip()
    return out


class FormPassesSurveySchema(unittest.TestCase):
    def test_bank_from_e2e_form_passes_reference_schema(self):
        tag = ss_tag()
        py = setup_env.env_python("question-authoring", WS)
        self.assertIsNotNone(py, "question-authoring 의 setup-env 환경이 없다(bash scripts/prepare-areas.sh question-authoring)")
        r = subprocess.run([str(py), "-c", EXTRACT, str(ROOT / "test/fixtures/question-form-v2.txt")], capture_output=True, text=True, cwd=str(WS / "question-authoring"))
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        ext = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(ext["status"], "PARSED", ext.get("reason"))
        bank = {**ext["bank"], "version": 1}
        with tempfile.TemporaryDirectory() as d:
            t = subprocess.run(f'git -C "{WS / "survey-service"}" archive "{tag}" schema | tar -x -C "{d}"', shell=True, capture_output=True, text=True)
            self.assertEqual(t.returncode, 0, f"survey-service 에 태그 {tag} 가 없다: {t.stderr[-200:]}")
            # 꺼낸 스키마 패키지를 이 시험 프로세스의 import 경로 맨 앞에 둔다(deploy .venv 에 설치된 다른 버전보다 먼저)
            sys.path.insert(0, f"{d}/schema")
            sys.modules.pop("survey_schema", None)
            try:
                import jsonschema, survey_schema
                self.assertTrue(survey_schema.__file__.startswith(d), "꺼낸 문진 스키마가 아니라 설치된 것이 import 됐다")
                sch = survey_schema.load_schema("QuestionBank")
                errs = sorted(jsonschema.validators.validator_for(sch)(sch).iter_errors(bank), key=lambda e: list(map(str, e.path)))
            finally:
                sys.path.pop(0); sys.modules.pop("survey_schema", None)
        self.assertEqual([f"/{'/'.join(map(str, e.path))}: {e.message[:120]}" for e in errs], [], f"문항 양식으로 만든 QuestionBank 가 {tag} 를 통과하지 못한다(question-authoring 추출기 또는 test/fixtures 를 고친다)")

    def test_tag_is_3_or_newer(self):
        self.assertRegex(ss_tag(), r"^survey-schema-v([3-9]|\d\d+)\.")


if __name__ == "__main__":
    unittest.main()
