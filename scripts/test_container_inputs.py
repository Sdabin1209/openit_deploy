#!/usr/bin/env python3
"""단독 시험: compose 주입과 이미지 주입 선언(계약 ContainerInputs 3.5.0)의 대조(컴포넌트 container_inputs_check, 진입점 check_container_inputs).
규칙 I1~I10 마다 맞는 경우는 통과하고 하나씩 어긋나게 하면 그 규칙으로 잡힌다(변이). 선언은 계약 예시에서 시작한다(계약 validator 통과)."""
import copy
import io
import json
import contextlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from openit_deploy.components import container_inputs_check as C  # noqa: E402
from openit_deploy.wiring import cli_check_container_inputs as W  # noqa: E402
from openit_deploy.wiring.call import call  # noqa: E402

DECL = {"schema_version": 1, "image": "survey-service", "read_only_root": True, "exec_absolute_argv": True, "role_env": None, "jobs": {},
        "roles": {"default": {"env_schema": "SurveyServiceEnv", "process": {"uid": 10001, "gid": 999}, "capabilities": [], "sysctls": {},
                              "files": [{"path_env": "SURVEY_DATABASE_URL_FILE", "path": "/run/secrets/db-survey-dsn", "directory": False, "kind": "secret", "schema": None, "required": True, "opened_by": "start-process"},
                                        {"path_env": "SSL_CERT_FILE", "path": "/etc/openit/pki/root_ca.crt", "directory": False, "kind": "ca-bundle", "schema": None, "required": True, "opened_by": "start-process"},
                                        {"path_env": "SURVEY_RISK_RULES_FILE", "path": "/config/risk-rules.json", "directory": False, "kind": "config", "schema": "SurveyRiskRulesFile", "required": False, "opened_by": "start-process"}],
                              "writable": [{"path": "/data", "persist": True, "written_by": {"uid": 10001, "gid": 999}}, {"path": "/tmp", "persist": False, "written_by": {"uid": 10001, "gid": 999}}]}}}
BODY = {"image": "r/openit/survey-service@sha256:aa", "read_only": True, "cap_drop": ["ALL"], "group_add": ["1000"],
        "environment": {"SURVEY_RELEASE_READER": "http", "SURVEY_RELEASE_READER_URL": "https://release-gate", "SURVEY_TRACE_INGEST": "http", "SURVEY_TRACE_INGEST_URL": "https://ops-feedback", "SURVEY_INFERENCE_URL": "https://model-serving", "SURVEY_DATABASE_URL_FILE": "/run/secrets/db-survey-dsn", "SSL_CERT_FILE": "/etc/openit/pki/root_ca.crt"},
        "secrets": [{"source": "db-survey-dsn", "target": "/run/secrets/db-survey-dsn"}],
        "volumes": [{"type": "volume", "source": "pki-root", "target": "/etc/openit/pki", "read_only": True}, {"type": "volume", "source": "survey-data", "target": "/data"}],
        "tmpfs": ["/tmp"]}


def check(body, decl=DECL):
    f = W.facts("survey-service", body, "survey-service", decl, "1000")
    return call(C, "ContainerInputsCheckRequest", "ContainerInputsCheckResult", {"services": [f], "declarations": {"survey-service": decl}})


