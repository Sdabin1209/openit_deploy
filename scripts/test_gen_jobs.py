#!/usr/bin/env python3
"""단독 시험: 잡의 command·시간 한도는 이미지 라벨 io.openit.jobs(계약 JobsDeclaration)에서 온다(S10, RUNTIME R9.2·R9.3). compose.yaml 에 `python -m` 이 없다.
변이 확인: 잡 이름이 어긋나거나 라벨이 없으면 거부하고, compose 에 python -m 을 손으로 적으면 정적 시험이 실패한다."""
import json, re, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from boundary_contracts import validator  # noqa: E402
from openit_deploy.wiring import cli_gen_jobs as G  # noqa: E402

COMPOSE = {"services": {"job-survey-purge": {"image": "img/s"}, "job-question-authoring-purge": {"image": "img/q"}, "job-release-gate-prune": {"image": "img/g"},
                        "job-release-gate-collect": {"image": "img/g"}, "job-ops-feedback": {"image": "img/o"}, "gateway": {"image": "img/gw"}}}
DECL = {"img/s": {"jobs": [{"name": "session-purge", "argv": ["python", "-m", "survey_service", "purge"], "idempotent": True, "timeout_seconds": 120}]},
        "img/q": {"jobs": [{"name": "purge", "argv": ["qa", "purge"], "idempotent": True}]},
        "img/g": {"jobs": [{"name": "prune", "argv": ["gate", "prune"], "idempotent": True}, {"name": "collect", "argv": ["gate", "collect"], "idempotent": True, "timeout_seconds": 300}]},
        "img/o": {"jobs": [{"name": "ops-feedback-job", "argv": ["ops", "job", "--config", "/config/job.yaml"], "idempotent": True, "timeout_seconds": 1800}]}}


def labels(img): return {"io.openit.jobs": json.dumps(DECL[img])} if img in DECL else {}


def validator_of_internal():
    from jsonschema import Draft202012Validator
    return Draft202012Validator(json.loads((ROOT / "schemas/JobOverlayRequest.schema.json").read_text(encoding="utf-8")))


