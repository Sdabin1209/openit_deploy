#!/usr/bin/env python3
"""백업 보관 기간 <= 운영 데이터 보존 기간 중 가장 짧은 값(U30, ADR 0044)을 고정한다. 사용: python3 scripts/test_retention_check.py"""
import pathlib, subprocess, sys, tempfile, unittest

H = pathlib.Path(__file__).resolve().parent
ROOT = H.parent
sys.path.insert(0, str(H))
import retention_check as R


def run(*args):
    return subprocess.run([sys.executable, str(H / "retention_check.py"), *args], capture_output=True, text=True)


class T(unittest.TestCase):
    def test_repo_example_value_within_shortest_retention(self):
        p = run("--backup-env", str(ROOT / "config/backup.env.example"))
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)

    def test_reads_every_retention_source(self):
        v = R.data_retentions(ROOT / "config", ROOT / "compose.yaml")
        names = " ".join(v)
        for need in ("survey.env:SURVEY_SESSION_RETENTION_DAYS", "ops-feedback-ingest.env:OPS_RAW_RETENTION_DAYS", "question-authoring.env:QA_DRAFT_RETENTION_DAYS", "question-authoring.env:QA_SOURCE_RETENTION_DAYS",
                     "ops-feedback-job.yaml:retention.raw_days", "ops-feedback-job.yaml:retention.cases_days", "ops-feedback-job.yaml:retention.metrics_days"):
            self.assertIn(need, names)
        self.assertEqual(v["survey.env:SURVEY_SESSION_RETENTION_DAYS"], 90)
        self.assertEqual(min(v.values()), 30)

    def test_longer_backup_is_rejected(self):
        lo = min(R.data_retentions(ROOT / "config", ROOT / "compose.yaml").values())
        self.assertEqual(run("--backup-days", str(lo)).returncode, 0)
        p = run("--backup-days", str(lo + 1)); self.assertEqual(p.returncode, 1); self.assertIn("CRIT", p.stderr)

    def test_synthetic_configs(self):
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t); (t / "a.env").write_text("X_RETENTION_DAYS=10   # 주석\nOTHER=1\n")
            (t / "ops-feedback-job.yaml").write_text("storage:\n  a: 1\nretention:\n  raw_days: 7\n  cases_days: forever\nother:\n  x_days: 1\n")
            (t / "c.yml").write_text("services:\n  s:\n    environment:\n      Y_RETENTION_DAYS: 5\n")
            v = R.data_retentions(t, t / "c.yml")
            self.assertEqual(v, {"a.env:X_RETENTION_DAYS": 10, "ops-feedback-job.yaml:retention.raw_days": 7, "c.yml:Y_RETENTION_DAYS": 5})
            self.assertEqual(run("--backup-days", "5", "--config-dir", str(t), "--compose", str(t / "c.yml")).returncode, 0)
            self.assertEqual(run("--backup-days", "6", "--config-dir", str(t), "--compose", str(t / "c.yml")).returncode, 1)

    def test_no_values_is_unverified_not_pass(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(run("--backup-days", "1", "--config-dir", t, "--compose", t + "/none.yml").returncode, 2)

    def test_backup_check_calls_it(self):
        self.assertIn("retention_check.py", (H / "backup-check.sh").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
