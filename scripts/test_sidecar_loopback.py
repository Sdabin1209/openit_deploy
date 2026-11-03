#!/usr/bin/env python3
"""정적 시험(ADR 0060, 계약 v3.4.2): TLS 사이드카를 둔 앱은 모두 loopback 에 바인드한다. 앱 포트(8080 등)가 사이드카를 거치지 않고 다른 컨테이너에 닿으면 평문이 열린다.
앱마다 바인드 설정 이름이 다르다(*_HOST 계약 변수, Keycloak http-host, oauth2-proxy http-address). 목록에 없는 새 사이드카 앱이 생기면 이 시험이 알려 준다. 사용: python3 scripts/test_sidecar_loopback.py"""
import pathlib, unittest
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
BIND = {"survey-service": "SURVEY_HOST", "question-authoring": "QA_HOST", "ops-feedback-ingest": "OPS_HOST", "release-gate": "GATE_HOST", "model-serving": "MODEL_RUNTIME_HOST",
        "model-registry": "MODEL_REGISTRY_HOST", "dataset-store": "DATASET_STORE_HOST", "keycloak": "KC_HTTP_HOST", "oauth2-proxy": "OAUTH2_PROXY_HTTP_ADDRESS", "kiosk-frontend": "KIOSK_HOST", "admin-console": "ADMIN_HOST"}
KNOWN_GAP = set()   # 계약 v3.4.3 부터 kiosk-frontend(KIOSK_HOST)·admin-console(ADMIN_HOST)도 바인드 주소를 환경에서 받는다
S = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
SIDECARED = {n[:-3] if n.endswith("-gw") else n[:-4] for n in S if n.endswith(("-gw", "-tls"))}   # 영역 게이트웨이(-gw) 또는 TLS 사이드카(-tls)


class Loopback(unittest.TestCase):
    def test_every_sidecared_app_is_covered(self):
        self.assertEqual(SIDECARED, set(BIND) | KNOWN_GAP, "사이드카를 둔 앱 목록이 바뀌었다: BIND 또는 KNOWN_GAP 에 적는다")

    def test_bind_is_loopback(self):
        for n, k in BIND.items():
            v = str(S[n]["environment"].get(k, ""))
            self.assertTrue(v == "127.0.0.1" or v.startswith("127.0.0.1:"), f"{n}.{k}={v!r}: 앱은 loopback 에 바인드해야 한다")

    def test_sidecar_shares_namespace_of_app(self):
        for n in SIDECARED:
            self.assertEqual(S[n + ("-gw" if n + "-gw" in S else "-tls")]["network_mode"], f"service:{n}-net"); self.assertEqual(S[n]["network_mode"], f"service:{n}-net")


if __name__ == "__main__":
    unittest.main()
