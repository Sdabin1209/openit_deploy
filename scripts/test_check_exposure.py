#!/usr/bin/env python3
"""check_exposure.py 시험: 실제 config/Caddyfile 에 대해 (1) 일치하는 라벨은 통과 (2) 흔한 어긋남(역할·상류 토큰·시간 제한·거부 경로 열림·라벨에 없는 노출·root 사용자·포트)을 잡는다.
라벨은 시험에서 직접 만든다(이웃 영역의 라벨을 복사하지 않는다). 사용: <deploy .venv>/bin/python scripts/test_check_exposure.py"""
import copy, json, pathlib, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_exposure as C

CADDY = (HERE.parent / "config/Caddyfile").read_text(encoding="utf-8")
HOSTS = json.loads((HERE.parent / "config/exposure-hosts.json").read_text())
ROLES = "staff operator release-approver reviewer author clinical-reviewer".split()
TO = {"dial": 2000, "response_header": 15000}
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
        self.assertTrue(any("시간 제한" in d for d in run(caddy=CADDY.replace("(proxy_limits) {\n\tlb_try_duration 0\n\ttransport http {\n\t\tdial_timeout 2s", "(proxy_limits) {\n\tlb_try_duration 0\n\ttransport http {\n\t\tdial_timeout 3s"))))

    def test_oci_user_and_port(self):
        self.assertTrue(any("root" in d for d in run(oci={"exposed_ports": ["8080/tcp"], "user": ""})))
        self.assertTrue(any("ExposedPorts" in d for d in run(oci={"exposed_ports": ["9090/tcp"], "user": "10001"})))


if __name__ == "__main__":
    unittest.main(verbosity=2)