class T(unittest.TestCase):
    def test_declaration_is_a_valid_contract_document(self):
        from boundary_contracts import validator
        self.assertEqual([e.message for e in validator("ContainerInputs").iter_errors(DECL)], [])

    def test_matching_injection_passes(self):
        r = check(BODY)
        self.assertEqual(r["violations"], []); self.assertEqual(r["status"], "OK"); self.assertGreater(r["checked"], 10)

    def test_tmpfs_permission_bits_apply_even_when_writer_is_start_process(self):
        b = copy.deepcopy(BODY)
        b["tmpfs"] = ["/tmp:uid=0,gid=0,mode=0700"]
        self.assertIn("I8", {v["rule"] for v in check(b)["violations"]})
        b["tmpfs"] = ["/tmp:uid=10001,gid=999,mode=0700"]
        self.assertEqual(check(b)["violations"], [])
        b["tmpfs"] = ["/tmp:mode=1777"]
        self.assertEqual(check(b)["violations"], [])

    def test_tmpfs_root_owned_without_write_bits_for_nonroot_writer_is_rejected(self):
        """비root(10001:999) 쓰는 사용자 + root 소유 tmpfs 에 쓰기 비트가 없으면 기동 전에 I8(2026-11-08 release-gate 잡 /data 검토).
        mode 가 없으면 Docker 기본(0:0, 1777)으로 판정한다: 측정상 쓸 수 있어 통과가 맞다(같은 판정 경로를 거친다)."""
        b = copy.deepcopy(BODY)
        for t in ("/tmp:mode=0755", "/tmp:uid=0,gid=0,mode=0755", "/tmp:uid=0,gid=999,mode=0750"):
            b["tmpfs"] = [t]
            self.assertIn("I8", {v["rule"] for v in check(b)["violations"]}, t)
        b["tmpfs"] = ["/tmp:uid=0,gid=999,mode=0770"]   # 그룹이 쓰는 사용자의 gid 이고 그룹 rwx
        self.assertEqual(check(b)["violations"], [])
        b["tmpfs"] = []; b["volumes"] = b["volumes"] + [{"type": "tmpfs", "target": "/tmp", "tmpfs": {"mode": 0o755}}]   # 긴 형식 tmpfs 도 같다
        self.assertIn("I8", {v["rule"] for v in check(b)["violations"]})
        b["volumes"][-1]["tmpfs"] = {}   # 긴 형식, mode 없음 = Docker 기본 1777
        self.assertEqual(check(b)["violations"], [])
        b["volumes"].pop(); b["tmpfs"] = ["/tmp"]   # 짧은 형식, mode 없음 = Docker 기본 1777
        self.assertEqual(check(b)["violations"], [])

    def test_role_default_comes_from_the_declared_env_schema(self):
        from unittest.mock import patch
        declaration = copy.deepcopy(DECL)
        declaration["role_env"] = "ROLE"
        declaration["roles"] = {"serve": declaration["roles"]["default"]}
        with patch("boundary_contracts.load_schema", return_value={"properties": {"ROLE": {"default": "serve"}}}):
            facts = W.facts("example", BODY, "survey-service", declaration, "1000")
        self.assertEqual(facts["set"], "role:serve")

    def test_a_file_bind_cannot_supply_required_children(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "one-file"
            source.write_text("certificate")
            b = copy.deepcopy(BODY)
            b["volumes"][0] = {"type": "bind", "source": str(source), "target": "/etc/openit/pki", "read_only": True}
            self.assertIn("I6", {v["rule"] for v in check(b)["violations"]})

    def test_job_argv_must_equal_the_image_declaration(self):
        d = copy.deepcopy(DECL)
        d["jobs"]["backup"] = d["roles"]["default"]
        b = copy.deepcopy(BODY)
        b["command"] = ["/does-not-exist"]
        f = W.facts("job-survey-backup", b, "survey-service", d, "1000", ["/declared-job", "backup"])
        result = call(C, "ContainerInputsCheckRequest", "ContainerInputsCheckResult", {"services": [f], "declarations": {"survey-service": d}})
        self.assertIn("I11", {v["rule"] for v in result["violations"]})
        f["argv"] = f["expected_argv"]
        result = call(C, "ContainerInputsCheckRequest", "ContainerInputsCheckResult", {"services": [f], "declarations": {"survey-service": d}})
        self.assertEqual(result["violations"], [])

    def test_typed_file_is_read_from_actual_override_and_requires_valid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "custom.json"
            source.write_text('{"override": true}')
            body = {"environment": {"SURVEY_RISK_RULES_FILE": "/custom/rules.json"},
                    "volumes": [{"type": "bind", "source": str(source), "target": "/custom/rules.json", "read_only": True}]}
            inputs = {"files": [f for f in DECL["roles"]["default"]["files"] if f["schema"]]}
            self.assertEqual(W.typed_role_file_documents(body, inputs, {}), [("SurveyRiskRulesFile", {"override": True})])
            source.write_text('invalid JSON SENSITIVE_SENTINEL')
            with self.assertRaisesRegex(ValueError, "invalid JSON") as error:
                W.typed_role_file_documents(body, inputs, {})
            self.assertNotIn("SENSITIVE_SENTINEL", str(error.exception))

    def test_job_config_and_argv_are_composed_from_the_same_image_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "job.json"
            source.write_text((ROOT / "config/release-gate-job.json").read_text())
            declaration = copy.deepcopy(DECL)
            declaration["jobs"]["backup"] = declaration["roles"]["default"]
            job = {"name": "backup", "argv": ["/declared-job", "backup"], "idempotent": True,
                   "config": {"container_path": "/job/input.json", "schema": "GateJobConfig"}}
            labels = {"io.openit.service": "survey-service", "io.openit.contracts.boundary": "v3.6.0",
                      "io.openit.inputs": json.dumps(declaration), "io.openit.jobs": json.dumps({"jobs": [job]})}
            body = copy.deepcopy(BODY)
            body["command"] = job["argv"]
            body["volumes"].append({"type": "bind", "source": str(source), "target": "/job/input.json", "read_only": True})
            config = root / "compose.json"
            config.write_text(json.dumps({"services": {"job-survey-backup": body}}))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(W.main(["--compose-json", str(config), "--secrets-gid", "1000"], labels_of=lambda _: labels), 0)
                body["command"] = ["/undeclared-job"]
                config.write_text(json.dumps({"services": {"job-survey-backup": body}}))
                self.assertEqual(W.main(["--compose-json", str(config), "--secrets-gid", "1000"], labels_of=lambda _: labels), 1)

    def test_each_rule_catches_its_mutation(self):
        cases = [
            ("I1", lambda b, d: b.update(read_only=False)),
            ("I2", lambda b, d: b.update(cap_drop=[])),
            ("I2", lambda b, d: b.update(cap_add=["CHOWN"])),
            ("I3", lambda b, d: b.update(sysctls={"net.ipv4.ip_unprivileged_port_start": 0})),
            ("I4", lambda b, d: b.update(user="0")),
            ("I4", lambda b, d: b.update(entrypoint=["sh"])),
            ("I4", lambda b, d: b.update(entrypoint=[])),
            ("I4", lambda b, d: b.update(command=["/does-not-exist"])),
            ("I5", lambda b, d: d.update(role_env="X_ROLE") or b["environment"].update(X_ROLE="other")),
            ("I6", lambda b, d: b.update(secrets=[])),                                                    # 선언한 비밀이 없다
            ("I6", lambda b, d: b["environment"].update(SSL_CERT_FILE="/etc/other/ca.crt")),             # 경로 변수가 주입 밖을 가리킨다
            ("I7", lambda b, d: b["secrets"].append({"source": "unused", "target": "/run/secrets/unused"})),   # 읽지 않는 비밀을 넣는다
            ("I8", lambda b, d: b.update(tmpfs=[])),                                                     # 선언한 /tmp 가 없다
            ("I8", lambda b, d: b.update(volumes=[b["volumes"][0]], tmpfs=["/tmp", "/data"])),           # 유지 경로를 tmpfs 로
            ("I9", lambda b, d: b["tmpfs"].append("/var/cache")),                                       # 선언 밖 쓰기 마운트
            ("I10", lambda b, d: b.update(group_add=[])),                                                # 비밀을 주는데 그룹이 없다
        ]
        for rule, mutate in cases:
            b, d = copy.deepcopy(BODY), copy.deepcopy(DECL)
            mutate(b, d)
            got = {v["rule"] for v in check(b, d)["violations"]}
            self.assertIn(rule, got, f"{rule} 변이가 잡히지 않았다: {got}")

    def test_optional_file_may_be_absent_but_not_undeclared(self):
        b = copy.deepcopy(BODY)
        self.assertEqual(check(b)["violations"], [])                     # 선택 파일(SURVEY_RISK_RULES_FILE)이 없어도 된다
        b["environment"]["SURVEY_RISK_RULES_FILE"] = "/config/risk-rules.json"
        b["volumes"].append({"type": "bind", "source": "/h/r.json", "target": "/config/risk-rules.json", "read_only": True})
        self.assertEqual(check(b)["violations"], [])                     # 주면 선언과 같아야 한다

    def test_writable_mount_under_declared_persistent_path_must_be_volume(self):
        b = copy.deepcopy(BODY); b["volumes"].append({"type": "volume", "source": "cache", "target": "/data/cache"})
        self.assertEqual(check(b)["violations"], [])
        b = copy.deepcopy(BODY); b["tmpfs"].append("/data/cache")
        self.assertIn("I9", {v["rule"] for v in check(b)["violations"]})

    def test_entry_reads_declarations_dir_and_fails_on_missing_or_invalid(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t); cfg = t / "c.json"; cfg.write_text(json.dumps({"services": {"survey-service": BODY, "pause": {"image": "k8s/pause@x"}}}))
            (t / "d").mkdir()
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(W.main(["--compose-json", str(cfg), "--declarations-dir", str(t / "d"), "--secrets-gid", "1000"]), 2)   # 선언이 없다
            (t / "d" / "survey-service.json").write_text(json.dumps(DECL))
            with contextlib.redirect_stdout(out):
                self.assertEqual(W.main(["--compose-json", str(cfg), "--declarations-dir", str(t / "d"), "--secrets-gid", "1000"]), 0)
            bad = copy.deepcopy(DECL); bad["roles"]["default"]["process"]["uid"] = "app"
            (t / "d" / "survey-service.json").write_text(json.dumps(bad))
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(W.main(["--compose-json", str(cfg), "--declarations-dir", str(t / "d"), "--secrets-gid", "1000"]), 2)   # 계약 위반 선언


if __name__ == "__main__":
    unittest.main()
