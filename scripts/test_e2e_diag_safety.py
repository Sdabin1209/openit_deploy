#!/usr/bin/env python3
"""E2E 실패 진단(e2e.sh collect_diag, e2e_steps.py 의 diag_write)에 비밀이 섞이지 않는지 정적으로 본다(사용자 지시: 진단은 남기되 비밀은 금지, D84).
금지: 환경 변수 목록을 읽는 명령(env, printenv, docker exec, Config.Env, inspect 전체 JSON, compose config). 허용: docker logs, docker ps, docker inspect --format '{{json .State}}'.
또 진단이 정리(teardown) 전에 돌고, 수집 실패가 정리를 막지 않으며(서브셸 + || true), 끝 요약에 진단 폴더 경로가 나온다. 사용: python3 scripts/test_e2e_diag_safety.py"""
import pathlib, re, subprocess, tempfile, unittest

H = pathlib.Path(__file__).resolve().parent
SH = (H / "e2e.sh").read_text(encoding="utf-8")
PY = (H / "e2e_steps.py").read_text(encoding="utf-8")


def func_body(text, name):
    i = text.index(f"{name}() {{")
    depth, j = 0, text.index("{", i)
    for k in range(j, len(text)):
        depth += text[k] == "{"; depth -= text[k] == "}"
        if depth == 0: return text[i:k + 1]
    raise AssertionError(name)


class T(unittest.TestCase):
    def test_collect_diag_reads_no_environment(self):
        body = func_body(SH, "collect_diag")
        code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
        for bad in (r"\bprintenv\b", r"\benv\b", r"docker\S*\s+exec|\"\$DOCKER\"\s+exec", r"Config\.Env", r"compose[^\n]*\bconfig\b", r"\bset\s+-x\b"):
            self.assertIsNone(re.search(bad, code), f"진단 수집에 환경을 읽을 수 있는 명령이 있다: {bad}")
        for m in re.finditer(r'inspect\b[^\n]*', code):
            self.assertIn("{{json .State}}", m.group(0), f"inspect 는 State 만 읽는다: {m.group(0)}")

    def test_collect_diag_never_blocks_cleanup(self):
        body = func_body(SH, "collect_diag")
        self.assertIn("( set +e", body); self.assertIn(") || true", body)
        self.assertRegex(body, r"timeout \d+")   # 멈춘 컨테이너가 정리를 막지 않게 상한을 둔다

    def test_diag_runs_before_teardown_and_prints_path(self):
        cl = func_body(SH, "cleanup")
        self.assertLess(cl.index("collect_diag"), cl.index("down -v"), "진단은 정리 전에 모아야 한다")
        self.assertIn("진단 폴더", cl)

    def test_step_diag_files_hold_no_environment(self):
        for name in ("diag_write", "tail_lines"):
            self.assertIn(f"def {name}", PY)
        seg = PY[PY.index("DIAG = WORK"):PY.index("def run_job(")]
        self.assertNotRegex(seg, r"os\.environ|environ\b|printenv")
        self.assertIn("steps-traceback.log", PY); self.assertIn("traceback.format_exc()", PY)
        self.assertIn('f"{CUR_STEP[0]}-{job_name}.log"', PY)

    def test_collect_diag_runs_with_fake_docker(self):
        """가짜 docker 로 collect_diag 를 실제로 돌려 산출물과 호출한 하위 명령을 본다: ps·logs·inspect(State) 외에는 부르지 않고, 로그·State·목록·$W/diag 가 진단 폴더에 모인다."""
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t); (t / "root/state").mkdir(parents=True); (t / "w/diag").mkdir(parents=True)
            (t / "w/diag/7-synthetic-import.log").write_text("job stderr"); (t / "w/steps.log").write_text("steps")
            fake = t / "docker"
            fake.write_text("#!/usr/bin/env bash\necho \"$@\" >> " + str(t / "calls.txt") + "\ncase \"$1\" in ps) if [[ \"$*\" == *Names* ]]; then echo svc-a; echo svc-b; else echo table; fi;; logs) echo \"log of $4\";; inspect) echo '{\"Status\":\"exited\"}';; esac\n")
            fake.chmod(0o755)
            script = func_body(SH, "collect_diag") + '\nDOCKER=' + str(fake) + ' DEPLOY_ROOT=' + str(t / "root") + ' PROJECT=p W=' + str(t / "w") + '\ncollect_diag; echo "$DIAG_DIR"\n'
            out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
            d = pathlib.Path(out.stdout.strip().splitlines()[-1])
            self.assertTrue((d / "logs/svc-a.log").read_text().startswith("log of"), out.stderr)
            self.assertIn("exited", (d / "state/svc-b.json").read_text())
            self.assertTrue((d / "compose-ps.txt").is_file()); self.assertEqual((d / "7-synthetic-import.log").read_text(), "job stderr"); self.assertEqual((d / "steps.log").read_text(), "steps")
            subs = {l.split()[0] for l in (t / "calls.txt").read_text().splitlines()}
            self.assertLessEqual(subs, {"ps", "logs", "inspect"}, f"허용하지 않은 docker 하위 명령: {subs}")


if __name__ == "__main__":
    unittest.main()
