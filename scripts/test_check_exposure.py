#!/usr/bin/env python3
"""규칙 D124. check_exposure.py 시험: 실제 config/Caddyfile 에 대해 (1) 일치하는 라벨은 통과 (2) 흔한 어긋남(역할·상류 토큰·시간 제한·거부 경로 열림·라벨에 없는 노출·root 사용자·포트)을 잡는다.
라벨은 시험에서 직접 만든다(이웃 영역의 라벨을 복사하지 않는다). 사용: <deploy .venv>/bin/python scripts/test_check_exposure.py"""
import copy, json, pathlib, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from openit_deploy.components import exposure_check as C

CADDY = (HERE.parent / "config/Caddyfile").read_text(encoding="utf-8")
HOSTS = json.loads((HERE.parent / "config/exposure-hosts.json").read_text())
ROLES = "staff operator release-approver reviewer author clinical-reviewer".split()
TO = {"dial": 1000, "response_header": 180000}   # config/Caddyfile 의 release-gate 사람용 경로(ADR 0051, D125)
GATE = {"service": "release-gate", "routes": [
    {"paths": ["/v1/submissions", "/v1/submissions/*"], "methods": ["GET"], "auth": {"kind": "account", "roles": ["release-approver"]}, "timeouts_ms": TO, "upstream_token": "gate-read-release-approver", "user_header": "set"},
    {"paths": ["/v1/approvals"], "methods": ["POST"], "auth": {"kind": "account", "roles": ["release-approver"]}, "timeouts_ms": TO, "upstream_token": "gate-write-release-approver", "user_header": "set"},
    {"paths": ["/v1/active-pointer", "/v1/releases"], "methods": ["GET"], "auth": {"kind": "account", "roles": ["operator"]}, "timeouts_ms": TO, "upstream_token": "gate-read-operator", "user_header": "set"},
    {"paths": ["/v1/activate", "/v1/rollback"], "methods": ["POST"], "auth": {"kind": "account", "roles": ["operator"]}, "timeouts_ms": TO, "upstream_token": "gate-write-operator", "user_header": "set"},
    {"paths": ["/v1/submissions"], "methods": ["POST"], "auth": {"kind": "denied"}},
    {"paths": ["/v1/releases/*", "/v1/decisions"], "auth": {"kind": "denied"}}]}
OCI = {"exposed_ports": ["8080/tcp"], "user": "10001"}


def run(label=GATE, caddy=CADDY, oci=OCI):
    h = C.collect(caddy, ROLES)
    return C.compare("release-gate", label, h, HOSTS, oci)


class T(unittest.TestCase):
    def test_matching_label_passes(self):
        self.assertEqual(run(), [])

    def test_validates_against_contract(self):
        from boundary_contracts import validator
        self.assertEqual(list(validator("Exposure").iter_errors(GATE)), [])

    def test_role_mismatch(self):
        l = copy.deepcopy(GATE); l["routes"][0]["auth"]["roles"] = ["operator"]
        self.assertTrue(any("역할" in d for d in run(l)))

    def test_upstream_token_mismatch(self):
        l = copy.deepcopy(GATE); l["routes"][1]["upstream_token"] = "other"
        self.assertTrue(any("상류 토큰" in d for d in run(l)))

    def test_timeout_mismatch(self):
        l = copy.deepcopy(GATE); l["routes"][2]["timeouts_ms"]["response_header"] = 1234
        self.assertTrue(any("시간 제한" in d for d in run(l)))

    def test_denied_path_that_caddy_opens(self):
        l = copy.deepcopy(GATE); l["routes"][5]["paths"].append("/v1/active-pointer")
        self.assertTrue(any("거부(denied)인데" in d for d in run(l)))

    def test_exposed_path_missing_in_caddy(self):
        l = copy.deepcopy(GATE); l["routes"][3]["paths"].append("/v1/new-thing")
        self.assertTrue(any("/v1/new-thing" in d for d in run(l)))

    def test_caddy_exposes_more_than_label(self):
        l = copy.deepcopy(GATE); l["routes"].pop(1)
        self.assertTrue(any("라벨 선언이 이 핸들러에 닿는 경로가 없다" in d for d in run(l)))

    def test_caddy_change_is_caught(self):
        self.assertTrue(any("상류 토큰" in d for d in run(caddy=CADDY.replace("gate-write-operator", "gate-write-other"))))
        self.assertTrue(any("시간 제한" in d for d in run(caddy=CADDY.replace("(proxy_limits) {\n\tlb_try_duration 0\n\ttransport http {\n\t\ttls_trusted_ca_certs /etc/openit/pki/root_ca.crt\n\t\tdial_timeout 1s", "(proxy_limits) {\n\tlb_try_duration 0\n\ttransport http {\n\t\tdial_timeout 3s"))))

    def test_oci_user_and_port(self):
        self.assertTrue(any("root" in d for d in run(oci={"exposed_ports": ["8080/tcp"], "user": ""})))
        self.assertTrue(any("ExposedPorts" in d for d in run(oci={"exposed_ports": ["9090/tcp"], "user": "10001"})))


