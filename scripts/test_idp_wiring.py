#!/usr/bin/env python3
"""U82(head ADR 0014, deploy ADR 0057) 정적 시험: Keycloak realm 템플릿과 compose 배선이 결정을 따른다.
(1) realm: 그룹 8개 = 계약의 고정 역할 이름, 자가 등록 켬, 이벤트 저장 365일, 클라이언트 openit-gateway 는 기밀·직접 암호 흐름 꺼짐·PKCE·그룹 매퍼(전체 경로 아님), 시험 사용자 없음, 비밀은 ${...} 자리표시,
(2) compose: keycloak·oauth2-proxy 는 호스트 포트가 없고 비밀은 *_FILE 경로만(환경 변수에 값 없음), 안쪽 네트워크, oauth2-proxy 는 일반 oidc 공급자(keycloak-oidc 아님), 정적 계정 경로(basic_auth)는 없다,
(3) 게이트웨이: 인증 조각은 oauth2-proxy 에 묻고 위조 헤더를 지우며, /auth/* /oauth2/* 만 IdP 로 보내고 master realm 과 /oauth2/auth 는 닫는다.
사용: python3 scripts/test_idp_wiring.py (PyYAML 필요)"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
from compose_nets import nets  # noqa: E402
import json, pathlib, re, subprocess, tempfile, unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROLES = {"staff", "operator", "release-approver", "reviewer", "author", "clinical-reviewer", "clinician", "admin"}   # 계약 CONVENTIONS 6절(3.4.0)의 고정 목록
T = json.loads((ROOT / "config/keycloak/openit-realm.template.json").read_text(encoding="utf-8"))
C = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
S = C["services"]
CF = (ROOT / "config/Caddyfile").read_text(encoding="utf-8")
AUTH = (ROOT / "config/gateway-auth.caddy").read_text(encoding="utf-8")


def code(text): return "\n".join(l.split("#", 1)[0] for l in text.splitlines())


class Realm(unittest.TestCase):
    def test_groups_are_the_contract_roles(self):
        self.assertEqual({g["name"] for g in T["groups"]}, ROLES)

    def test_registration_events_and_admin(self):
        self.assertTrue(T["registrationAllowed"]); self.assertTrue(T["eventsEnabled"]); self.assertEqual(T["eventsExpiration"], 365 * 24 * 3600)
        admin = next(g for g in T["groups"] if g["name"] == "admin")
        self.assertTrue(set(admin["clientRoles"]["realm-management"]) >= {"manage-users", "query-users", "query-groups"})
        self.assertNotIn("realm-admin", admin["clientRoles"]["realm-management"], "최소 권한: 전체 관리자 역할이 아니라 사용자·그룹 관리에 필요한 역할만")
        self.assertEqual([u["username"] for u in T["users"]], ["openit-admin"]); self.assertEqual(T["users"][0]["groups"], ["admin"]); self.assertTrue(T["users"][0]["credentials"][0]["temporary"])

    def test_gateway_client(self):
        (c,) = T["clients"]
        self.assertEqual(c["clientId"], "openit-gateway"); self.assertFalse(c["publicClient"]); self.assertFalse(c["directAccessGrantsEnabled"]); self.assertFalse(c["implicitFlowEnabled"])
        self.assertEqual(c["attributes"]["pkce.code.challenge.method"], "S256")
        (m,) = c["protocolMappers"]
        self.assertEqual((m["protocolMapper"], m["config"]["claim.name"], m["config"]["full.path"]), ("oidc-group-membership-mapper", "groups", "false"))

    def test_no_secret_values_or_test_users_in_template(self):
        s = (ROOT / "config/keycloak/openit-realm.template.json").read_text(encoding="utf-8")
        self.assertIn("${OPENIT_GATEWAY_CLIENT_SECRET}", s); self.assertIn("${OPENIT_INITIAL_ADMIN_PASSWORD}", s)   # 템플릿에는 자리표시만. 값은 gen-keycloak-realm.sh 가 비밀 파일(keycloak-realm.json)에 채운다
        self.assertNotIn("-e2e", s)

    def test_generator_fills_uris_from_gateway_hosts(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "r.json"
            sd = pathlib.Path(d) / "sec"; (sd / "tokens").mkdir(parents=True)
            (sd / "tokens/oauth2-proxy-client-secret").write_text("client-secret-for-test"); (sd / "tokens/openit-initial-admin-password").write_text("initial-pw-for-test\n")
            env = {"GATEWAY_HOSTS": "kiosk.hospital.local:8443, 10.0.0.5:8443", "GATEWAY_PUBLIC_TLS_PORT": "443", "PATH": "/usr/bin:/bin", "SECRETS_DIR": str(sd)}
            subprocess.run(["bash", str(ROOT / "scripts/gen-keycloak-realm.sh"), str(out)], check=True, capture_output=True, env=env)
            doc = json.loads(out.read_text(encoding="utf-8")); c = doc["clients"][0]
            self.assertEqual(c["secret"], "client-secret-for-test"); self.assertEqual(doc["users"][0]["credentials"][0]["value"], "initial-pw-for-test")
            self.assertNotIn("${", out.read_text(encoding="utf-8"))
            self.assertEqual(oct(out.stat().st_mode & 0o777), "0o640", "값이 든 realm 파일은 비밀 파일이다(640)")
        self.assertEqual(sorted(c["redirectUris"]), sorted(["https://kiosk.hospital.local:8443/oauth2/callback", "https://kiosk.hospital.local/oauth2/callback", "https://10.0.0.5:8443/oauth2/callback", "https://10.0.0.5/oauth2/callback"]))
        self.assertEqual(set(c["attributes"]["post.logout.redirect.uris"].split("##")), {"https://kiosk.hospital.local:8443/", "https://kiosk.hospital.local/", "https://10.0.0.5:8443/", "https://10.0.0.5/"})


class Compose(unittest.TestCase):
    def test_no_host_ports_and_inner_networks(self):
        for n in ("keycloak", "oauth2-proxy"):
            self.assertNotIn("ports", S[n], n)
        for net in ("auth", "db-keycloak"):
            self.assertTrue(C["networks"][net].get("internal"), net)
        self.assertEqual(nets(S, "keycloak"), ["auth", "db-keycloak"]); self.assertEqual(nets(S, "oauth2-proxy"), ["auth"])
        self.assertIn("auth", S["gateway"]["networks"])
        self.assertIn("db-keycloak", S["postgres"]["networks"])

    def test_secrets_are_files_not_env_values(self):
        for n in ("keycloak", "oauth2-proxy"):
            for k, v in S[n]["environment"].items():
                if re.search(r"(PASSWORD|SECRET)", k): self.assertTrue(k.endswith("_FILE"), f"{n}.{k}: 비밀은 *_FILE 경로만")
                if k.endswith("_FILE") and k != "SSL_CERT_FILE": self.assertTrue(str(v).startswith("/run/secrets/"), f"{n}.{k}")
        self.assertEqual(S["oauth2-proxy"]["environment"]["OAUTH2_PROXY_PROVIDER"], "oidc", "keycloak-oidc 는 realm 역할을 role: 그룹으로 섞는다")

    def test_oauth2_proxy_urls_and_groups(self):
        e = S["oauth2-proxy"]["environment"]
        self.assertEqual(e["OAUTH2_PROXY_OIDC_GROUPS_CLAIM"], "groups"); self.assertEqual(e["OAUTH2_PROXY_SET_XAUTHREQUEST"], "true")
        self.assertTrue(e["OAUTH2_PROXY_REDEEM_URL"].startswith("https://keycloak/auth/")); self.assertTrue(e["OAUTH2_PROXY_OIDC_JWKS_URL"].startswith("https://keycloak/auth/"))
        self.assertTrue(S["keycloak"]["environment"]["KC_HOSTNAME"].endswith("/auth")); self.assertEqual(S["keycloak"]["environment"]["KC_HTTP_RELATIVE_PATH"], "/auth")

    def test_keycloak_gets_secrets_from_files_not_environment(self):
        k = S["keycloak"]
        self.assertNotIn("entrypoint", k, "엔트리포인트 래퍼가 비밀을 환경 변수로 옮기면 /proc/1/environ 에 값이 남는다")
        self.assertEqual(k["command"][0], "--config-file=/run/secrets/keycloak-secrets.conf", "--config-file 은 kc.sh 의 전역 옵션: start 앞")
        for key in k["environment"]: self.assertNotRegex(key, r"PASSWORD|SECRET", f"keycloak.environment.{key}")
        srcs = [x if isinstance(x, str) else x["source"] for x in k["secrets"]]
        self.assertTrue({"keycloak-secrets.conf", "keycloak-realm.json"} <= set(srcs))
        self.assertFalse((ROOT / "config/keycloak/entrypoint.sh").exists())

    def test_keycloak_is_optimized_and_read_only(self):
        k = S["keycloak"]
        self.assertTrue(k.get("read_only"), "읽기 전용 루트 예외 없음(ADR 0058)")
        self.assertIn("--optimized", k["command"])
        self.assertTrue((ROOT / "images/keycloak/Dockerfile").exists())
        self.assertNotIn("keycloak", (ROOT / "scripts/check-containers.sh").read_text(encoding="utf-8").split("루트 파일시스템")[0].split("\n")[-1])

    def test_keycloak_db_account_exists(self):
        self.assertIn("db-keycloak-password", S["postgres"]["secrets"]); self.assertEqual(S["keycloak"]["environment"]["KC_DB_USERNAME"], "keycloak")


class Gateway(unittest.TestCase):
    def test_no_static_accounts(self):
        self.assertNotIn("basic_auth", code(CF) + code(AUTH))
        self.assertFalse((ROOT / "config/staff-accounts.conf.example").exists()); self.assertFalse((ROOT / "scripts/apply-accounts.sh").exists())

    def test_authenticate_asks_oauth2_proxy_and_strips_forged_headers(self):
        a = code(AUTH)
        self.assertIn("forward_auth https://oauth2-proxy {", a); self.assertIn("uri /oauth2/auth", a)   # U99: oauth2-proxy 도 TLS 사이드카 뒤(ADR 0060)
        for h in ("X-Auth-Request-User", "X-Auth-Request-Preferred-Username", "X-Auth-Request-Groups"):
            self.assertIn(f"request_header -{h}", a, h)
        self.assertIn("order request_header before forward_auth", code(CF))
        self.assertIn("ACCOUNT_PENDING_APPROVAL", a)
        for r in ROLES: self.assertIn(f"@role_{ {'release-approver': 'approver'}.get(r, r) }", a, r)

    def test_idp_routes(self):
        c = code(CF)
        self.assertIn("handle /oauth2/*", c); self.assertIn("reverse_proxy https://oauth2-proxy", c)
        self.assertIn("handle /auth/*", c); self.assertIn("reverse_proxy https://keycloak", c)
        self.assertRegex(c, r"@kcmaster path /auth/realms/master[^\n]*/auth/admin/master"); self.assertIn("@oauth2internal path /oauth2/auth", c)


if __name__ == "__main__":
    unittest.main()
