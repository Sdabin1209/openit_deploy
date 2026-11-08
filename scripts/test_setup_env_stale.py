#!/usr/bin/env python3
"""단독 시험(실행별 상태 격리): setup-env 보고는 이 작업 트리(DEPLOY_ROOT)의 state/ 에만 있고, 보고에는 그것을 만든 영역 커밋이 적힌다. check-all 이 지금 대조하는 영역 커밋과 다르면 낡은 보고로 거부한다.
변이 확인: 다른 커밋의 보고를 넣으면 거부(STALE_REPORT), 같은 커밋이면 통과, 커밋 기록이 없는 보고도 거부한다."""
from child_env import child_env  # R9.1: 하위 프로세스는 최소 환경만(scripts/child_env.py)
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from openit_deploy.wiring import setup_env as SE  # noqa: E402

REP = {"status": "ok", "exit_code": 0, "environment": {"kind": "python-venv", "path": ".venv", "test_command": ["pytest"]}}


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", *a], capture_output=True, text=True, check=True, env=child_env()).stdout.strip()


class T(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()); self.store = Path(tempfile.mkdtemp())
        a = self.ws / "areax"; (a / ".venv/bin").mkdir(parents=True); (a / ".venv/bin/python").write_text("")
        subprocess.run(["git", "init", "-q", str(a)], check=True, env=child_env()); (a / "f").write_text("1"); git(a, "add", "-A"); git(a, "commit", "-qm", "c1")
        self.a = a; os.environ["SETUP_ENV_DIR"] = str(self.store); os.environ["SETUP_ENV_WORK"] = str(self.ws)   # 환경은 사본 폴더(work_root)에 있다: 시험에서는 임시 워크스페이스가 그 자리
        self.store.mkdir(exist_ok=True); (self.store / "areax.json").write_text(json.dumps(REP))

    def tearDown(self):
        os.environ.pop("SETUP_ENV_DIR", None); os.environ.pop("SETUP_ENV_WORK", None)

    def test_same_commit_is_ready(self):
        (self.store / "areax.commit").write_text(git(self.a, "rev-parse", "--short", "HEAD") + "\n")
        self.assertEqual(SE.env_status("areax", self.ws)[1], "")

    def test_report_of_another_commit_is_refused(self):
        (self.store / "areax.commit").write_text(git(self.a, "rev-parse", "--short", "HEAD") + "\n")
        (self.a / "f").write_text("2"); git(self.a, "add", "-A"); git(self.a, "commit", "-qm", "c2")   # 영역이 앞으로 갔다
        why = SE.env_status("areax", self.ws)[1]
        self.assertIn("낡았다", why)

    def test_report_without_commit_record_is_refused(self):
        self.assertIn("낡았다", SE.env_status("areax", self.ws)[1])

    def test_store_is_inside_this_tree_by_default(self):
        os.environ.pop("SETUP_ENV_DIR", None); os.environ.pop("SETUP_ENV_WORK", None)
        self.assertEqual(SE.store(), SE.ROOT / "state" / "setup-env")


if __name__ == "__main__":
    unittest.main()
