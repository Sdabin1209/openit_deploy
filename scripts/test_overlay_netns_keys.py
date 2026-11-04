#!/usr/bin/env python3
"""정적 시험(RUNTIME.md R3.2, ADR 0060): 앱은 network_mode: service:<서비스>-net 이라 networks·ports·extra_hosts·dns·hostname·sysctls 같은 네트워크 키를 직접 가질 수 없다
(Docker 가 `conflicting options: custom host-to-IP mapping and the network mode` 로 거부한다; compose config 는 통과해서 기동 때에야 드러났다). 겹쳐쓰기 파일(compose.*.yaml, test/·demo/ 의
overlay)도 사이드카를 둔 앱 서비스에 이 키를 두면 안 된다 — <서비스>-net 에 둔다. 사용: python3 scripts/test_overlay_netns_keys.py"""
import glob, pathlib, unittest
import yaml


class _L(yaml.SafeLoader):   # compose 의 !reset 태그를 읽는다
    pass


_L.add_constructor("!reset", lambda l, n: None)
ROOT = pathlib.Path(__file__).resolve().parent.parent
FORBIDDEN = ("networks", "ports", "extra_hosts", "dns", "hostname", "mac_address", "sysctls")
STANDALONE = {"compose.inference.yaml", "compose.inference.samehost.yaml", "compose.inference.remote.yaml", "compose.registry.yaml", "compose.backup-target.yaml", "test/split/compose.split.yaml"}   # compose.yaml 에 겹치지 않는 독립 파일(자기 서비스 정의)
BASE = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
APPS = sorted(n[:-3] if n.endswith("-gw") else n[:-4] for n in BASE if n.endswith(("-gw", "-tls")))   # 영역 게이트웨이(-gw) 또는 TLS 사이드카(-tls)를 둔 앱


class T(unittest.TestCase):
    def test_apps_found(self):
        self.assertIn("survey-service", APPS); self.assertGreaterEqual(len(APPS), 11)

    def test_no_network_keys_on_apps_in_any_compose_file(self):
        files = [f for pat in ("compose*.yaml", "test/*.yaml", "demo/*.yaml", "test/*/*.yaml") for f in glob.glob(str(ROOT / pat))]
        bad = []
        for f in sorted(files):
            if str(pathlib.Path(f).relative_to(ROOT)) in STANDALONE:
                continue
            try:
                d = yaml.load(open(f, encoding="utf-8"), Loader=_L) or {}
            except yaml.YAMLError:
                continue
            for n, v in (d.get("services") or {}).items():
                if n in APPS and isinstance(v, dict):
                    bad += [f"{pathlib.Path(f).relative_to(ROOT)}: {n}.{k}" for k in FORBIDDEN if k in v and not (f.endswith("/compose.yaml") and k == "networks" and False)]
        self.assertEqual([b for b in bad if not b.startswith("compose.yaml:")], [], "앱 서비스에 네트워크 키: <서비스>-net 에 둔다")
        self.assertEqual([b for b in bad if b.startswith("compose.yaml:")], [], "compose.yaml 의 앱에 네트워크 키")


if __name__ == "__main__":
    unittest.main()
