#!/usr/bin/env python3
"""e2e_backup_jobs.py 단독 시험(가짜 잡 실행기): ok 결과는 통과, 변이(status error, 결과 줄 없음, 스키마 위반, status ok 인데 종료 코드 1)는 실패. 사용: python3 scripts/test_e2e_backup_jobs.py"""
import json, pathlib, sys, types, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import e2e_backup_jobs as J  # noqa: E402

OK = {"status": "ok", "snapshot_id": "abc12345", "bytes": 10, "started_at": "2026-11-05T00:00:00Z", "finished_at": "2026-11-05T00:00:05Z"}


def fake(res=OK, rc=0, text=None, only=None):
    def run(svc):
        out = text if text is not None else "로그 줄\n" + json.dumps(res) + "\n"
        return types.SimpleNamespace(returncode=rc, stdout=out)
    return run


class T(unittest.TestCase):
    def go(self, kind="backup", **kw): return J.main([kind], runner=fake(**kw))
    def test_all_ok(self): self.assertEqual(self.go(), 0); self.assertEqual(self.go("restore"), 0)
    def test_error_status_fails(self): self.assertEqual(self.go(res={**OK, "status": "error", "error": "x"}, rc=1), 1)
    def test_no_result_line_fails(self): self.assertEqual(self.go(text="그냥 로그\n"), 1)
    def test_schema_violation_fails(self): self.assertEqual(self.go(res={"status": "ok"}), 1)
    def test_ok_status_with_nonzero_exit_fails(self): self.assertEqual(self.go(rc=1), 1)
    def test_restore_default_skips_ca_and_ingress_but_backup_runs_them(self):
        seen = {"backup": [], "restore": []}
        for kind in seen:
            J.main([kind], runner=lambda svc, kind=kind: (seen[kind].append(svc), fake()(svc))[1])
        self.assertIn("job-gateway-backup", seen["backup"]); self.assertIn("job-pki-backup", seen["backup"])
        self.assertNotIn("job-gateway-restore", seen["restore"]); self.assertEqual(len(seen["restore"]), 7)

    def test_unknown_area_is_usage_error(self): self.assertEqual(J.main(["backup", "--areas", "nope"], runner=fake()), 2)


if __name__ == "__main__":
    unittest.main()
