#!/usr/bin/env python3
"""정적 시험(ADR 0060): 게이트웨이가 상류로 부르는 서비스(config/Caddyfile 과 import 조각의 reverse_proxy·forward_auth 상류)는 모두 준비 확인(healthcheck)이 있고,
게이트웨이의 depends_on 이 그 서비스(와 TLS 사이드카)를 service_healthy 로 기다린다. 준비 전에 요청이 오면 503 이 되고(oauth2-proxy 가 service_started 만 기다려 인증이 503 이던 결함),
운영 재시작 직후에도 같은 실패가 난다. 사용: python3 scripts/test_gateway_depends.py"""
import pathlib, re, unittest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
S = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
FILES = [ROOT / "config/Caddyfile", *sorted((ROOT / "config").glob("*.caddy")), *sorted((ROOT / "config/gateway-tls").glob("*.caddy"))]
UP = re.compile(r"^\s*(?:reverse_proxy|forward_auth)\s+https://([a-z0-9-]+)", re.M)
UPSTREAMS = sorted({m for f in FILES for m in UP.findall("\n".join(l for l in f.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#")))})
DEPS = S["gateway"]["depends_on"]


class T(unittest.TestCase):
    def test_found_upstreams(self):
        self.assertIn("oauth2-proxy", UPSTREAMS); self.assertIn("survey-service", UPSTREAMS)   # 껍데기 시험이 아님을 본다

    def test_each_upstream_is_waited_for_healthy(self):
        for n in UPSTREAMS:
            self.assertIn(f"{n}-tls", S, f"{n}: TLS 사이드카가 없다")
            self.assertEqual(DEPS.get(f"{n}-tls", {}).get("condition"), "service_healthy", f"gateway 가 {n}-tls 를 service_healthy 로 기다리지 않는다")
            # 앱 자체의 준비는 앱의 healthcheck 이거나(없으면) 사이드카의 healthcheck 가 상류를 본다
            app_ok = DEPS.get(n, {}).get("condition") == "service_healthy" and S[n].get("healthcheck")
            side_checks_app = "127.0.0.1" in str(S[f"{n}-tls"].get("healthcheck", {}).get("test", "")) and n == "oauth2-proxy" and "/ping" in str(S[f"{n}-tls"]["healthcheck"]["test"])
            self.assertTrue(app_ok or side_checks_app, f"{n}: 앱의 healthcheck 가 없고 사이드카도 상류를 보지 않는다 / gateway 가 service_healthy 로 기다리지 않는다")

    def test_no_started_only_dependency_on_an_upstream_without_check(self):
        # service_started 로만 기다리는 상류는 사이드카의 상류 점검(/ping)이 있을 때만 허용한다
        for n, c in DEPS.items():
            if c.get("condition") == "service_started":
                self.assertIn(n, UPSTREAMS, f"{n}: 이유 없이 service_started")
                self.assertEqual(DEPS[f"{n}-tls"]["condition"], "service_healthy")


if __name__ == "__main__":
    unittest.main()
