#!/usr/bin/env python3
"""정적 시험: E2E 의 PostgreSQL 데이터베이스 목록은 lib.sh 의 정본 PG_DBS 이고 e2e.sh 에 하드코딩 목록·개수가 없다(Keycloak 이 백업·복구·지문 검사에서 빠졌던 결함). 사용: python3 scripts/test_e2e_pg_dbs.py"""
import pathlib, re, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
E2E = (ROOT / "scripts/e2e.sh").read_text(encoding="utf-8")
LIB = (ROOT / "scripts/lib.sh").read_text(encoding="utf-8")


class T(unittest.TestCase):
    def test_e2e_uses_canonical_list(self):
        self.assertRegex(E2E, r'PGDBS="\$PG_DBS"')
        self.assertIn("keycloak", re.search(r'^PG_DBS="([^"]*)"', LIB, re.M).group(1))

    def test_no_hardcoded_db_names_or_counts(self):
        self.assertNotRegex(E2E, r'PGDBS="[a-z_ ]+"', "데이터베이스 이름 목록 하드코딩")
        self.assertNotRegex(E2E, r'PostgreSQL 5개|데이터베이스 5\)|= 8 \]', "개수 하드코딩")

    def test_keycloak_is_verified_after_restore(self):
        # keycloak 을 백업·복구 목록에 넣은 수정의 완성 조건: 복구 뒤 시험 사용자가 실제로 로그인되고 역할이 그대로임을 본다(선행 실패는 chk_dep 로 건너뛴다)
        self.assertRegex(E2E, r'chk_dep "복구 후 서비스 기동" "복구 후 Keycloak:[^"]*" \\\n\s+"\$VENV/bin/python" "\$DEPLOY_ROOT/scripts/e2e_verify_keycloak\.py"')
        self.assertTrue((ROOT / "scripts/e2e_verify_keycloak.py").is_file())
        tool = (ROOT / "scripts/e2e_verify_keycloak.py").read_text(encoding="utf-8")
        self.assertIn("oidc_login", tool); self.assertIn("/oauth2/userinfo", tool); self.assertIn("release-approver", tool)


if __name__ == "__main__":
    unittest.main()
