#!/usr/bin/env python3
"""영역 시험 시간 상한(check-all 규칙 8)은 근거 있는 상수 하나다(D125: 상한 = 측정 최악 + 여유). 측정 최악 platform 768.38초(2026-11-04)의 2배 이상이고, 소스에 근거 없는 리터럴 900 이 없다.
변이: 상수를 900 으로 되돌리면 이 시험이 실패한다. 사용: python3 scripts/test_area_test_timeout.py"""
import pathlib, re, sys, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from openit_deploy.components import consistency_check as C  # noqa: E402
SRC = (ROOT / "openit_deploy/components/consistency_check.py").read_text(encoding="utf-8")

class T(unittest.TestCase):
    def test_limit_is_twice_the_measured_worst(self):
        self.assertGreaterEqual(C.AREA_TEST_TIMEOUT_SECONDS, 2 * 768)

    def test_subprocess_and_messages_use_the_constant(self):
        body = SRC[SRC.index("def run_area_tests"):]
        self.assertIn("timeout=AREA_TEST_TIMEOUT_SECONDS", body)
        self.assertIsNone(re.search(r"timeout=\d+", body), "시간 상한은 상수로만 쓴다")
        self.assertNotIn("900초", body)

if __name__ == "__main__":
    unittest.main()
