#!/usr/bin/env python3
"""e2e_steps.py 가 IMAGES["<서비스>"] 로 읽는 키는 e2e.sh 가 --images 로 넘기는 IMAGES JSON 에 전부 있어야 한다(없으면 단계 2 에서 KeyError: U43 잡 이미지 실행 때 dataset-store 가 빠졌었다).
정적 시험: 소스를 문자열로 읽는다(e2e_steps.py 는 import 하면 환경 준비가 돈다). Docker 불필요. 사용: python3 scripts/test_e2e_images_keys.py"""
import pathlib, re, unittest

H = pathlib.Path(__file__).resolve().parent
STEPS = (H / "e2e_steps.py").read_text(encoding="utf-8")
SH = (H / "e2e.sh").read_text(encoding="utf-8")


class T(unittest.TestCase):
    def test_every_used_key_is_passed(self):
        used = set(re.findall(r'IMAGES\["([a-z][a-z0-9-]*)"\]', STEPS))
        line = next(l for l in SH.splitlines() if l.startswith('IMAGES="{'))
        passed = set(re.findall(r'\\"([a-z][a-z0-9-]*)\\":', line))
        self.assertTrue(used, "e2e_steps.py 에서 IMAGES 키를 찾지 못했다(시험이 낡았다)")
        self.assertEqual(sorted(used - passed), [], f"e2e_steps.py 가 쓰는 IMAGES 키가 e2e.sh 의 IMAGES 에 없다: {sorted(used - passed)}")

    def test_passed_digest_variables_exist_in_lock_use(self):
        line = next(l for l in SH.splitlines() if l.startswith('IMAGES="{'))
        for var in re.findall(r"\$([A-Z_]+_DIGEST)", line):
            self.assertIn(f"{var}", SH, var)


if __name__ == "__main__":
    unittest.main()
