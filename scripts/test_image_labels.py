#!/usr/bin/env python3
"""규칙 D63. check_image_labels.py 자체 시험(Docker 불필요): 이미지 라벨이 계약 ImageLabels 스키마를 따르는지 가리는 규칙.
기대값의 출처: 헤드 결정(wo8) - 필수 라벨은 ImageLabels가 정한 service, revision, contracts.boundary, contracts.survey-schema, inputs,
model-runtime·langgraph 는 해당 서비스에만(선택; turn-engine 라벨은 계약 3.0 에서 없어졌다), 값 없음 표기는 `n/a` 하나, revision `unknown` 거부. 값 예시는 이 PC 의 실제 이미지 라벨(deploy-build/*)에서 왔다.
사용: python3 scripts/test_image_labels.py   (jsonschema 가 있는 파이썬: deploy .venv)"""
import json, os, pathlib, subprocess, sys, tempfile, unittest
from image_label_test_data import inputs_label

HERE = pathlib.Path(__file__).resolve().parent
CHECK = HERE / "check_image_labels.py"
B = {"io.openit.inputs": inputs_label("svc"), "io.openit.service": "svc", "io.openit.revision": "85b3552", "io.openit.contracts.boundary": "v3.0.0", "io.openit.contracts.survey-schema": "3"}


