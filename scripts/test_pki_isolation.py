#!/usr/bin/env python3
"""TLS 사이드카를 둔 앱(과 그 사이드카)은 pki 망에 붙지 않는다. 사이드카는 앱의 네트워크 네임스페이스를 쓰므로, 앱이 pki 망에 있으면 같은 망의 다른 서비스가 그 앱·사이드카에 닿아 서비스 사이 차단이 깨진다
(4차 E2E: survey-service -> question-authoring 이 pki 망으로 닿았다). 인증서는 <서비스>-cert 컨테이너(pki 망)가 받아 볼륨으로 준다. 사용: python3 scripts/test_pki_isolation.py"""
import pathlib, re, unittest, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
S = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]


class T(unittest.TestCase):
    def test_sidecared_apps_are_not_on_pki(self):
        apps = sorted({str(v["network_mode"]).split(":", 1)[1] for v in S.values() if str(v.get("network_mode") or "").startswith("service:")})
        self.assertTrue(apps)
        self.assertEqual([a for a in apps if "pki" in (S[a].get("networks") or [])], [], "사이드카를 둔 앱이 pki 망에 있다(서비스 사이 차단이 깨진다)")

    def test_only_cert_issuing_containers_use_pki(self):
        on = sorted(n for n, s in S.items() if "pki" in (s.get("networks") or []))
        bad = [n for n in on if not (n.endswith("-cert") or n in ("step-ca", "pki-root", "pki-tokens", "postgres-cert"))]
        self.assertEqual(bad, [])

    def test_pairs_that_e2e_expects_blocked_share_no_network(self):
        # E2E 가 "차단" 으로 확인하는 서비스 쌍(e2e.sh 의 `blocked A B`)은 compose 에서 공통 망이 없어야 한다. 사이드카·인증서 컨테이너가 앱의 망 구성을 바꿔 이 차단이 깨졌다(4차 E2E)
        # model-serving 은 제품 밖(다른 호스트 역할)이라 compose.yaml 의 망으로 비교하지 않는다(외부 추론 모드)
        e2e = (ROOT / "scripts/e2e.sh").read_text(encoding="utf-8")
        pairs = re.findall(r'"차단: [^"]*" blocked ([a-z-]+) ([a-z-]+)', e2e)
        self.assertTrue(pairs)
        nets = lambda n: set(S[n].get("networks") or []) if n in S else None
        bad = []
        for a, b in pairs:
            na, nb = nets(a), nets(b)
            if na is None or nb is None or "model-serving" in (a, b): continue
            if na & nb: bad.append(f"{a} -> {b}: 공통 망 {sorted(na & nb)}")
        self.assertEqual(bad, [], "차단이어야 하는 서비스 쌍이 같은 망에 있다")


if __name__ == "__main__":
    unittest.main()
