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


# 시험 이미지의 디렉터리 소유·모드(진입점이 이미지에서 읽는 값의 대역): /tmp 는 보통 root 1777, /data 는 이미지가 0755 로 둔다(release-gate 실측 2026-11-08: 10001:0 0755, tmpfs 를 올리면 0:0 0755)
IMAGE_DIRS = {"/tmp": {"mode": "1777", "uid": 0, "gid": 0}, "/data": {"mode": "0755", "uid": 10001, "gid": 0}}


def check(body, decl=DECL, image_dirs=IMAGE_DIRS):
    f = W.facts("survey-service", body, "survey-service", decl, "1000")
    for w in f["writable"]:
        if w["kind"] == "tmpfs" and "mode" not in w and w["target"] in image_dirs: w["image_dir"] = image_dirs[w["target"]]
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

    def test_tmpfs_without_mode_is_judged_by_the_image_directory(self):
        """mode 없는 tmpfs 는 이미지의 그 경로 소유·모드를 받는다(Docker). 2026-11-08 release-gate 잡: 이미지 /data root 0755 위 tmpfs 에 10001 이 못 썼다(PermissionError).
        이미지 경로가 root 0755 면 비root 쓰는 사용자는 기동 전에 I8, 경로가 없으면(null) 재시작 때 0:0 0755 라 비root 는 I8, 확인 못 하면 검증 불가로 I8."""
        decl = copy.deepcopy(DECL); r = decl["roles"]["default"]
        r["writable"] = [{"path": "/data", "persist": False, "written_by": {"uid": 10001, "gid": 999}}, r["writable"][1]]
        b = copy.deepcopy(BODY); b["volumes"] = [b["volumes"][0]]; b["tmpfs"] = ["/tmp", "/data"]
        v = check(b, decl)["violations"]
        self.assertEqual([x["rule"] for x in v], ["I8"], v); self.assertIn("/data", v[0]["detail"])   # 이미지 /data root 0755
        v = check(b, decl, {**IMAGE_DIRS, "/data": None})["violations"]                              # 이미지에 경로 없음: 첫 기동만 1777, 재시작하면 Docker 가 만든 마운트 지점(0:0 0755)
        self.assertEqual([x["rule"] for x in v], ["I8"], v); self.assertIn("755", v[0]["detail"])   # 2026-11-08 E2E 단계 9: 복구 뒤 재시작한 identity 가 /opt/keycloak/data/import 에 못 썼다
        self.assertEqual(check(b, {**decl, "roles": {"default": {**r, "writable": [{**r["writable"][0], "written_by": {"uid": 0, "gid": 0}}, r["writable"][1]]}}}, {**IMAGE_DIRS, "/data": None})["violations"], [])   # root 가 쓰면 0755 로 쓸 수 있다
        self.assertIn("I8", {x["rule"] for x in check(b, decl, {**IMAGE_DIRS, "/data": {"mode": "0755", "uid": 10001, "gid": 0}})["violations"]})   # 이미지가 그 사용자 소유여도 tmpfs 뿌리는 root(실측: release-gate /data 10001:0 0755 -> tmpfs 0:0 0755)
        self.assertEqual(check(b, decl, {**IMAGE_DIRS, "/data": {"mode": "1777", "uid": 0, "gid": 0}})["violations"], [])   # 이미지 디렉터리가 1777 이면 쓸 수 있다
        v = check(b, decl, {"/tmp": IMAGE_DIRS["/tmp"]})["violations"]                               # /data 를 확인하지 못했다
        self.assertEqual([x["rule"] for x in v], ["I8"]); self.assertIn("검증 불가", v[0]["detail"])
        b["tmpfs"] = ["/tmp", "/data:uid=10001,gid=999,mode=0700"]                                     # 명시 mode·uid 가 이긴다
        self.assertEqual(check(b, decl)["violations"], [])
        b["tmpfs"] = ["/tmp", "/data:mode=0755"]                                                       # 명시 mode, uid 기본 root
        self.assertIn("I8", {x["rule"] for x in check(b, decl)["violations"]})

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
        for w in f["writable"]:
            if w["kind"] == "tmpfs": w["image_dir"] = IMAGE_DIRS[w["target"]]   # 진입점이 이미지에서 읽는 값의 대역
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
                self.assertEqual(W.main(["--compose-json", str(config), "--secrets-gid", "1000"], labels_of=lambda _: labels, image_dir_of=lambda r, p: IMAGE_DIRS.get(p, W._UNVERIFIED)), 0)
                body["command"] = ["/undeclared-job"]
                config.write_text(json.dumps({"services": {"job-survey-backup": body}}))
                self.assertEqual(W.main(["--compose-json", str(config), "--secrets-gid", "1000"], labels_of=lambda _: labels, image_dir_of=lambda r, p: IMAGE_DIRS.get(p, W._UNVERIFIED)), 1)

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
            with contextlib.redirect_stdout(out):   # mode 없는 tmpfs /tmp 의 이미지 경로를 모르면 검증 불가(I8)로 실패한다: 쓸 수 있다고 가정하지 않는다
                self.assertEqual(W.main(["--compose-json", str(cfg), "--declarations-dir", str(t / "d"), "--secrets-gid", "1000"]), 1)
            (t / "dirs.json").write_text(json.dumps({"survey-service": IMAGE_DIRS}))
            with contextlib.redirect_stdout(out):
                self.assertEqual(W.main(["--compose-json", str(cfg), "--declarations-dir", str(t / "d"), "--image-dirs", str(t / "dirs.json"), "--secrets-gid", "1000"]), 0)
            bad = copy.deepcopy(DECL); bad["roles"]["default"]["process"]["uid"] = "app"
            (t / "d" / "survey-service.json").write_text(json.dumps(bad))
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(W.main(["--compose-json", str(cfg), "--declarations-dir", str(t / "d"), "--secrets-gid", "1000"]), 2)   # 계약 위반 선언


if __name__ == "__main__":
    unittest.main()