ROLES2 = ROLES + ["clinician", "admin"]
TOS = {"dial": 1000, "response_header": 55000}
PUSH_STAFF = {"paths": ["/v1/staff/push-config"], "methods": ["GET"], "auth": {"kind": "account", "roles": ["staff"]}, "upstream_token": "survey-api-staff", "user_header": "set", "streaming": True, "timeouts_ms": {**TOS, "read": 3600000}}
PUSH_CLIN = {"paths": ["/v1/staff/push-config"], "methods": ["GET"], "auth": {"kind": "account", "roles": ["clinician"]}, "upstream_token": "survey-result-reader", "user_header": "set", "timeouts_ms": TOS}


def run_survey(routes):
    h = C.collect(CADDY, ROLES2)
    return [d for d in C.compare("survey-service", {"service": "survey-service", "routes": routes}, h, HOSTS, OCI) if "push-config" in d]


class TwoRoleBlocks(unittest.TestCase):
    """D9a: 같은 경로·메서드에 사람 역할 블록이 둘(staff 블록, clinician 전용 블록)이면 라벨의 두 줄이 각자 자기 블록과 비교된다(예전에는 첫 블록만 읽어 clinician 줄이 어긋나 보였다)."""
    def test_staff_and_clinician_lines_both_match(self):
        self.assertEqual(run_survey([PUSH_STAFF, PUSH_CLIN]), [])

    def test_clinician_line_with_wrong_token_is_caught(self):
        bad = dict(PUSH_CLIN, upstream_token="survey-api-staff")
        self.assertTrue(any("상류 토큰" in d for d in run_survey([PUSH_STAFF, bad])))

    def test_clinician_line_with_wrong_streaming_is_caught(self):
        bad = dict(PUSH_CLIN, streaming=True)
        self.assertTrue(any("streaming" in d for d in run_survey([PUSH_STAFF, bad])))

    def test_only_the_staff_line_leaves_the_clinician_block_undeclared(self):
        self.assertTrue(any("라벨 선언이 이 핸들러에 닿는 경로가 없다" in d for d in run_survey([PUSH_STAFF])))

    def test_clinician_block_inherits_the_outer_role(self):
        hs = [h for h in C.collect(CADDY, ROLES2) if h.get("kind") == "proxy" and "/v1/staff/push-config" in h["paths"]]
        self.assertEqual(sorted(sorted(h["roles"]) for h in hs), [["clinician"]])


class MachineToken(unittest.TestCase):
    """계약 3.4.0 의 auth.kind machine-token: Authorization: Bearer 고정 비밀 매처의 입구는 라벨의 machine-token 줄과, 같은 경로의 사람 줄은 사람 블록과 각자 비교된다."""
    MACH = {"paths": ["/v1/active-pointer", "/v1/releases/*"], "methods": ["GET"], "auth": {"kind": "machine-token"}, "upstream_token": "gate-read-model-serving", "user_header": "strip", "streaming": True}

    def test_machine_line_matches_and_operator_line_still_matches(self):
        label = copy.deepcopy(GATE); label["routes"] = [r for r in label["routes"] if r["auth"]["kind"] != "denied" or r["paths"] == ["/v1/submissions"]] + [self.MACH]
        d = [x for x in run(label) if "active-pointer" in x or "/v1/releases" in x]
        self.assertEqual(d, [])

    def test_machine_line_with_wrong_token_is_caught(self):
        label = copy.deepcopy(GATE); label["routes"] = [r for r in label["routes"] if r["auth"]["kind"] != "denied" or r["paths"] == ["/v1/submissions"]] + [dict(self.MACH, upstream_token="gate-read-operator")]
        self.assertTrue(any("상류 토큰" in x and "release-gate" in x for x in run(label)))


class Authenticated(unittest.TestCase):
    """계약 3.4.0 의 auth.kind authenticated: 로그인한 계정이면 역할과 무관하게 연다. Caddyfile 의 /admin/*(인증만 보고 역할 매처 없음)과 같다."""
    ADMIN = {"paths": ["/admin/*"], "methods": ["GET"], "auth": {"kind": "authenticated"}, "user_header": "strip", "timeouts_ms": {"dial": 1000, "response_header": 10000}}

    def run_admin(self, route):
        h = C.collect(CADDY, ROLES + ["clinician", "admin"])
        return [d for d in C.compare("admin-console", {"service": "admin-console", "routes": [route]}, h, HOSTS, OCI) if "/admin/" in d]

    def test_authenticated_label_matches_the_open_admin_screen(self):
        self.assertEqual(self.run_admin(self.ADMIN), [])

    def test_role_restricted_label_is_a_diff_against_an_open_screen(self):
        d = self.run_admin(dict(self.ADMIN, auth={"kind": "account", "roles": ["operator"]}))
        self.assertTrue(any("인증 종류 라벨 account / Caddyfile authenticated" in x for x in d), d)

    def test_authenticated_label_against_a_role_block_is_a_diff(self):
        h = C.collect(CADDY, ROLES + ["clinician", "admin"])
        d = C.compare("release-gate", {"service": "release-gate", "routes": [{"paths": ["/v1/approvals"], "methods": ["POST"], "auth": {"kind": "authenticated"}, "upstream_token": "gate-write-release-approver", "user_header": "set", "timeouts_ms": TO}]}, h, HOSTS, OCI)
        self.assertTrue(any("인증 종류 라벨 authenticated / Caddyfile account" in x for x in d), d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
