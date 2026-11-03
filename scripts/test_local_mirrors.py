#!/usr/bin/env python3
"""정적 시험: write-local-mirrors.sh 가 git 표준 insteadOf 설정을 쓰고(S14), 그 설정으로 git 이 원격 주소를 로컬 리포로 푼다.
변이 확인: 리포가 없으면 거부(종료 2)한다."""
import os, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENV = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG")}


class T(unittest.TestCase):
    def mk(self, repos):
        ws = Path(tempfile.mkdtemp())
        for r in repos:
            subprocess.run(["git", "init", "-q", str(ws / r)], check=True, env=GENV)
        return ws

    def test_writes_insteadof_and_git_resolves(self):
        ws = self.mk(["boundary-contracts", "link", "model-runtime", "survey-service"])
        p = subprocess.run(["bash", str(ROOT / "scripts/write-local-mirrors.sh"), str(ws)], capture_output=True, text=True, env=GENV)
        self.assertEqual(p.returncode, 0, p.stderr)
        cfg = Path(p.stdout.strip())
        r = subprocess.run(["git", "ls-remote", "ssh://git@github.com/Sdabin1209/openit_link.git"], capture_output=True, text=True, env={**GENV, "GIT_CONFIG_GLOBAL": str(cfg)})
        self.assertEqual(r.returncode, 0, r.stderr)   # 원격이 아니라 로컬 빈 리포로 풀려 성공한다
        self.assertIn(f'[url "{ws}/link"]', cfg.read_text())

    def test_missing_repo_is_refused(self):
        ws = self.mk(["boundary-contracts", "link"])
        p = subprocess.run(["bash", str(ROOT / "scripts/write-local-mirrors.sh"), str(ws)], capture_output=True, text=True, env=GENV)
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main()
