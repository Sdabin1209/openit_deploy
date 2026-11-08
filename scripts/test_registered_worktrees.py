"""독립 저장소는 누락으로 보고하고, Git 등록 작업 트리는 소유 영역을 기록한다."""
from child_env import child_env  # R9.1: 하위 프로세스는 최소 환경만(scripts/child_env.py)
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from openit_deploy.components import consistency_check as check
from openit_deploy.wiring.workspace import workspace_of


class Worktrees(unittest.TestCase):
    def test_registered_worktree_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            known = root / "known"
            subprocess.run(["git", "init", "-q", str(known)], check=True, env=child_env())
            subprocess.run(["git", "-C", str(known), "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial", "--allow-empty"], check=True, env=child_env())
            subprocess.run(["git", "-C", str(known), "worktree", "add", "-q", "--detach", str(root / "arbitrary-name")], check=True, env=child_env())
            subprocess.run(["git", "init", "-q", str(root / "wt-unregistered")], check=True, env=child_env())
            self.assertEqual(workspace_of(known), root)
            self.assertEqual(workspace_of(root / "arbitrary-name"), root)
            with patch.object(check, "WS", root), patch.object(check, "AREA_KIND", {"known": "python"}):
                self.assertEqual(check.registered_worktree_aliases(), {"arbitrary-name": "known"})
                self.assertIn("wt-unregistered", check.enum_git_dirs())


if __name__ == "__main__":
    unittest.main()
