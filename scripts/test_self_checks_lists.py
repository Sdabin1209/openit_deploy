#!/usr/bin/env python3
"""정적 시험: 자체 점검 목록의 등록 형식. scripts/self-checks.list(기본)와 scripts/self-checks-slow.list(느린 시험, `run-self-checks.sh --slow`)는
`설명 :: 명령` 형식이고, 명령이 가리키는 scripts/ 파일이 있고, 설명이 겹치지 않으며, 느린 시험은 기본 묶음에 들지 않고 `--slow` 에서만 나온다.
느린 시험 목록의 머리말은 "완료 전 1회 필수" 를 말한다. 사용: python3 scripts/test_self_checks_lists.py"""
from child_env import child_env  # R9.1: 하위 프로세스는 최소 환경만(scripts/child_env.py)
import pathlib, re, subprocess, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
LISTS = {"기본": ROOT / "scripts/self-checks.list", "느린": ROOT / "scripts/self-checks-slow.list"}


def entries(path):
    out = []
    for l in path.read_text(encoding="utf-8").splitlines():
        if not l.strip() or l.lstrip().startswith("#"):
            continue
        out.append(l)
    return out


class T(unittest.TestCase):
    def test_format_and_targets(self):
        seen = {}
        for kind, p in LISTS.items():
            for l in entries(p):
                self.assertIn(" :: ", l, f"{kind} 목록 형식 오류: {l[:80]}")
                desc, cmd = l.split(" :: ", 1)
                self.assertTrue(desc.strip() and cmd.strip(), l[:80])
                self.assertNotIn(desc, seen, f"설명 중복: {desc[:60]}")
                seen[desc] = kind
                for f in re.findall(r"scripts/([A-Za-z0-9_.-]+\.(?:sh|py))", cmd):
                    self.assertTrue((ROOT / "scripts" / f).is_file(), f"{kind} 목록이 없는 파일을 가리킨다: scripts/{f}")

    def test_slow_list_is_opt_in(self):
        slow = [l.split(" :: ")[1] for l in entries(LISTS["느린"])]
        if not slow:   # 느린 시험이 없으면(옛 사이드카 인증서 갱신 시험은 platform 이미지로 옮겨 갔다) 기본 목록과 --slow 목록이 같아야 한다
            self.assertEqual(subprocess.run(["bash", str(ROOT / "scripts/run-self-checks.sh"), "--print"], capture_output=True, text=True, env=child_env()).stdout,
                             subprocess.run(["bash", str(ROOT / "scripts/run-self-checks.sh"), "--print", "--slow"], capture_output=True, text=True, env=child_env()).stdout)
            return
        base = subprocess.run(["bash", str(ROOT / "scripts/run-self-checks.sh"), "--print"], capture_output=True, text=True, env=child_env()).stdout
        withslow = subprocess.run(["bash", str(ROOT / "scripts/run-self-checks.sh"), "--print", "--slow"], capture_output=True, text=True, env=child_env()).stdout
        self.assertNotIn("test-cert-renewal.sh", base)
        self.assertIn("test-cert-renewal.sh", withslow)
        self.assertEqual(len(withslow.splitlines()), len(base.splitlines()) + len(slow))

    def test_header_says_run_once_before_done(self):
        head = LISTS["느린"].read_text(encoding="utf-8").split("\n\n")[0]
        self.assertIn("1회", head); self.assertIn("--slow", head)


if __name__ == "__main__":
    unittest.main()
