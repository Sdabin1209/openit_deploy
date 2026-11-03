#!/usr/bin/env python3
"""L08(ADR 0055) 배선 정적 시험: ops-feedback 의 서버·잡은 앱 계정(DML만) 접속 문자열과 OPS_DB_SCHEMA=verify 만 받고, 소유자 계정 접속 문자열은 migrate 일회성 서비스만 받는다.
migrate 가 서버·잡보다 먼저 성공해야 한다(depends_on service_completed_successfully). 계정·권한 자체는 test-postgres.sh 가 실제 PostgreSQL 로 본다. 사용: <deploy .venv>/bin/python scripts/test_ops_db_roles_wiring.py"""
import pathlib, re, unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
C = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
S = C["services"]
OWNER = {"db-ops-log-dsn", "db-ops-failure-dsn"}
APP = {"db-ops-log-app-dsn", "db-ops-failure-app-dsn"}


def secrets_of(name): return {x if isinstance(x, str) else x["source"] for x in S[name].get("secrets", [])}


class T(unittest.TestCase):
    def test_only_migrate_gets_owner_dsn(self):
        users = {n for n in S if secrets_of(n) & OWNER}
        self.assertEqual(users, {"ops-feedback-migrate"}, users)

    def test_server_and_job_get_app_dsn_and_verify(self):
        for n in ("ops-feedback-ingest", "job-ops-feedback"):
            self.assertTrue(APP <= secrets_of(n), n)
            env = S[n]["environment"]
            self.assertEqual(env["OPS_LOG_DATABASE_URL_FILE"], "/run/secrets/db-ops-log-app-dsn", n)
            self.assertEqual(env["OPS_FAILURE_DATABASE_URL_FILE"], "/run/secrets/db-ops-failure-app-dsn", n)
        self.assertEqual(S["job-ops-feedback"]["environment"]["OPS_DB_SCHEMA"], "verify")
        envf = (ROOT / "config/ops-feedback-ingest.env").read_text(encoding="utf-8")
        self.assertRegex(envf, r"(?m)^OPS_DB_SCHEMA=verify\b")
        self.assertNotRegex(envf, r"(?m)^OPS_DB_SCHEMA=apply")

    def test_migrate_runs_first_and_is_one_shot(self):
        for n in ("ops-feedback-ingest", "job-ops-feedback"):
            self.assertEqual(S[n]["depends_on"]["ops-feedback-migrate"]["condition"], "service_completed_successfully", n)
        m = S["ops-feedback-migrate"]
        self.assertEqual(m["command"], ["python", "-m", "ops_feedback.admin", "migrate"])
        self.assertEqual(m["restart"], "no"); self.assertEqual(m["networks"], ["db-ops"])
        self.assertNotIn("OPS_DB_SCHEMA", m.get("environment", {}), "migrate 는 apply 가 기본이다: verify 를 주면 스키마를 만들지 못한다")

    def test_app_roles_are_created_with_dml_only(self):
        sh = (ROOT / "config/postgres/initdb/10-roles.sh").read_text(encoding="utf-8")
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES", sh)
        self.assertIn("ALTER DEFAULT PRIVILEGES FOR ROLE", sh)
        self.assertNotRegex(sh, r"GRANT (ALL|CREATE)[^\n]*TO :\"app\"")
        pg = secrets_of("postgres")
        self.assertTrue({"db-ops-log-app-password", "db-ops-failure-app-password"} <= pg)


if __name__ == "__main__":
    unittest.main()
