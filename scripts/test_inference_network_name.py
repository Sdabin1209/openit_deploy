#!/usr/bin/env python3
"""정적 시험(compose 망 이름 규칙): 같은 호스트의 추론 서버가 붙는 외부 망 이름 INFERENCE_RELEASE_NETWORK 는 `<주 서버 프로젝트>_<compose.yaml 의 망 이름>` 이다(compose 가 프로젝트 이름을 망 이름 앞에 붙인다).
그 망 이름(inference-in)은 compose.yaml 에 정의돼 있고 release-gate pod 가 별칭 release-gate 로 붙어 있어야 한다. e2e.sh·test-inference-location.sh 가 쓰는 문자열이 이 규칙과 같다.
변이 확인: 망 이름이나 접두사를 바꾸면 실패한다."""
import re, unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
C = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
USERS = ["scripts/e2e.sh", "scripts/test-inference-location.sh"]
PAT = re.compile(r'INFERENCE_RELEASE_NETWORK="\$\{?(\w+)\}?_([a-z0-9-]+)"')


def uses(text):
    return PAT.findall(text)


def problems(text, compose):
    errs = []
    found = uses(text)
    if not found: errs.append("INFERENCE_RELEASE_NETWORK=\"<프로젝트>_<망>\" 을 쓰지 않는다")
    for proj, net in found:
        if net not in (compose.get("networks") or {}): errs.append(f"망 {net} 이 compose.yaml 에 없다")
        pod = (compose["services"].get("release-gate-net") or {}).get("networks") or {}
        if net not in pod or "release-gate" not in ((pod[net] or {}).get("aliases") or []): errs.append(f"release-gate-net 이 {net} 에 별칭 release-gate 로 붙어 있지 않다")
    return errs


class T(unittest.TestCase):
    def test_scripts_use_the_compose_network_name(self):
        for u in USERS:
            self.assertEqual(problems((ROOT / u).read_text(encoding="utf-8"), C), [], u)

    def test_overlay_uses_the_same_variable(self):
        class L(yaml.SafeLoader): pass
        L.add_constructor("!reset", lambda l, n: None)   # compose 의 !reset 태그
        o = yaml.load((ROOT / "compose.inference.samehost.yaml").read_text(encoding="utf-8"), Loader=L)
        self.assertIn("INFERENCE_RELEASE_NETWORK", str(o["networks"]["release"]["name"]))
        self.assertTrue(o["networks"]["release"]["external"])

    def test_mutation_wrong_name_is_caught(self):
        t = (ROOT / USERS[0]).read_text(encoding="utf-8").replace("_inference-in", "_inference-out")
        self.assertTrue(problems(t, C))


if __name__ == "__main__":
    unittest.main()
