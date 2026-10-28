"""e2e_plan.py 와 e2e.sh/record-e2e.sh 의 SKIP·fail-fast 자체 시험(Docker 불필요). 실행: python3 scripts/test_e2e_plan.py"""
import os, pathlib, re, subprocess, sys, tempfile, unittest
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e2e_plan as P
from e2e_plan import Decl, UNKNOWN

D = {"a": Decl(("r1",), (), "근거", True), "b": Decl(("r2",), ("a",), "근거", True), "c": Decl(("r3",), ("b",), "근거", True),
     "d": Decl(("r4",), (), "근거", True), "u": Decl(("r5",), UNKNOWN, "근거", True)}
ORDER = ["a", "b", "c", "d", "u"]
cur = {n: "h-" + n for n in ORDER}


class T(unittest.TestCase):
    def test_skip_propagation(self):
        self.assertEqual(P.skip_root("b", {"a": "FAIL"}, D), "a")
        self.assertEqual(P.skip_root("c", {"a": "SKIP:a", "b": "SKIP:a"}, D), "a")   # 전이: 뿌리 항목명이 남는다
        self.assertIsNone(P.skip_root("b", {"a": "OK"}, D))
        self.assertIsNone(P.skip_root("d", {"a": "FAIL"}, D))   # 독립 단계는 영향 없다
        self.assertIsNone(P.skip_root("u", {"a": "FAIL"}, D))   # 미확인 deps 는 SKIP 근거가 아니다

    def test_changed_detection(self):
        last = dict(cur)
        sel, why = P.select_changed(ORDER, D, cur, last)
        self.assertEqual(sel, {"u"})   # deps 미확인 단계만 항상 포함
        last["a"] = "old"
        sel, why = P.select_changed(ORDER, D, cur, last)
        self.assertEqual(sel, {"a", "b", "c", "u"}); self.assertEqual(why["b"][:2], "하위")
        last = dict(cur); last["c"] = "old"
        sel, why = P.select_changed(ORDER, D, cur, last)
        self.assertEqual(sel, {"a", "b", "c", "u"}); self.assertEqual(why["a"][:2], "상류")   # 스냅샷이 없어 상태를 재구성
        self.assertNotIn("d", sel)

    def test_unproven_solo_always_included(self):
        d2 = dict(D); d2["d"] = Decl(("r4",), (), "근거", False)
        sel, _ = P.select_changed(ORDER, d2, cur, dict(cur))
        self.assertIn("d", sel)
        self.assertTrue(all(not d.solo for d in P.STEP_DECLS.values()))   # 지금은 아무 단계도 단독 실행을 증명하지 않았다

    def test_hash_changes_with_inputs(self):
        h = lambda c: P.input_hash("a", D, lambda r: f"{r}={c}", lambda s: "code")
        self.assertEqual(h("x"), h("x")); self.assertNotEqual(h("x"), h("y"))
        self.assertNotEqual(P.input_hash("a", D, lambda r: r, lambda s: "c1"), P.input_hash("a", D, lambda r: r, lambda s: "c2"))

    def test_last_pass_roundtrip(self):
        with tempfile.TemporaryDirectory() as t:
            f = pathlib.Path(t) / "x" / "last.json"
            self.assertEqual(P.load_last_pass(f), {}); P.save_last_pass({"a": "h"}, f); self.assertEqual(P.load_last_pass(f), {"a": "h"})

    def test_missing_declaration_detected(self):
        self.assertEqual(P.missing(["a", "zz"], D), ["zz"])
        self.assertEqual(P.missing(P.steps_in_source(), P.STEP_DECLS), [], "e2e_steps.py STEPS 에 선언 없는 단계")
        bad = {"a": Decl(("r",), ("nope",), ""), "b": Decl((), (), "x")}
        probs = P.validate(bad); self.assertTrue(any("nope" in p for p in probs) and any("why" in p for p in probs) and any("repos" in p for p in probs))
        cyc = {"a": Decl(("r",), ("b",), "x"), "b": Decl(("r",), ("a",), "x")}
        self.assertTrue(any("순환" in p for p in P.validate(cyc)))
        self.assertEqual(P.validate(P.STEP_DECLS, P.steps_in_source()), []); self.assertEqual(P.validate(P.SECTION_DECLS), [])

    def test_decls_come_only_from_step_decorators(self):
        """선언은 e2e_steps.py 의 @step 한 곳에만 있다: STEPS 와 같은 집합이고 e2e_plan.py 에 단계 표가 없다."""
        self.assertEqual(set(P.STEP_DECLS), set(P.steps_in_source()))
        self.assertNotIn('"5n": Decl', (HERE / "e2e_plan.py").read_text(encoding="utf-8"))
        self.assertNotIn("risk_signal_recall", (HERE / "e2e_steps.py").read_text(encoding="utf-8"), "폐기 지표 이름이 단계에 박혀 있다: boundary_contracts/metrics.json 에서 읽는다")

    def test_declared_deps_equal_state_analysis(self):
        """deps 는 STATE 읽기/쓰기 ast 분석과 같아야 한다(읽는데 선언 안 함, 안 읽는데 선언함 모두 실패). 미확인(None)도 허용하지 않는다."""
        comp = P.computed_deps(); bad = []
        for n, d in P.STEP_DECLS.items():
            if d.deps == UNKNOWN: bad.append(f"{n}: deps 미확인(None). 계산값 {sorted(comp[n])}")
            elif set(d.deps) != comp[n]: bad.append(f"{n}: 선언 {sorted(d.deps)} != STATE 분석 {sorted(comp[n])}")
        self.assertEqual(bad, [])

    def test_state_analysis_detects_undeclared_read(self):
        with tempfile.TemporaryDirectory() as t:
            f = pathlib.Path(t) / "s.py"
            f.write_text("def a():\n    STATE['x'] = 1\ndef b():\n    return STATE['x'], STATE.get('y'), 'z' in STATE\nSTEPS = [('a', a), ('b', b)]\n")
            self.assertEqual(P.computed_deps(f), {"a": set(), "b": {"a"}})
            f.write_text("def a():\n    STATE[k] = 1\nSTEPS = [('a', a)]\n")
            with self.assertRaises(SystemExit): P.state_access(f)

    def test_metric_registry_reader_fails_loudly_without_file(self):
        """지표 이름은 boundary_contracts/metrics.json 에서만 읽는다. 파일이 없으면 폴백 없이 SystemExit."""
        src = (HERE / "e2e_steps.py").read_text(encoding="utf-8")
        self.assertIn("def metric_registry", src); self.assertIn("raise SystemExit", src.split("def metric_registry")[1].split("def step(")[0])

    def test_e2e_sh_sections_declared(self):
        sh = (HERE / "e2e.sh").read_text(encoding="utf-8")
        for key in ("prep", "s9-front", "s1-8", "s9-sched", "s9-backup", "s9-rollback"): self.assertIn(key, P.SECTION_DECLS)
        self.assertEqual(len(re.findall(r'^sect "[^"]+"', sh, re.M)), 6, "sect 구간 수가 바뀌었다: SECTION_DECLS 를 갱신한다")

    def test_step_status_lines(self):
        rows = [["4", "REAL", "x"], ["4", "FAIL", "x"], ["5", "SKIP", "x"], ["6", "BLOCKED", "x"]]
        self.assertEqual(sorted(P.step_status_lines(rows)), ["4|FAIL", "5|SKIP", "6|PASS"])


