"""A job runner may execute only argv supplied by the image declaration."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DeclaredCommand(unittest.TestCase):
    def test_command_override_is_rejected_before_starting_a_container(self):
        with tempfile.TemporaryDirectory() as directory:
            scripts = Path(directory) / "scripts"
            scripts.mkdir()
            (scripts / "run-job.sh").write_bytes((ROOT / "scripts/run-job.sh").read_bytes())
            (scripts / "lib.sh").write_text('dc() { echo "UNEXPECTED_CONTAINER"; return 99; }\n')
            result = subprocess.run(["bash", str(scripts / "run-job.sh"), "job-any", "/bin/sh"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("JobsDeclaration.argv", result.stderr)
            self.assertNotIn("UNEXPECTED_CONTAINER", result.stdout)


if __name__ == "__main__":
    unittest.main()
