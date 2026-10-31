#!/usr/bin/env python3
"""compose.yaml 의 재시작 정책(우리가 정한 것)을 정적으로 본다(U17 '서비스 컨테이너 재시작'): 상시 서비스 11개는 모두 `restart: unless-stopped`, 주기 잡 job-* 5개는 restart 가 없다(한 번 돌고 끝나는 잡이 다시 뜨면 안 된다).
재시작 자체는 Docker 의 동작이라 시험하지 않는다. 서비스 목록을 이 파일에 따로 적지 않고 compose.yaml 에서 읽으며, 개수(11, 5)는 기대 구성이 바뀌면 일부러 실패하게 둔 고정값이다. 사용: <deploy .venv>/bin/python scripts/test_compose_restart_policy.py"""
import pathlib, unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVICES = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
JOBS = {n: s for n, s in SERVICES.items() if n.startswith("job-")}
ALWAYS = {n: s for n, s in SERVICES.items() if not n.startswith("job-")}


class RestartPolicy(unittest.TestCase):
    def test_counts(self):
        self.assertEqual((len(ALWAYS), len(JOBS)), (11, 5), f"서비스 구성이 바뀌었다: 상시 {sorted(ALWAYS)} / 잡 {sorted(JOBS)} (정책을 확인하고 이 시험의 개수를 고친다)")

    def test_always_on_services_restart_unless_stopped(self):
        bad = {n: s.get("restart") for n, s in ALWAYS.items() if s.get("restart") != "unless-stopped"}
        self.assertEqual(bad, {}, "상시 서비스는 restart: unless-stopped 이다")

    def test_jobs_have_no_restart_and_are_profile_gated(self):
        self.assertEqual({n: s["restart"] for n, s in JOBS.items() if "restart" in s}, {}, "주기 잡에는 restart 가 없다")
        self.assertEqual([n for n, s in JOBS.items() if not s.get("profiles")], [], "잡은 profiles 로 기본 기동에서 빠진다(스케줄러가 run 으로 돌린다)")


if __name__ == "__main__":
    unittest.main()