def run_bash_harness(script):
    """e2e.sh 의 res/chk/chk_dep/blocked_by/fail-fast 정의만 떼어 와 실행한다(Docker 없이)."""
    sh = (HERE / "e2e.sh").read_text(encoding="utf-8")
    lines = sh.split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith("declare -A STAT"))
    end = next(i for i, l in enumerate(lines) if l.startswith("chk() {"))
    defs = "\n".join(lines[start:end + 1])
    pre = 'FAILS=0; RESULT=(); FAILFAST=${FAILFAST:-0}; sect() { :; }; finish() { echo FINISH-CALLED; }\n'
    return subprocess.run(["bash", "-c", pre + defs + "\n" + script], capture_output=True, text=True)


class BashT(unittest.TestCase):
    def test_skip_not_fail(self):
        r = run_bash_harness('chk "빌드" false; chk_dep "빌드" "publish" true; chk_dep "publish" "적용" true; chk "독립" true\n'
                             'echo "FAILS=$FAILS SKIPS=$SKIPS"; printf "%s\\n" "${RESULT[@]}"')
        o = r.stdout
        self.assertIn("FAILS=1 SKIPS=2", o); self.assertIn("적용|SKIP|SKIP(선행 실패: 빌드)", o)   # 전이 SKIP 도 뿌리를 가리킨다
        self.assertIn("독립|PASS|", o)

    def test_need_array(self):
        r = run_bash_harness('chk "up" false; NEED=("up"); chk "x" true; chk "y" true; echo "FAILS=$FAILS SKIPS=$SKIPS"')
        self.assertIn("FAILS=1 SKIPS=2", r.stdout)

    def test_fail_fast_stops(self):
        r = run_bash_harness('FAILFAST=1; chk "a" true; chk "b" false; chk "c" true; echo NOT-REACHED')
        self.assertEqual(r.returncode, 1); self.assertIn("FINISH-CALLED", r.stdout); self.assertNotIn("NOT-REACHED", r.stdout)
        self.assertNotIn("[PASS] c", r.stdout)
        r = run_bash_harness('chk "b" false; chk "c" true; echo REACHED')
        self.assertIn("REACHED", r.stdout)   # 기본은 끝까지 돈다

    def test_record_separates_skip(self):
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t); f = t / "R.md"
            f.write_text("| h |\n<!-- E2E-ROWS-END -->\n")
            r = subprocess.run(["bash", str(HERE / "record-e2e.sh"), "--file", str(f), "--manual", "--source", "시험", "--commit", "abc", "--mode", "전체",
                                "--pass", "10", "--fail", "1", "--exit", "1", "--ca-fail", "0", "--ca-skip", "0", "--ca-pass", "5", "--skip", "3", "--env", "t"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("SKIP 3개", f.read_text())
            f.write_text("| h |\n<!-- E2E-ROWS-END -->\n")
            r = subprocess.run(["bash", str(HERE / "record-e2e.sh"), "--file", str(f), "--manual", "--source", "시험", "--commit", "abc", "--mode", "전체",
                                "--pass", "10", "--fail", "0", "--exit", "0", "--ca-fail", "0", "--ca-skip", "0", "--ca-pass", "5", "--env", "t"], capture_output=True, text=True)
            self.assertNotIn("SKIP", f.read_text())


if __name__ == "__main__":
    unittest.main()
