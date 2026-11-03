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
        "img/g": {"jobs": [{"name": "prune", "argv": ["gate", "prune"], "idempotent": True}, {"name": "collect", "argv": ["gate", "collect"], "idempotent": True}]},
        "img/o": {"jobs": [{"name": "ops-feedback", "argv": ["ops", "job", "--config", "/config/job.yaml"], "idempotent": True}]}}


def labels(img): return {"io.openit.jobs": json.dumps(DECL[img])} if img in DECL else {}


class T(unittest.TestCase):
    def test_command_and_timeout_come_from_the_declaration(self):
        r = G.build(COMPOSE, labels, validator)["services"]
        self.assertEqual(r["job-survey-purge"], {"command": ["python", "-m", "survey_service", "purge"], "x-openit-timeout-seconds": 120})
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
        self.assertIn("ops-feedback", str(e.exception))

    def test_compose_has_no_hand_written_python_m_for_jobs(self):
        s = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        for m in re.finditer(r"^  (job-[a-z-]+):.*?(?=^  [a-z]|\Z)", s, re.M | re.S):
            self.assertNotIn('"python", "-m"', m.group(0), f"{m.group(1)}: 잡 명령을 손으로 적었다(이미지 라벨에서 와야 한다)")
        self.assertEqual(sorted(re.findall(r"^  (job-[a-z-]+):", s, re.M)), sorted(G.JOB_NAMES))

    def test_run_job_enforces_the_timeout(self):
        s = (ROOT / "scripts/run-job.sh").read_text(encoding="utf-8")
        self.assertIn('timeout --signal=TERM', s); self.assertIn("x-openit-timeout-seconds", s)


if __name__ == "__main__":
    unittest.main()
