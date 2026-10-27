#!/usr/bin/env python3
"""verify_area.py 자체 시험: Docker·형제 영역 없이 대응표 파싱, 단계 닫힘, 명령 조립, 낡은 이미지 판정을 확인한다."""
import copy, re, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_area as v

HERE = Path(__file__).resolve().parent
WS = Path("/ws")


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = v.load_config()

    def test_real_config_covers_all_areas_and_known_steps(self):
        self.assertEqual(set(self.cfg["areas"]), set(v.AREAS))
        order = v.step_order()
        self.assertIn("5p", order); self.assertEqual(order[:4], ["1", "2", "3", "4"])

    def test_every_mapping_has_why(self):
        for a, s in self.cfg["areas"].items():
            e = s["e2e"]
            if isinstance(e, dict) and not e.get("none"):
                for k, x in e.items():
                    self.assertTrue(x["why"].strip(), (a, k))

    def test_closure_adds_base_and_requires_in_run_order(self):
        steps = v.e2e_steps(self.cfg, "ops-feedback")
        self.assertEqual(steps, [s for s in v.step_order() if s in steps])   # 실행 순서
        for need in ("1", "2", "3", "4", "6", "7", "8"):   # 7 은 2·6, 8 은 6, 6 은 4(base)
            self.assertIn(need, steps)

    def test_step1_only_area_does_not_pull_release_base(self):
        cfg = copy.deepcopy(self.cfg); cfg["areas"]["synthetic-data"]["e2e"] = {"2": {"why": "x"}}
        self.assertEqual(v.e2e_steps(cfg, "synthetic-data"), ["2"])

    def test_deploy_is_fast_and_none_is_none(self):
        self.assertEqual(v.e2e_steps(self.cfg, "deploy"), "fast")
        cfg = copy.deepcopy(self.cfg); cfg["areas"]["model-lab"]["e2e"] = {"none": True, "reason": "내부 로직만"}
        self.assertIsNone(v.e2e_steps(cfg, "model-lab"))

    def _bad(self, mutate, expect):
        cfg = copy.deepcopy(self.cfg); mutate(cfg)
        import yaml
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.yaml"; p.write_text(yaml.safe_dump(cfg))
            with self.assertRaises(v.ConfigError) as cm:
                v.load_config(p)
            self.assertIn(expect, str(cm.exception))

    def test_config_rejects_missing_reason_unknown_step_missing_why_missing_area(self):
        self._bad(lambda c: c["areas"]["model-lab"].update(e2e={"none": True}), "reason")
        self._bad(lambda c: c["areas"]["model-lab"].update(e2e={"99": {"why": "x"}}), "없는 단계 99")
        self._bad(lambda c: c["areas"]["model-lab"].update(e2e={"3": {}}), "why")
        self._bad(lambda c: c["areas"].pop("deploy"), "deploy")
        self._bad(lambda c: c.update(e2e_base=["1", "zz"]), "zz")

    def test_every_e2e_step_is_mapped_to_some_area(self):
        """점검 M5: e2e_steps.py 의 STEPS 에 있는 단계(demo·diag 제외)는 최소 한 영역의 e2e 에 대응해야 한다. 아니면 그 단계를 바꿔도 verify-area 가 돌리지 않는다."""
        import re
        steps = re.findall(r'\("([0-9a-z]+)", step', (HERE / "e2e_steps.py").read_text(encoding="utf-8").split("STEPS = [")[1].split("]")[0])
        cfg = v.load_config(); mapped = set()
        for a, av in cfg["areas"].items():
            e = av.get("e2e")
            if isinstance(e, dict) and "why" not in e: mapped |= set(e)
        missing = [x for x in steps if x not in mapped and not x.startswith("demo") and x != "diag"]
        self.assertEqual(missing, [], f"어느 영역에도 대응되지 않은 E2E 단계: {missing}")

    def test_skippable(self):
        g = self.cfg["default_skip_e2e_paths"]
        self.assertTrue(v.skippable(["docs/a.md", "tests/test_x.py", "README.md"], g))
        self.assertFalse(v.skippable(["docs/a.md", "survey_service/api.py"], g))
        self.assertFalse(v.skippable([], g))   # 근거 없으면 건너뛰지 않는다

    def test_assemble_survey(self):
        plan, notes = v.assemble(self.cfg, "survey-service", WS, changed=["survey_service/x.py"])
        names = [p[0] for p in plan]
        self.assertEqual(names[0], "survey-service 시험"); self.assertEqual(names[1], "check-all (정적 일관성)")
        e2e = plan[-1]
        self.assertIn("--only", e2e[1]); self.assertEqual(e2e[3]["DEPLOY_SKIP_CHECK_ALL"], "1"); self.assertEqual(e2e[3]["DEPLOY_NO_RECORD"], "1")
        self.assertTrue(plan[0][1][0].endswith("survey-service/.venv/bin/python"))
        self.assertTrue(any("5q=" in n for n in notes))   # 근거를 알린다

    def test_assemble_docs_only_skips_e2e(self):
        plan, notes = v.assemble(self.cfg, "survey-service", WS, changed=["docs/design.md"])
        self.assertEqual(len(plan), 2); self.assertTrue(notes[0].startswith("E2E 필요 없음"))

    def test_assemble_no_e2e_reason_and_tests_only(self):
        plan, notes = v.assemble(self.cfg, "release-gate", WS, changed=["a.py"], no_e2e_reason="내부 순수 함수만")
        self.assertEqual(len(plan), 2); self.assertIn("내부 순수 함수만", notes[0])
        plan, notes = v.assemble(self.cfg, "release-gate", WS, changed=["a.py"], tests_only=True)
        self.assertEqual(len(plan), 2)

    def test_assemble_npm_and_deploy_and_stale(self):
        plan, _ = v.assemble(self.cfg, "kiosk-frontend", WS, changed=["app/x.ts"], stale=("kiosk-frontend",))
        self.assertEqual(plan[0][1], ["npm", "test", "--silent"]); self.assertEqual(plan[0][2], WS / "kiosk-frontend")
        self.assertEqual(plan[2][1][-1], "kiosk-frontend"); self.assertIn("build-images.sh", plan[2][1][1])
        self.assertEqual(plan[3][1][-2:], ["--only", "1,2,3,4,5f"])
        plan, _ = v.assemble(self.cfg, "deploy", WS, changed=["compose.yaml"])
        self.assertIn("--fast", plan[-1][1]); self.assertEqual(plan[0][2], v.DEPLOY_ROOT)
        plan, notes = v.assemble(self.cfg, "deploy", WS, changed=["compose.yaml"])
        self.assertNotIn("--only", plan[-1][1])

    def test_is_stale(self):
        rec = {"commit": "abc", "stamp": "bc=v2,te=v4,mr=v7"}
        self.assertFalse(v.is_stale(rec, True, "abc", "bc=v2,te=v4,mr=v7"))
        self.assertTrue(v.is_stale(None, True, "abc", "bc=v2,te=v4,mr=v7"))              # 기록 없음
        self.assertTrue(v.is_stale(rec, False, "abc", "bc=v2,te=v4,mr=v7"))              # 이미지가 로컬에 없다
        self.assertTrue(v.is_stale(rec, True, "abd", "bc=v2,te=v4,mr=v7"))               # 소스 커밋이 다름
        self.assertTrue(v.is_stale({**rec, "commit": "abc-test2"}, True, "abc", rec["stamp"]))   # 시험 접미사
        self.assertTrue(v.is_stale(rec, True, "abc", "bc=v3,te=v4,mr=v7"))               # 의존 태그가 올랐다
        self.assertTrue(v.is_stale({"commit": "abc", "stamp": None}, True, "abc", rec["stamp"]))   # 옛 기록(도장 없음)은 한 번 다시 빌드

    def test_build_images_record_writes_stamp(self):
        s = (HERE / "build-images.sh").read_text(encoding="utf-8")
        self.assertIn('bc=$BC,te=$TE,mr=$MR', s)

    def test_stale_images_with_fake_git_and_docker(self):
        import json, tempfile
        tags = {"DEPLOY_BC_TAG": "v2.0.2", "DEPLOY_TE_TAG": "v0.4.0", "DEPLOY_MR_TAG": "v0.7.3"}
        class P:  # subprocess.CompletedProcess 대용
            def __init__(s, out="", rc=0): s.stdout, s.returncode = out, rc
        def fake_run(argv, cwd=None):
            if argv[0] == "git":
                return P("bbb2222\n" if "model-lab" in argv[2] else "aaa1111\n")   # model-lab 만 소스가 바뀌었다
            return P("{}")   # docker image inspect 성공
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / "build"; env.mkdir(); (env / "images.env").write_text("survey-service img:1 aaa1111 bc=v2.0.2,te=v0.4.0,mr=v0.7.3\nmodel-registry img:2 aaa1111 bc=v2.0.2,te=v0.4.0,mr=v0.7.3\n")
            old = (v._run, v.lib_tags, v.DEPLOY_ROOT)
            v._run, v.lib_tags, v.DEPLOY_ROOT = fake_run, lambda: tags, Path(d)
            try:
                got = v.stale_images(["survey-service", "model-registry", "release-gate"], Path("/ws"))
            finally:
                v._run, v.lib_tags, v.DEPLOY_ROOT = old
        self.assertEqual(got, ["model-registry", "release-gate"])   # 바뀐 소스, 기록 없는 이미지는 낡음. survey-service 는 재사용

    def test_image_src_matches_build_images_sh(self):
        src = (HERE / "build-images.sh").read_text(encoding="utf-8")
        m = re.search(r"declare -A SRC=\((.*?)\)\n", src)
        got = dict(re.findall(r"\[([\w-]+)\]=([\w-]+)", m.group(1)))
        self.assertEqual(got, v.IMAGE_SRC)

    def test_e2e_sh_accepts_flags_and_env_we_use(self):
        s = (HERE / "e2e.sh").read_text(encoding="utf-8")
        for tok in ("--reuse-build", "--only", "--fast", "DEPLOY_SKIP_CHECK_ALL", "DEPLOY_NO_RECORD"):
            self.assertIn(tok, s)
        for a, spec in self.cfg["areas"].items():
            for img in spec["image"]:
                self.assertIn(img, v.IMAGE_SRC)

    def test_cli_dry_run_and_list_without_docker(self):
        import subprocess
        r = subprocess.run([sys.executable, str(HERE / "verify_area.py"), "deploy", "--tests-only", "--dry-run"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("check-all", r.stdout)
        r = subprocess.run([sys.executable, str(HERE / "verify_area.py"), "--list"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0); self.assertIn("model-lab: --only", r.stdout)
        r = subprocess.run([sys.executable, str(HERE / "verify_area.py"), "deploy", "--no-e2e", " "], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)   # 이유 없는 --no-e2e 는 거부


if __name__ == "__main__":
    unittest.main(verbosity=1)
