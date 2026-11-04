#!/usr/bin/env python3
"""정적 시험: E2E 의 백업·복구 구간은 영역의 백업·복구 잡(BackupJobResult)으로만 돌고 deploy 가 영역 데이터를 직접 꺼내지 않는다(계약 3.4.16, RUNTIME R10.1).
(이 파일은 예전에 PostgreSQL 목록 하드코딩과 Keycloak 복구 확인을 지켰다. 목록은 이제 영역 잡이 정하고, identity DB 는 platform 이 백업 잡을 선언하면 더한다.)
사용: python3 scripts/test_e2e_pg_dbs.py"""
import pathlib, re, unittest
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
E2E = (ROOT / "scripts/e2e.sh").read_text(encoding="utf-8")
COMPOSE = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
JOBS = (ROOT / "scripts/e2e_backup_jobs.py").read_text(encoding="utf-8")
SECTION = E2E[E2E.index("영역 백업·복구 (영역이 자기 백업·복구 잡을 돌린다"):E2E.index("if has_s9 rollback")]


class T(unittest.TestCase):
    def test_section_runs_area_jobs_and_judges_by_result(self):
        self.assertIn('e2e_backup_jobs.py" backup', SECTION)
        self.assertIn('e2e_backup_jobs.py" restore', SECTION)
        self.assertIn("e2e_verify_restore.py", SECTION)   # 복구한 데이터는 공개 API 로 다시 읽는다

    def test_no_direct_area_data_access(self):
        for bad in ("pg_dump", "pg_restore", "psql", "pg-fingerprint", "pg-backup", "pg-restore", "fingerprint.sh", "docker exec", '"$DOCKER" exec', "backup.sh", "restore.sh"):
            self.assertNotIn(bad, re.sub(r"^\s*#.*$", "", SECTION, flags=re.M), f"백업 구간이 영역 데이터를 직접 만진다: {bad}")

    def test_every_area_job_exists_in_compose(self):
        for area, name in re.findall(r'"([a-z-]+)": "([a-z-]+)"', JOBS.split("AREAS = ")[1].split("}")[0]):
            for kind in ("backup", "restore"):
                self.assertIn(f"job-{name}-{kind}", COMPOSE["services"], f"{area}: compose 에 job-{name}-{kind} 가 없다")

    def test_deleted_volumes_are_compose_volumes(self):
        vols = re.search(r'AREA_VOLUMES="([^"]*)"', SECTION).group(1).split()
        self.assertGreaterEqual(len(vols), 7)
        for v in vols: self.assertIn(v, COMPOSE["volumes"], f"compose 에 없는 볼륨: {v}")
        self.assertNotIn("backup-store-data", vols)   # 백업 저장소는 남겨야 복구할 수 있다


if __name__ == "__main__":
    unittest.main()
