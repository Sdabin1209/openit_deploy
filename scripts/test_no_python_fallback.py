#!/usr/bin/env python3
"""scripts/*.sh 가 deploy .venv 의 파이썬이 없을 때 시스템 python3 로 조용히 넘어가지 않는다: 거기엔 계약 패키지가 없어 점검이 엉뚱한 이유로 실패한다(TLS worktree 의 "시험 빌드 라벨" 점검). 없으면 lib.sh deploy_py 가 고칠 방법을 말하고 멈춘다. 사용: python3 scripts/test_no_python_fallback.py"""
import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BAD = re.compile(r"\[ -x [^\]]*\] *\|\| *(export )?[A-Za-z_]+=\"?python3\b|\|\| *[A-Za-z_]+=\"?python3\b")


class T(unittest.TestCase):
    def test_no_silent_system_python_fallback(self):
        hits = []
        for f in sorted((ROOT / "scripts").glob("*.sh")):
            for i, l in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if not l.lstrip().startswith("#") and BAD.search(l): hits.append(f"{f.name}:{i}")
        self.assertEqual(hits, [], "시스템 python3 로 넘어가는 대체가 있다(lib.sh deploy_py 를 쓴다)")

    def test_detects_the_pattern(self):
        self.assertTrue(BAD.search('PY=x; [ -x "$PY" ] || PY=python3'))
        self.assertTrue(BAD.search('[ -x "$L" ] || export L=python3'))

    def test_deploy_py_stops_with_the_remedy(self):
        s = (ROOT / "scripts/lib.sh").read_text(encoding="utf-8")
        self.assertIn("deploy .venv 가 없다: bash scripts/prepare-areas.sh", s)


if __name__ == "__main__":
    unittest.main()
