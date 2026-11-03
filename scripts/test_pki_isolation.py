#!/usr/bin/env python3
"""TLS 사이드카를 둔 앱(과 그 사이드카)은 pki 망에 붙지 않는다. 사이드카는 앱의 네트워크 네임스페이스를 쓰므로, 앱이 pki 망에 있으면 같은 망의 다른 서비스가 그 앱·사이드카에 닿아 서비스 사이 차단이 깨진다
(4차 E2E: survey-service -> question-authoring 이 pki 망으로 닿았다). 인증서는 <서비스>-cert 컨테이너(pki 망)가 받아 볼륨으로 준다.
또 e2e.sh 가 "차단" 으로 확인하는 서비스 쌍은 compose 에서 공통 망이 없어야 한다.
변이 확인(일부러 망을 붙이면 실패하는가)은 작업 트리의 compose.yaml 을 건드리지 않고 임시 사본에서 한다. 사용: python3 scripts/test_pki_isolation.py"""
import copy, pathlib, re, sys, unittest

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from compose_nets import nets  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
S = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
E2E = (ROOT / "scripts/e2e.sh").read_text(encoding="utf-8")
CERT_ONLY = ("step-ca", "pki-root", "pki-tokens", "postgres-cert")


def sidecared_apps(svcs):
    return sorted(n[:-4] for n in svcs if n.endswith("-tls"))


def apps_on_pki(svcs):
    return [a for a in sidecared_apps(svcs) if "pki" in nets(svcs, a)]


def non_cert_on_pki(svcs):
    return [n for n in svcs if "pki" in nets(svcs, n) and not (n.endswith("-cert") or n in CERT_ONLY)]


def blocked_pairs_sharing_networks(svcs):
    pairs = re.findall(r'"차단: [^"]*" blocked ([a-z-]+) ([a-z-]+)', E2E)
    bad = []
    for a, b in pairs:
        if a not in svcs or b not in svcs or "model-serving" in (a, b):   # model-serving 은 제품 밖(다른 호스트 역할): compose.yaml 의 망으로 비교하지 않는다
            continue
        common = set(nets(svcs, a)) & set(nets(svcs, b))
        if common: bad.append(f"{a} -> {b}: 공통 망 {sorted(common)}")
    return bad


class T(unittest.TestCase):
    def test_product_compose_is_clean(self):
        self.assertTrue(sidecared_apps(S))
        self.assertEqual(apps_on_pki(S), [], "사이드카를 둔 앱이 pki 망에 있다(서비스 사이 차단이 깨진다)")
        self.assertEqual(non_cert_on_pki(S), [], "인증서 발급 컨테이너가 아닌데 pki 망에 있다")
        self.assertTrue(re.findall(r'"차단: [^"]*" blocked ([a-z-]+) ([a-z-]+)', E2E))
        self.assertEqual(blocked_pairs_sharing_networks(S), [], "차단이어야 하는 서비스 쌍이 같은 망에 있다")

    def test_mutations_on_a_copy_are_caught(self):
        # 작업 트리 파일이 아니라 메모리 사본(deepcopy)을 바꾼다
        m = copy.deepcopy(S); m["survey-service-net"]["networks"]["pki"] = {}
        self.assertIn("survey-service", apps_on_pki(m))
        m = copy.deepcopy(S); m["survey-service-net"]["networks"]["authoring"] = {}
        self.assertTrue(any(x.startswith("survey-service -> question-authoring") for x in blocked_pairs_sharing_networks(m)))
        m = copy.deepcopy(S); m["gateway"]["networks"] = list(m["gateway"]["networks"]) + ["pki"]
        self.assertIn("gateway", non_cert_on_pki(m))


if __name__ == "__main__":
    unittest.main()