class T(unittest.TestCase):
    def test_command_and_timeout_come_from_the_declaration(self):
        r = G.build(COMPOSE, labels, validator)["services"]
        self.assertEqual(r["job-survey-purge"], {"command": ["python", "-m", "survey_service", "purge"], "x-openit-timeout-seconds": 120, "x-openit-period-seconds": 86400})
        self.assertEqual(r["job-release-gate-collect"]["command"], ["gate", "collect"])
        self.assertEqual(r["job-question-authoring-purge"]["x-openit-timeout-seconds"], 3600)   # R9.3 기본
        self.assertNotIn("gateway", r)

    def test_missing_label_or_name_is_refused(self):
        with self.assertRaises(SystemExit) as e:
            G.build(COMPOSE, lambda i: {}, validator)
        self.assertIn("io.openit.jobs 가 없다", str(e.exception))
        bad = json.loads(json.dumps(DECL)); bad["img/o"]["jobs"][0]["name"] = "other"
        with self.assertRaises(SystemExit) as e:
            G.build(COMPOSE, lambda i: {"io.openit.jobs": json.dumps(bad[i])} if i in bad else {}, validator)
        self.assertIn("ops-feedback-job", str(e.exception))

    def test_period_is_made_by_the_rule_longer_than_the_declared_timeout(self):   # R9.3: 상한 600 = 기본 주기 600 이면 주기가 900 이 된다(상한보다 큰 가장 작은 5분 배수)
        r = G.build(COMPOSE, labels, validator)["services"]
        c = r["job-release-gate-collect"]
        self.assertEqual((c["x-openit-timeout-seconds"], c["x-openit-period-seconds"]), (300, 600))
        d = json.loads(json.dumps(DECL)); d["img/g"]["jobs"][1]["timeout_seconds"] = 600
        r2 = G.build(COMPOSE, lambda i: {"io.openit.jobs": json.dumps(d[i])} if i in d else {}, validator)["services"]["job-release-gate-collect"]
        self.assertEqual((r2["x-openit-timeout-seconds"], r2["x-openit-period-seconds"]), (600, 900))
        self.assertGreater(r2["x-openit-period-seconds"], r2["x-openit-timeout-seconds"])
        from openit_deploy.components import job_overlay as JO
        self.assertEqual([JO.period_for(t, 0) for t in (1, 299, 300, 600, 3600)], [300, 300, 600, 900, 3900])   # 규칙: 상한보다 큰 가장 작은 300 배수
        self.assertEqual(JO.period_for(100, 86400), 86400)   # 기본 주기가 더 길면 그대로

    def test_mutation_without_the_rule_r93_check_refuses(self):
        from openit_deploy.components import job_overlay as JO
        orig = JO.period_for
        try:
            JO.period_for = lambda timeout, base: base   # 규칙을 뺀다
            d = json.loads(json.dumps(DECL)); d["img/g"]["jobs"][1]["timeout_seconds"] = 600
            with self.assertRaises(SystemExit) as e:
                G.build(COMPOSE, lambda i: {"io.openit.jobs": json.dumps(d[i])} if i in d else {}, validator)
            self.assertIn("R9.3", str(e.exception))
        finally:
            JO.period_for = orig

    def test_derived_units_carry_timeout_and_period(self):
        u = G.derived_units("job-release-gate-collect", 600, 900)
        self.assertIn("OnUnitActiveSec=900s", u["openit-release-gate-collector.timer"])
        sv = u["openit-release-gate-collector.service"]
        self.assertIn("TimeoutStartSec=600", sv); self.assertRegex(sv, r"job-metrics\.sh \S+ 900")   # JobStale 의 기준(주기의 2배 + 60초)이 같은 주기에서 나온다

    def test_timers_never_catch_up_missed_runs(self):   # R10.12: 놓친 실행을 몰아서 하지 않는다(Persistent 없음), 잡은 oneshot 이라 겹치지 않는다
        for t in (ROOT / "config/systemd").glob("*.timer"):
            self.assertNotRegex(t.read_text(encoding="utf-8"), r"(?m)^Persistent=true", t.name)
        for sv in (ROOT / "config/systemd").glob("*.service"):
            self.assertIn("Type=oneshot", sv.read_text(encoding="utf-8"), sv.name)

    def test_compose_has_no_hand_written_python_m_for_jobs(self):
        s = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        for m in re.finditer(r"^  (job-[a-z-]+):.*?(?=^  [a-z]|\Z)", s, re.M | re.S):
            self.assertNotIn('"python", "-m"', m.group(0), f"{m.group(1)}: 잡 명령을 손으로 적었다(이미지 라벨에서 와야 한다)")
        # JOB_NAMES = compose 의 job-* 서비스 + 명령을 이미지 선언에서 받는 일회성 선행 서비스(ops-feedback-migrate, CONVENTIONS 13절 3.4.17). 일회성 서비스도 손으로 쓴 명령이 없어야 한다
        self.assertEqual(sorted(re.findall(r"^  (job-[a-z-]+):", s, re.M) + ["ops-feedback-migrate"]), sorted(G.JOB_NAMES))
        m = re.search(r"^  ops-feedback-migrate:.*?(?=^  [a-z]|\Z)", s, re.M | re.S).group(0)
        self.assertNotIn('"python", "-m"', m, "ops-feedback-migrate: 명령을 손으로 적었다(이미지 라벨의 잡 선언에서 와야 한다)")

    def test_every_constant_fits_the_overlay_request_schema(self):   # 실행 없이: JOB_NAMES·TIMERS·CONFIG_SOURCES 의 값이 JobOverlayRequest 스키마를 통과한다(ops-feedback-migrate 가 pattern 에 걸린 재발 방지)
        v = validator_of_internal()
        names = sorted(set(G.JOB_NAMES) | set(G.TIMERS) | set(G.CONFIG_SOURCES))
        req = {"jobs": [{"compose_service": n, "declared": {"name": G.JOB_NAMES.get(n, "x"), "argv": ["x"]}, "base_period_seconds": 60,
                         **({"config_source": G.CONFIG_SOURCES[n]} if n in G.CONFIG_SOURCES else {})} for n in names]}
        self.assertEqual([e.message for e in v.iter_errors(req)], [])
        self.assertTrue(all(isinstance(k, str) and isinstance(x, str) and x for d in (G.TIMERS, G.CONFIG_SOURCES) for k, x in d.items()))

    def test_mutation_old_pattern_is_caught(self):
        import copy
        sch = copy.deepcopy(json.loads((ROOT / "schemas/JobOverlayRequest.schema.json").read_text(encoding="utf-8")))
        sch["properties"]["jobs"]["items"]["properties"]["compose_service"]["pattern"] = "^job-[a-z][a-z0-9-]*$"
        from jsonschema import Draft202012Validator
        req = {"jobs": [{"compose_service": "ops-feedback-migrate", "declared": {"name": "x", "argv": ["x"]}}]}
        self.assertTrue(list(Draft202012Validator(sch).iter_errors(req)))

    def test_overlay_is_per_project(self):   # 다른 프로젝트(분리 배치 시험의 작은 compose)가 남의 잡 덧씌우기에 걸려 거부당하지 않게 프로젝트마다 따로 둔다(묶음에서만 나던 실패의 원인)
        import subprocess
        out = subprocess.run(["bash", "-c", 'DEPLOY_NO_DOCKER=1; source scripts/lib.sh; jobs_overlay_path a; jobs_overlay_path b'], cwd=ROOT, capture_output=True, text=True).stdout.split()
        self.assertEqual(len(out), 2); self.assertNotEqual(out[0], out[1])
        self.assertNotIn("compose.jobs.yaml", (ROOT / "scripts/lib.sh").read_text(encoding="utf-8").replace("compose.jobs.${1", ""))

    def test_run_job_enforces_the_timeout(self):
        s = (ROOT / "scripts/run-job.sh").read_text(encoding="utf-8")
        self.assertIn('timeout --signal=TERM', s); self.assertIn("x-openit-timeout-seconds", s)


if __name__ == "__main__":
    unittest.main()
