#!/usr/bin/env python3
"""check_image_labels.py 자체 시험(Docker 불필요): 이미지 라벨이 계약 ImageLabels 스키마를 따르는지 가리는 규칙.
기대값의 출처: 헤드 결정(wo8) - 필수 라벨은 publish-image.sh 가 보는 4개(service, revision, contracts.boundary, contracts.survey-schema),
model-runtime·langgraph 는 해당 서비스에만(선택; turn-engine 라벨은 계약 3.0 에서 없어졌다), 값 없음 표기는 `n/a` 하나, revision `unknown` 거부. 값 예시는 이 PC 의 실제 이미지 라벨(deploy-build/*)에서 왔다.
사용: python3 scripts/test_image_labels.py   (jsonschema 가 있는 파이썬: deploy .venv)"""
import json, os, pathlib, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
CHECK = HERE / "check_image_labels.py"
B = {"io.openit.service": "svc", "io.openit.revision": "85b3552", "io.openit.contracts.boundary": "v3.0.0", "io.openit.contracts.survey-schema": "1"}


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

    def test_minimal_four_required(self): self.ok(B)
    def test_survey_service_real(self): self.ok({**B, "io.openit.service": "survey-service", "io.openit.model-runtime": "v0.7.6", "io.openit.langgraph": "1.2.15"})
    def test_admin_console_real_na(self): self.ok({**B, "io.openit.contracts.survey-schema": "n/a", "io.openit.model-runtime": "n/a"})
    def test_kiosk_frontend_real_without_engine_labels(self): self.ok({**B, "io.openit.app-version": "0.1.0"})
    def test_other_prefix_ignored(self): self.ok({**B, "org.opencontainers.image.revision": "whatever", "maintainer": "x"})
    def test_gpu_variant(self): self.ok({**B, "io.openit.variant": "gpu"})


class Reject(unittest.TestCase):
    def bad(self, labels, needle=None):
        rc, out = run(labels); self.assertEqual(rc, 1, out)
        if needle: self.assertIn(needle, out)

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
        for k in ("service", "revision", "contracts.boundary", "contracts.survey-schema"):
            with self.subTest(k): self.bad(without(k), k)
    def test_typo_key(self): self.bad({**B, "io.openit.revison": "abc1234"})
    def test_empty_langgraph(self): self.bad(with_(langgraph=""), "langgraph")
    def test_bad_jobs_content(self): self.bad({**B, "io.openit.jobs": json.dumps({"jobs": [{"name": "x", "argv": ["a"], "idempotent": False}]})}, "io.openit.jobs")
    def test_jobs_not_json(self): self.bad({**B, "io.openit.jobs": "not json"}, "io.openit.jobs")


class Interface(unittest.TestCase):
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
