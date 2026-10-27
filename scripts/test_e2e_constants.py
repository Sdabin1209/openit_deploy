#!/usr/bin/env python3
"""E2E 시간 상수(scripts/e2e_steps.py)와 config/Caddyfile 의 실제 값을 대조하는 자체 점검(점검 L10). Docker 불필요.
설정을 바꾸고 상수를 안 바꾸면(또는 반대) 여기서 실패한다. 사용: python3 scripts/test_e2e_constants.py"""
import pathlib, re, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent
STEPS = (HERE / "e2e_steps.py").read_text(encoding="utf-8")
CADDY = (HERE.parent / "config/Caddyfile").read_text(encoding="utf-8")


def const(name):
    m = re.search(rf"^{name}\s*=\s*([0-9.]+)", STEPS, re.M)
    if m: return float(m.group(1))
    m = re.search(r"^([A-Z_0-9, ]+?)\s*=\s*([0-9., ]+)\s*(#|$)", "\n".join(l for l in STEPS.splitlines() if l.startswith(("GW_HDR",))), re.M)   # 튜플 대입(GW_HDR_GATE_S, GW_HDR_OPS_S = 15.0, 10.0)
    assert m, f"e2e_steps.py 에 상수 {name} 이 없다"
    names = [x.strip() for x in m.group(1).split(",")]; vals = [float(x) for x in m.group(2).split(",")]
    return vals[names.index(name)]


def secs(v):
    return float(v[:-2]) / 1000 if v.endswith("ms") else float(v.rstrip("s"))


class T(unittest.TestCase):
    def test_patient_path_cap_is_within_kiosk_wait_and_above_server_deadline(self):
        # 환자 API(@kioskapi) reverse_proxy 의 dial + response_header
        blk = CADDY[CADDY.index("@kioskapi path"):]
        dial = secs(re.search(r"dial_timeout\s+([0-9.]+m?s)", blk).group(1)); hdr = secs(re.search(r"response_header_timeout\s+([0-9.]+m?s)", blk).group(1))
        self.assertLess(dial + hdr, const("KIOSK_WAIT_S"))
        self.assertGreater(dial + hdr, const("SURVEY_TURN_DEADLINE_S"))
        self.assertAlmostEqual(dial + hdr, 9.5, places=3, msg="ADR 0003·docs/E2E.md 의 9.5초(연결 1s + 헤더 8.5s)와 Caddyfile 이 다르다")

    def test_human_proxy_limits_match_constants(self):
        self.assertAlmostEqual(secs(re.search(r"\(proxy_limits\)[^}]*?dial_timeout\s+(\S+)", CADDY, re.S).group(1)), const("GW_DIAL_PROXY_S"))
        gate = {secs(x) for x in re.findall(r"reverse_proxy release-gate:8080 \{[^}]*?import proxy_limits (\S+)", CADDY, re.S)}
        ops = {secs(x) for x in re.findall(r"reverse_proxy ops-feedback-ingest:8080 \{[^}]*?import proxy_limits (\S+)", CADDY, re.S)}
        self.assertEqual(gate, {const("GW_HDR_GATE_S")}); self.assertEqual(ops, {const("GW_HDR_OPS_S")})

    def test_readyz_cap_matches(self):
        blk = CADDY[CADDY.index("handle /readyz"):][:600]
        dial = secs(re.search(r"dial_timeout\s+([0-9.]+m?s)", blk).group(1)); hdr = secs(re.search(r"response_header_timeout\s+([0-9.]+m?s)", blk).group(1))
        self.assertAlmostEqual(dial + hdr, const("GW_READYZ_CAP_S"))

    def test_conn_refused_bound_is_far_below_header_limit(self):
        self.assertLess(const("GW_DIAL_PROXY_S") + const("DOCKER_DNS_FAIL_S") + 1.5, const("GW_HDR_GATE_S") / 2)

    def test_release_gate_stop_grace_covers_hard_cap(self):
        """compose 의 release-gate stop_grace_period 는 그 영역이 확정한 최악 종료 시간(하드 상한 35초, release-gate docs/adr/0008-timeouts.md) 이상이어야 한다."""
        comp = (HERE.parent / "compose.yaml").read_text(encoding="utf-8")
        blk = comp[comp.index("\n  release-gate:"):]
        m = re.search(r"stop_grace_period:\s*(\d+)s", blk[:blk.index("\n  model-serving:")])
        self.assertIsNotNone(m, "release-gate 에 stop_grace_period 가 없다")
        self.assertGreaterEqual(int(m.group(1)), 35 + 5)

    def test_unused_constant_removed(self):
        self.assertNotIn("GW_PATIENT_CAP_S", STEPS)


if __name__ == "__main__":
    unittest.main()