def run(labels, *extra):
    p = subprocess.run([sys.executable, str(CHECK), *extra], input=json.dumps(labels), capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def with_(**kv):
    d = dict(B)
    for k, v in kv.items(): d["io.openit." + k.replace("_", "-")] = v
    return d


def without(*keys):
    return {k: v for k, v in B.items() if k not in {"io.openit." + x for x in keys}}


class Accept(unittest.TestCase):
    def ok(self, labels):
        rc, out = run(labels); self.assertEqual(rc, 0, out)

    def test_minimal_required_labels(self): self.ok(B)
    def test_survey_service_real(self): self.ok({**B, "io.openit.service": "survey-service", "io.openit.inputs": inputs_label("survey-service"), "io.openit.model-runtime": "v0.7.6", "io.openit.langgraph": "1.2.15"})
    def test_admin_console_real_na(self): self.ok({**B, "io.openit.contracts.survey-schema": "n/a", "io.openit.model-runtime": "n/a"})
    def test_kiosk_frontend_real_without_engine_labels(self): self.ok({**B, "io.openit.app-version": "0.1.0"})
    def test_other_prefix_ignored(self): self.ok({**B, "org.opencontainers.image.revision": "whatever", "maintainer": "x"})
    def test_gpu_variant(self): self.ok({**B, "io.openit.variant": "gpu"})


class Reject(unittest.TestCase):
    def bad(self, labels, needle=None):
        rc, out = run(labels); self.assertEqual(rc, 1, out)
        if needle: self.assertIn(needle, out)

    def test_inputs_identity_must_match_image(self):
        self.bad({**B, "io.openit.inputs": inputs_label("another-service")}, "서비스 식별")

    def test_job_without_input_profile(self):
        self.bad({**B, "io.openit.jobs": json.dumps({"jobs": [{"name":"run","argv":["/bin/run"],"idempotent":True}]})}, "잡 목록")

    def test_input_profile_without_job(self):
        inputs = json.loads(inputs_label("svc"))
        inputs["jobs"]["ghost"] = inputs["roles"]["default"]
        self.bad({**B, "io.openit.inputs":json.dumps(inputs)}, "잡 목록")

    def test_database_invalid_document(self): self.bad({**B, "io.openit.database": "{}"}, "io.openit.database")
    def test_database_not_json(self): self.bad({**B, "io.openit.database": "not json"}, "io.openit.database")
    def test_inputs_not_json(self): self.bad({**B, "io.openit.inputs": "not json"}, "io.openit.inputs")
    def test_inputs_invalid_document(self): self.bad({**B, "io.openit.inputs": "{}"}, "io.openit.inputs")

    def test_revision_unknown(self): self.bad(with_(revision="unknown"), "io.openit.revision")
    def test_revision_empty(self): self.bad(with_(revision=""), "io.openit.revision")
    def test_turn_engine_label_gone(self): self.bad(with_(turn_engine="n/a"), "io.openit.turn-engine")      # 3.0: 알 수 없는 io.openit.* 키라 거부된다(남아 있으면 영역이 지우지 않은 것)
    def test_model_runtime_none(self): self.bad(with_(model_runtime="none"), "io.openit.model-runtime")
    def test_unset(self): self.bad(with_(model_runtime="unset"), "io.openit.model-runtime")
    def test_model_runtime_without_v(self): self.bad(with_(model_runtime="0.7.6"), "io.openit.model-runtime")   # model-serving 의 실제 값
    def test_boundary_without_v(self): self.bad({**B, "io.openit.contracts.boundary": "2.1.1"}, "io.openit.contracts.boundary")   # release-gate 의 실제 값
    def test_survey_schema_unknown(self): self.bad({**B, "io.openit.contracts.survey-schema": "unknown"}, "io.openit.contracts.survey-schema")   # dataset-store 의 실제 값
    def test_survey_schema_tag_form(self): self.bad({**B, "io.openit.contracts.survey-schema": "survey-schema-v1.0.0"}, "io.openit.contracts.survey-schema")   # question-authoring 의 실제 값
    def test_missing_required(self):
        for k in ("service", "revision", "contracts.boundary", "contracts.survey-schema", "inputs"):
            with self.subTest(k): self.bad(without(k), k)
    def test_typo_key(self): self.bad({**B, "io.openit.revison": "abc1234"})
    def test_empty_langgraph(self): self.bad(with_(langgraph=""), "langgraph")
    def test_bad_jobs_content(self): self.bad({**B, "io.openit.jobs": json.dumps({"jobs": [{"name": "x", "argv": ["a"], "idempotent": False}]})}, "io.openit.jobs")
    def test_jobs_not_json(self): self.bad({**B, "io.openit.jobs": "not json"}, "io.openit.jobs")


class Interface(unittest.TestCase):
    def test_missing_content_schema_is_an_environment_error(self):
        import shutil
        import boundary_contracts
        source = pathlib.Path(boundary_contracts.__file__).parent / "schemas"
        with tempfile.TemporaryDirectory() as directory:
            for path in source.glob("*.schema.json"):
                if path.name != "ContainerInputs.schema.json":
                    shutil.copyfile(path, pathlib.Path(directory) / path.name)
            rc, output = run(B, "--schema-dir", directory)
            self.assertEqual(rc, 2, output)
            self.assertIn("ContainerInputs", output)

    def test_invalid_label_values_are_not_written_to_diagnostics(self):
        marker = "SENSITIVE_SENTINEL_DO_NOT_LOG"
        inputs = json.loads(inputs_label("svc"))
        inputs["roles"]["default"]["process"]["uid"] = marker
        for labels in ({**B, "io.openit.revision": marker}, {**B, "io.openit.inputs": json.dumps(inputs)}):
            with self.subTest(keys=list(labels)):
                rc, output = run(labels)
                self.assertEqual(rc, 1)
                self.assertNotIn(marker, output)

    def test_every_json_content_label_is_covered_by_the_component(self):
        sys.path.insert(0, str(HERE.parent))
        from boundary_contracts import load_schema
        from openit_deploy.components import image_label_check
        declared = {key: value["contentSchema"]["$ref"].removesuffix(".schema.json")
                    for key, value in load_schema("ImageLabels")["properties"].items()
                    if value.get("contentMediaType") == "application/json" and "contentSchema" in value}
        self.assertEqual(dict(image_label_check.INNER), declared)

    def test_missing_inner_validator_is_not_a_pass(self):
        sys.path.insert(0, str(HERE.parent))
        from openit_deploy.components import image_label_check
        result = image_label_check.run({"name": "test", "labels": B}, validators={"ImageLabels": lambda value: []})
        self.assertFalse(result["ok"])
        self.assertIn("ContainerInputs 검증기가 없다", result["errors"][0])

    def test_null_labels_is_missing_required(self):   # docker inspect 가 라벨 없는 이미지에서 null 을 낸다
        p = subprocess.run([sys.executable, str(CHECK)], input="null", capture_output=True, text=True); self.assertEqual(p.returncode, 1, p.stdout + p.stderr)

    def test_schema_missing_is_environment_error_not_pass(self):
        rc, out = run(B, "--schema-dir", "/nonexistent-dir"); self.assertEqual(rc, 2, out)

    def test_reports_schema_source(self):
        rc, out = run(B); self.assertEqual(rc, 0); self.assertRegex(out, "스키마 출처")

    def test_names_all_violations_without_values_of_secrets(self):
        rc, out = run({**with_(revision="unknown", model_runtime="none")}); self.assertEqual(rc, 1)
        self.assertIn("io.openit.revision", out); self.assertIn("io.openit.model-runtime", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
