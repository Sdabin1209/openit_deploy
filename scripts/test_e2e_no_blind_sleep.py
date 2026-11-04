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


SH_LOOP = re.compile(r"\b(for|while|until)\b")
SH_FILES = ("e2e.sh", "demo.sh", "export-gateway-ca.sh")   # E2E 가 부르는 셸: 고정 sleep 이 있을 수 있는 곳


def in_loop(L, i):
    """i 줄이 for/while/until 반복 안인가: 위로 올라가며 짝이 맞는 done 을 건너뛰고 닫히지 않은 반복 시작을 찾는다."""
    if SH_LOOP.search(L[i]): return True
    depth = 0
    for j in range(i - 1, -1, -1):
        if L[j].lstrip().startswith("#"): continue
        depth += len(re.findall(r"\bdone\b", L[j]))
        for _ in SH_LOOP.findall(L[j]):
            if depth == 0: return True
            depth -= 1
    return False


def blind_sh(text):
    """셸의 sleep 은 (1) for/while/until 반복(폴링) 안에 있거나 (2) 같은 줄·앞 3줄에 이유 단어가 있어야 한다."""
    L = text.splitlines(); bad = []
    for i, l in enumerate(L):
        if not re.search(r"\bsleep\s+[0-9]", l) or l.lstrip().startswith("#"): continue
        if in_loop(L, i) or OK.search(l + " " + " ".join(L[max(0, i - 3):i])): continue
        bad.append(i + 1)
    return bad


class T(unittest.TestCase):
    def test_e2e_shell_has_no_blind_sleep(self):
        for f in SH_FILES:
            self.assertEqual(blind_sh((ROOT / "scripts" / f).read_text(encoding="utf-8")), [], f"{f}: 반복 밖의 이유 없는 sleep")

    def test_detects_shell(self):
        self.assertEqual(blind_sh("a\nb\nc\nd\ne\nf\ng\nsleep 2\n"), [8])
        self.assertEqual(blind_sh("for i in 1 2; do x; sleep 1; done\n"), [])

    def test_e2e_steps_have_no_blind_sleep(self):
        self.assertEqual(blind((ROOT / "scripts/e2e_steps.py").read_text(encoding="utf-8")), [], "이유 없는 time.sleep: wait()/settled() 로 바꾸거나 이유 주석을 단다")

    def test_detects(self):
        self.assertEqual(blind("x = 1\ntime.sleep(3)\n"), [2])
        self.assertEqual(blind("# 폴링 간격\ntime.sleep(3)\n"), [])


if __name__ == "__main__":
    from unittest_skip_rc import main; main()
