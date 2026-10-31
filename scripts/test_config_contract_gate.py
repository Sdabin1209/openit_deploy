#!/usr/bin/env python3
"""기동 전 설정·환경 계약 검증 관문(check_config_contracts.py, up.sh)의 자체 점검(R7). (1) 실제 합쳐진 compose 환경(운영 구성)이 관문을 통과한다 (2) 계약을 어기는 환경(알 수 없는 SURVEY_ 키)은 종료 1이고 출력에 값이 없다 (3) 없는 계약 스키마는 건너뛰지 않고 실패 (4) up.sh 가 compose up 보다 앞에서 관문을 부른다 (5) 가짜 백엔드 흐름 파일이 RuntimeFlowFile 을 따른다.
사용: <deploy .venv>/bin/python -W ignore scripts/test_config_contract_gate.py   (docker compose 가 필요하다: 합쳐진 환경을 읽는다)"""
import io, json, os, pathlib, re, subprocess, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from openit_deploy.wiring import cli_check_config_contracts as G


def rendered():
    env = dict(os.environ)
    for v in re.findall(r"\$\{([A-Za-z0-9_]+):\?", (ROOT / "compose.yaml").read_text(encoding="utf-8")): env.setdefault(v, "x")
    r = subprocess.run(["docker", "compose", "--project-directory", str(ROOT), "-f", str(ROOT / "compose.yaml"), "--profile", "jobs", "config", "--format", "json"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"docker compose config 를 못 돌렸다(건너뛰지 않고 실패로 센다): {r.stderr[-200:]}"
    return json.loads(r.stdout)


def run(compose):
    out, err = io.StringIO(), io.StringIO()
    so, se = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try: rc = G.main(["--compose-json", "-"], stdin=io.StringIO(json.dumps(compose)))
    finally: sys.stdout, sys.stderr = so, se
    return rc, out.getvalue(), err.getvalue()


class Gate(unittest.TestCase):
    def test_real_production_environment_passes(self):
        rc, out, err = run(rendered())
        self.assertEqual(rc, 0, err + out)
        self.assertRegex(out, r"문서 [4-9]개", "검증한 문서 수가 너무 적다: 대상이 빠졌다")

    def test_violating_environment_fails_without_printing_values(self):
        c = rendered(); c["services"]["survey-service"]["environment"]["SURVEY_NOT_A_KEY"] = "SECRETVALUE123"
        rc, out, err = run(c)
        self.assertEqual(rc, 1); self.assertIn("survey-service", err); self.assertNotIn("SECRETVALUE123", out + err)

    def test_ops_feedback_unknown_ops_variable_fails(self):
        c = rendered(); c["services"]["ops-feedback-ingest"]["environment"]["OPS_NOT_A_KEY"] = "1"
        self.assertEqual(run(c)[0], 1)

    def test_missing_schema_is_a_failure_not_a_skip(self):
        from openit_deploy.components import config_contract_check as C
        r = C.run({"documents": [{"label": "x", "schema": "NoSuchContract", "document": {}}]}, validators={})
        self.assertFalse(r["ok"]); self.assertIn("NO_SCHEMA", r["violations"][0]["message"])

    def test_up_sh_runs_the_gate_before_compose_up(self):
        t = (ROOT / "scripts/up.sh").read_text(encoding="utf-8")
        self.assertLess(t.index("check_config_contracts.py"), t.index('dc "$P" up -d'))

    def test_fake_flow_file_matches_runtime_flow_file(self):
        docs = [d for d in G.build_documents({"services": {}}) if d["schema"] == "RuntimeFlowFile"]
        self.assertEqual(len(docs), 1)
        self.assertEqual(G.make_validators({"RuntimeFlowFile"})["RuntimeFlowFile"](docs[0]["document"]), [])


if __name__ == "__main__":
    unittest.main()
