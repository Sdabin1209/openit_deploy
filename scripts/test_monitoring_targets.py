#!/usr/bin/env python3
"""정적 시험(DC-MON.1·R10.11): 감시 대상 파일(config/monitoring-targets)이 가리키는 서비스는 compose 에 영역 게이트웨이(<서비스>-gw)가 있고, 감시가 그 영역 pod 에 닿는 전용 망(mon-<서비스>)이 있으며 그 망에는 감시와 그 pod 밖에 없다.
변이 확인: 대상 파일에 없는 서비스를 적거나, 영역 pod 를 다른 영역의 mon 망에 붙이면 실패한다."""
import copy, re, unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
S0 = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
M0 = yaml.safe_load((ROOT / "compose.monitoring.yaml").read_text(encoding="utf-8"))["services"]
TARGETS = ROOT / "config/monitoring-targets"
MONITORS = ("prometheus", "blackbox-exporter", "json-exporter")


def target_services(text_by_file):
    out = set()
    for t in text_by_file.values():
        out |= set(re.findall(r"https://([a-z0-9-]+)[:/']", t)) | set(re.findall(r"'([a-z0-9-]+):443'", t))
    return out - {"gateway"}


def problems(S, M, files):
    errs = []
    for svc in sorted(target_services(files)):
        if f"{svc}-gw" not in S:
            errs.append(f"{svc}: 대상인데 영역 게이트웨이({svc}-gw)가 없다")
        pod = S.get(f"{svc}-net") or {}
        mon = f"mon-{svc}"
        if mon not in (pod.get("networks") or {}):
            errs.append(f"{svc}-net: 감시 전용 망 {mon} 에 붙지 않았다")
        for m in MONITORS[:1]:
            if mon not in (M[m].get("networks") or []):
                errs.append(f"{m}: {mon} 에 붙지 않았다")
        others = [n for n, sv in S.items() if n != f"{svc}-net" and mon in (sv.get("networks") or {})]
        if others:
            errs.append(f"{mon} 에 영역 pod 가 둘 이상 있다: {others}")
    return errs


class T(unittest.TestCase):
    def files(self):
        return {p.name: p.read_text(encoding="utf-8") for p in TARGETS.glob("*.yml")}

    def test_targets_match_compose(self):
        f = self.files()
        self.assertTrue(target_services(f), "대상을 하나도 못 뽑았다")
        self.assertEqual(problems(S0, M0, f), [])

    def test_mutation_unknown_target_is_caught(self):
        f = self.files(); f["metrics.yml"] += "- targets: ['nonesuch:443']\n"
        self.assertTrue(problems(S0, M0, f))

    def test_mutation_shared_monitoring_network_is_caught(self):
        S = copy.deepcopy(S0); S["question-authoring-net"]["networks"]["mon-survey-service"] = {}
        self.assertTrue(problems(S, M0, self.files()))


if __name__ == "__main__":
    unittest.main()
