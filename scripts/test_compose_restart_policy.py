#!/usr/bin/env python3
"""compose.yaml 의 재시작 정책(우리가 정한 것)을 정적으로 본다(U17 '서비스 컨테이너 재시작'): 상시 서비스는 모두 `restart: unless-stopped`, 주기 잡 job-* 는 restart 가 없다(한 번 돌고 끝나는 잡이 다시 뜨면 안 된다).
재시작 자체는 Docker 의 동작이라 시험하지 않는다. 서비스 목록은 compose.yaml 에서 읽고 개수는 고정하지 않는다(R4.1: 구성이 바뀌어도 규칙이 같이 적용된다). 일회성 서비스는 이름이 아니라 "다른 서비스가 service_completed_successfully 로 기다리는 것"으로 정한다. 사용: <deploy .venv>/bin/python scripts/test_compose_restart_policy.py"""
import pathlib, unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVICES = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
JOBS = {n: s for n, s in SERVICES.items() if n.startswith("job-")}
def _awaited_once():
    out = set()
    for s in SERVICES.values():
        for d, c in (s.get("depends_on") or {}).items() if isinstance(s.get("depends_on"), dict) else []:
            if isinstance(c, dict) and c.get("condition") == "service_completed_successfully": out.add(d)
    return out
ONESHOT = {n: s for n, s in SERVICES.items() if n in _awaited_once() and not n.startswith("job-")}   # 일회성 서비스(상시도 주기 잡도 아님): restart "no", 기본 기동에 포함. compose 의 의존 선언에서 뽑는다
ALWAYS = {n: s for n, s in SERVICES.items() if not n.startswith("job-") and n not in ONESHOT}


class RestartPolicy(unittest.TestCase):
    def test_every_service_is_exactly_one_kind(self):
        # 개수를 고정하지 않고 분할이 빠짐없이 겹침 없이 맞는지 본다
        kinds = [set(ALWAYS), set(JOBS), set(ONESHOT)]
        self.assertEqual(set().union(*kinds), set(SERVICES))
        self.assertEqual(sum(len(k) for k in kinds), len(SERVICES), "서비스가 두 종류에 걸친다")
        self.assertTrue(ALWAYS and JOBS and ONESHOT, "상시·잡·일회성 중 하나가 비었다: 분류 규칙이 깨졌다")

    def test_always_on_services_restart_unless_stopped(self):
        bad = {n: s.get("restart") for n, s in ALWAYS.items() if s.get("restart") != "unless-stopped"}
        self.assertEqual(bad, {}, "상시 서비스는 restart: unless-stopped 이다")

    def test_jobs_have_no_restart_and_are_profile_gated(self):
        self.assertEqual({n: s["restart"] for n, s in JOBS.items() if "restart" in s}, {}, "주기 잡에는 restart 가 없다")
        self.assertEqual([n for n, s in JOBS.items() if not s.get("profiles")], [], "잡은 profiles 로 기본 기동에서 빠진다(스케줄러가 run 으로 돌린다)")

    def test_oneshot_migrate_runs_once_and_is_not_profile_gated(self):
        bad = {n: (s.get("restart"), s.get("profiles")) for n, s in ONESHOT.items() if s.get("restart") != "no" or s.get("profiles")}
        self.assertEqual(bad, {}, "일회성 migrate 는 restart: no 이고 profiles 가 없다(서버가 service_completed_successfully 로 기다린다)")


if __name__ == "__main__":
    unittest.main()
