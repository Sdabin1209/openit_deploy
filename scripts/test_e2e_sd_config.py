#!/usr/bin/env python3
"""E2E 가 만드는 synthetic-data 실행 설정(e2e_steps.py sd_config)이 계약 SyntheticJobConfigRun 을 통과하는지 정적으로 본다(R7: 만드는 쪽이 검증한다. 지금까지는 Import 설정만 시험이 있었다).
e2e_steps.py 는 import 하면 인자 해석이 돌아서 sd_config 함수만 AST 로 꺼내 시험용 전역(상수 몇 개와 작업 폴더)으로 실행한다. 사용: <deploy .venv>/bin/python scripts/test_e2e_sd_config.py"""
import ast, json, pathlib, re, tempfile, unittest

from boundary_contracts import validator
from boundary_contracts.action_rules import load_rules

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "scripts/e2e_steps.py").read_text(encoding="utf-8")


def const(name):   # e2e_steps.py 의 최상위 문자열 상수 한 개를 값으로 읽는다(ast.literal_eval; f-string 은 시험용 값으로 대신한다)
    m = re.search(rf'^{name}\s*=\s*("[^"\n]*")', SRC, re.M)
    return ast.literal_eval(m.group(1)) if m else None


def sd_config_fn(work):
    tree = ast.parse(SRC)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "sd_config")
    ns = {"json": json, "RID": "e2e-test", "ACTION_RULES_VERSION": load_rules()["rules_version"], "SD_UNUSED_DIR": const("SD_UNUSED_DIR"),
          "SD_QA_JOB_URL": const("SD_QA_JOB_URL"), "SD_OPS_JOB_URL": const("SD_OPS_JOB_URL"), "QS": "qs-e2e-test", "QSU": "qs-e2e-test-unseen",
          "STATE": {"qs": [{"version": "1"}, {"version": "2"}]}, "WORK": pathlib.Path(work), "pathlib": pathlib}
    exec(compile(ast.Module([fn], []), "e2e_steps.py", "exec"), ns)
    return ns["sd_config"]


class SdConfig(unittest.TestCase):
    def check(self, **kw):
        with tempfile.TemporaryDirectory() as w:
            p = sd_config_fn(w)("t", **kw) if "seeds" in kw else sd_config_fn(w)("t", True, **kw)
            cfg = json.loads(p.read_text(encoding="utf-8"))
        errs = [f"/{'/'.join(map(str, e.path))}: {e.message[:120]}" for e in validator("SyntheticJobConfigRun").iter_errors(cfg)]
        self.assertEqual(errs, [], f"sd_config({kw}) 가 만든 설정이 SyntheticJobConfigRun 을 어긴다")

    def test_constants_were_found(self):
        for n in ("SD_UNUSED_DIR", "SD_QA_JOB_URL", "SD_OPS_JOB_URL"): self.assertIsNotNone(const(n), f"e2e_steps.py 에서 {n} 을 읽지 못했다")

    def test_plain_run(self): self.check(seeds=True)
    def test_without_seeds(self): self.check(seeds=False)
    def test_with_failure_store(self): self.check(failure=True)

    def test_validator_really_rejects(self):   # 음성 대조: 계약 검증기가 빈 설정을 받아들이면 이 시험은 아무것도 보지 못한다
        self.assertTrue(list(validator("SyntheticJobConfigRun").iter_errors({})))


if __name__ == "__main__":
    unittest.main()
