#!/usr/bin/env python3
"""schemas/*.schema.json 과 scripts/check_schemas.py 자체 점검(audit DP-15). Docker 불필요. 사용: .venv/bin/python scripts/test_check_schemas.py
실제 파일이 통과하는 것(기대값은 파일 자체)과, 일부러 틀린 입력을 스키마가 거부하는 것을 본다."""
import json, pathlib, sys, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_schemas as cs

ROOT = cs.ROOT
GOOD_ROW = {"name": "survey-service", "image": "deploy-build/survey-service:85b3552", "commit": "85b3552", "tags": "bc=v2.6.0,mr=v0.10.0"}
D = "sha256:" + "a" * 64


def errs(name, doc): return cs.validate(name, doc, ROOT)


class T(unittest.TestCase):
    def test_real_files_pass(self):
        paths = {"images-env": ROOT / "build/images.env", "images-lock": ROOT / "locks/images.lock", "verify-areas": ROOT / "config/verify-areas.yaml"}
        self.assertEqual(cs.run(paths, ROOT), 0)

    def test_schemas_are_valid_2020_12(self):
        from jsonschema import Draft202012Validator
        for f in (ROOT / "schemas").glob("*.schema.json"):
            Draft202012Validator.check_schema(json.loads(f.read_text(encoding="utf-8")))

    def test_images_env_rejects(self):
        self.assertEqual(errs("images-env", GOOD_ROW), [])
        self.assertEqual(errs("images-env", {k: v for k, v in GOOD_ROW.items() if k != "tags"}), [])   # 4열은 선택
        for bad in ({**GOOD_ROW, "commit": "HEAD"}, {**GOOD_ROW, "tags": "bc=2.1.1"}, {**GOOD_ROW, "extra": ["x"]}, {k: v for k, v in GOOD_ROW.items() if k != "image"}):
            self.assertTrue(errs("images-env", bad), bad)
        self.assertEqual(cs.parse_images_env("# 주석\n\nsurvey-service img abc1234 bc=v2.6.0,mr=v0.10.0\n")[0][1]["tags"], "bc=v2.6.0,mr=v0.10.0")

    def test_lock_rejects_typos_and_bad_values(self):
        base = {"GATEWAY_IMAGE": "docker.io/library/caddy@" + D, "REGISTRY_IMAGE": "docker.io/library/registry@" + D, "UTIL_IMAGE": "docker.io/library/python@" + D, "POSTGRES_IMAGE": "docker.io/library/postgres@" + D}
        self.assertEqual(errs("images-lock", {**base, "SURVEY_SERVICE_DIGEST": D, "SURVEY_SERVICE_REVISION": "abc1234"}), [])
        for bad in ({**base, "SURVEY_SERVICE_DIGST": D}, {**base, "SURVEY_SERVICE_DIGEST": "sha256:short"}, {**base, "SURVEY_SERVICE_REVISION": "main"}, {k: v for k, v in base.items() if k != "GATEWAY_IMAGE"}, {**base, "UTIL_IMAGE": "python:latest"}):
            self.assertTrue(errs("images-lock", bad), bad)

    def test_verify_areas_rejects(self):
        a = {"image": [], "tests": {"kind": "pytest"}, "e2e": "auto"}
        self.assertEqual(errs("verify-areas", {"default_skip_e2e_paths": [], "areas": {"x": a}}), [])
        for bad in ({**a, "e2e": "none"}, {**a, "e2e": "maybe"}, {**a, "tests": {"kind": "commands"}}, {**a, "typo": 1}):
            self.assertTrue(errs("verify-areas", {"default_skip_e2e_paths": [], "areas": {"x": bad}}), bad)

    def test_cli_exit_codes_and_no_value_echo(self):
        with tempfile.TemporaryDirectory() as t:
            p = pathlib.Path(t) / "lock"; p.write_text("GATEWAY_IMAGE=x\nSURVEY_SERVICE_DIGEST=sha256:SECRETLIKEVALUE\n")
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cs.main(["c", "--files", f"images-lock={p}"])
            self.assertEqual(rc, 1); self.assertNotIn("SECRETLIKEVALUE", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
