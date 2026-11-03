#!/usr/bin/env python3
"""R4.3 정적: e2e_steps.py 의 time.sleep 은 이유가 줄에 있거나(폴링 간격·속도 제한 등) wait()/settled() 안에 있어야 한다. 복구를 고정 대기로 흉내 내지 않는다.
이유 표시: 같은 줄이나 앞 3줄 안의 주석/독스트링에 "간격", "폴링", "속도 제한", "R4.3" 중 하나. 사용: python3 scripts/test_e2e_no_blind_sleep.py"""
import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
OK = re.compile(r"간격|폴링|속도 제한|R4\.3")


def blind(text):
    L = text.splitlines(); bad = []
    for i, l in enumerate(L):
        if "time.sleep(" not in l or l.lstrip().startswith("#"): continue
        ctx = l + " " + " ".join(L[max(0, i - 3):i])   # 앞 3줄까지 이유 주석으로 본다
        # wait()/settled() 정의 안쪽(함수 본문 첫 줄들)은 폴링 루프다
        j = i
        while j >= 0 and not L[j].startswith("def "): j -= 1
        in_poll = j >= 0 and re.match(r"def (wait|settled|wait_review_report|wait_review_report_c1)\b", L[j])
        if not (OK.search(ctx) or in_poll): bad.append(i + 1)
    return bad


class T(unittest.TestCase):
    def test_e2e_steps_have_no_blind_sleep(self):
        self.assertEqual(blind((ROOT / "scripts/e2e_steps.py").read_text(encoding="utf-8")), [], "이유 없는 time.sleep: wait()/settled() 로 바꾸거나 이유 주석을 단다")

    def test_detects(self):
        self.assertEqual(blind("x = 1\ntime.sleep(3)\n"), [2])
        self.assertEqual(blind("# 폴링 간격\ntime.sleep(3)\n"), [])


if __name__ == "__main__":
    unittest.main()
