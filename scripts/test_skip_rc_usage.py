#!/usr/bin/env python3
"""종료 코드 77 = SKIP 규칙의 점검(automake 관례, run-self-checks.sh): (1) 시험 파일의 TestCase 메서드 안에 sys.exit(77) 이 없다(unittest 는 SystemExit 를 오류로 세어 SKIP 이 FAIL 이 된다: 추론 서버 egress 시험의 실제 결함). skipTest 를 쓴다.
(2) unittest_skip_rc.main 은 통과 0, 실패 1, skipTest 가 있으면 77 로 끝난다(변이: 실패와 skip 이 섞이면 실패가 이긴다). 사용: python3 scripts/test_skip_rc_usage.py"""
import ast, pathlib, subprocess, sys, tempfile, textwrap, unittest
HERE = pathlib.Path(__file__).resolve().parent


def exits_77_in_methods(src: str):
    out = []
    for cls in [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in ast.walk(cls) if isinstance(n, ast.FunctionDef)]:
            for c in ast.walk(fn):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "exit" and c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value == 77:
                    out.append((cls.name, fn.name, c.lineno))
    return out


def run_case(body: str) -> int:
    code = "import sys, unittest\nsys.path.insert(0, %r)\n%s\nif __name__ == '__main__':\n    from unittest_skip_rc import main; main(verbosity=0)\n" % (str(HERE), textwrap.dedent(body))
    with tempfile.TemporaryDirectory(dir=HERE.parent / "build" / "logs") as d:
        f = pathlib.Path(d) / "t.py"; f.write_text(code)
        return subprocess.run([sys.executable, "-W", "ignore", str(f)], capture_output=True).returncode


class T(unittest.TestCase):
    def test_no_exit_77_inside_test_methods(self):
        bad = {f.name: exits_77_in_methods(f.read_text(encoding="utf-8")) for f in HERE.glob("test_*.py") if f.name != "test_skip_rc_usage.py"}
        self.assertEqual({k: v for k, v in bad.items() if v}, {}, "TestCase 메서드 안의 sys.exit(77) 은 FAIL 로 센다: self.skipTest 를 쓴다")

    def test_detector_catches_the_mutation(self):
        self.assertTrue(exits_77_in_methods("import sys,unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        sys.exit(77)\n"))
        self.assertFalse(exits_77_in_methods("import sys\nif True:\n    sys.exit(77)\n"))

    def test_rc_mapping(self):
        ok = "class T(unittest.TestCase):\n    def test_a(self): pass\n"
        self.assertEqual(run_case(ok), 0)
        self.assertEqual(run_case(ok + "    def test_s(self): self.skipTest('x')\n"), 77)
        self.assertEqual(run_case(ok + "    def test_f(self): self.fail('x')\n"), 1)
        self.assertEqual(run_case(ok + "    def test_s(self): self.skipTest('x')\n    def test_f(self): self.fail('x')\n"), 1)


if __name__ == "__main__":
    unittest.main()
