#!/usr/bin/env python3
"""시간 상한 사슬 정적 시험(ADR 0047): 바깥이 안쪽보다 길다. 값은 각자의 정본에서 읽는다: gateway = config/Caddyfile 의 환자 경로(@kioskapi) 연결 + 응답 헤더, survey = config/survey.env 의 SURVEY_*_SECONDS, 키오스크 대기 = e2e_steps.py 의 KIOSK_WAIT_S(deploy 에는 키오스크 설정 파일이 없고, 값은 kiosk-frontend 영역이 정한다).
사슬(사용자 결정 2026-10-30): 키오스크 12s > gateway 10.5s > survey 턴 마감 9s > 값 추출 3s + 응답 생성 5s. 사용법: python3 scripts/test_time_chain.py"""
import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CADDY = (ROOT / "config/Caddyfile").read_text(encoding="utf-8")
STEPS = (ROOT / "scripts/e2e_steps.py").read_text(encoding="utf-8")


def secs(v):
    return float(v[:-2]) / 1000 if v.endswith("ms") else float(v.rstrip("s"))


def env(name):
    m = re.search(rf"^{name}=([0-9.]+)\s*$", (ROOT / "config/survey.env").read_text(encoding="utf-8"), re.M)
    assert m, f"config/survey.env 에 {name} 가 없다"
    return float(m.group(1))


def const(name):
    m = re.search(rf"^{name}\s*=\s*([0-9.]+)", STEPS, re.M)
    assert m, f"e2e_steps.py 에 {name} 가 없다"
    return float(m.group(1))


class Chain(unittest.TestCase):
    def values(self):
        blk = CADDY[CADDY.index("@kioskapi path"):]
        gw = secs(re.search(r"dial_timeout\s+([0-9.]+m?s)", blk).group(1)) + secs(re.search(r"response_header_timeout\s+([0-9.]+m?s)", blk).group(1))
        return {"kiosk": const("KIOSK_WAIT_S"), "gateway": gw, "turn": env("SURVEY_TURN_DEADLINE_SECONDS"), "extract": env("SURVEY_INFERENCE_EXTRACT_TIMEOUT_SECONDS"), "respond": env("SURVEY_INFERENCE_RESPOND_TIMEOUT_SECONDS")}

    def test_outer_is_longer_than_inner(self):
        v = self.values()
        self.assertGreater(v["kiosk"], v["gateway"], v)
        self.assertGreater(v["gateway"], v["turn"], v)
        self.assertGreater(v["turn"], v["extract"] + v["respond"], v)   # 한 턴이 추출과 응답을 순서대로 부르므로 합보다 길어야 마감이 먼저 오지 않는다

    def test_decided_values(self):
        v = self.values()
        self.assertEqual((v["extract"], v["respond"], v["turn"], v["gateway"], v["kiosk"]), (3.0, 5.0, 9.0, 10.5, 12.0), "사용자 결정(2026-10-30)과 다르다: 바꾸려면 ADR 0047 을 대체하는 새 ADR 이 먼저다")

    def test_e2e_derived_limits_stay_below_kiosk(self):
        self.assertLess(const("SURVEY_TURN_DEADLINE_S") + const("CLIENT_EXTRA_S"), const("KIOSK_WAIT_S") + const("CLIENT_EXTRA_S"))
        self.assertEqual(const("SURVEY_TURN_DEADLINE_S"), env("SURVEY_TURN_DEADLINE_SECONDS"), "E2E 상수와 설정이 다르다")


if __name__ == "__main__":
    unittest.main()
