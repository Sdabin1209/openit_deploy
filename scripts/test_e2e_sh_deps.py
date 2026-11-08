#!/usr/bin/env python3
"""e2e.sh 정적 시험: 단계 1~8 이 남기는 산출물(work/state.json 등)을 읽는 항목은 `chk_dep "단계 1~8"` 이어야 한다. 그냥 chk 면 선행 단계 실패가 SKIP 이 아니라 FAIL 로 번진다(3차 E2E: 단계 1 연결 거부 -> 복구 확인 FAIL).
사용: python3 scripts/test_e2e_sh_deps.py"""
from child_env import child_env  # R9.1: 하위 프로세스는 최소 환경만(scripts/child_env.py)
import pathlib, re, subprocess, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
E2E = (ROOT / "scripts/e2e.sh").read_text(encoding="utf-8")
READERS = ("e2e_verify_restore.py",)   # work/state.json 을 읽는 도구. 새 도구가 생기면 여기에 더한다


class T(unittest.TestCase):
    def test_user_registration_is_skipped_when_stack_start_fails(self):
        line = next(l for l in E2E.splitlines() if l.startswith("chk") and 'scripts/idp-test-users.sh' in l)
        functions = "\n".join(l for l in E2E.splitlines() if l.startswith(("blocked_by()", "chk_dep()")))
        script = "declare -A STAT ROOTF; NEED=(); DEPLOY_ROOT=/not-run; PROJECT=test\n"
        script += 'STAT["compose up --wait (digest 이미지, 읽기 전용 루트, cap_drop ALL)"]=FAIL\n'
        script += 'res() { printf "%s\\n" "$2"; }; chk() { echo EXECUTED; }\n'
        r = subprocess.run(["bash", "-c", script + functions + "\n" + line], capture_output=True, text=True, check=True, env=child_env())
        self.assertEqual(r.stdout.strip(), "SKIP")

    def test_items_reading_step_state_are_dependent_on_the_steps(self):
        bad = []
        for i, l in enumerate(E2E.splitlines(), 1):
            if l.lstrip().startswith("#"): continue
            if any(r in l for r in READERS) or (l.startswith("chk") and "state.json" in l):
                prev = E2E.splitlines()[max(0, i - 3):i]
                if not any(re.match(r'chk_dep "단계 1~8"', x) for x in prev): bad.append(f"e2e.sh:{i}")
        self.assertEqual(bad, [], '선행 단계 산출물을 읽는 항목이 chk_dep 단계 1~8 이 아니다')

    @unittest.skipUnless(any(r in E2E for r in READERS), '읽는 도구를 쓰는 구간 대기(계약 3.4.16 항목 2)')
    def test_reader_is_found(self):
        self.assertIn("e2e_verify_restore.py", E2E)


if __name__ == "__main__":
    unittest.main()
