#!/usr/bin/env python3
"""정적 시험(R6.2·R1.8): 추론 서버(compose.inference.yaml)의 영역 게이트웨이가 허용하는 나가는 상대(model-runtime 이미지 라벨 io.openit.exposure 의 egress)가
이 compose 가 실제로 부르는 상대와 이름으로 맞는다. 영역 게이트웨이의 나가는 쪽은 선언된 `<이름>:443` 만 연다(그 밖은 403 EGRESS_DENIED).
- 입력: build/images.env 의 model-serving 이미지 라벨(없으면 SKIP 으로 끝낸다: 통과로 세지 않는다, 종료 코드 77)
- 규칙: (1) MODEL_RUNTIME_RELEASE_URL 의 호스트 이름이 egress 항목이어야 하고 포트는 443 이어야 한다. (2) egress 의 각 이름은 이 compose 의 extra_hosts 나 네트워크 별칭으로 풀려야 한다.
변이 확인: egress 에 없는 이름이나 8443 포트를 주면 실패한다."""
import json, re, subprocess, sys, unittest
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parent.parent
C = yaml.safe_load((ROOT / "compose.inference.yaml").read_text(encoding="utf-8"))["services"]


def label_egress():
    envf = ROOT / "build/images.env"
    if not envf.exists(): return None
    img = next((l.split()[1] for l in envf.read_text().splitlines() if l.startswith("model-serving ")), None)
    if not img: return None
    r = subprocess.run(["docker", "image", "inspect", img, "--format", '{{index .Config.Labels "io.openit.exposure"}}'], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip(): return None
    return json.loads(r.stdout).get("egress", [])


def problems(compose, egress):
    errs = []
    url = str((compose["model-serving"].get("environment") or {}).get("MODEL_RUNTIME_RELEASE_URL", ""))
    m = re.match(r"^https://([a-z0-9.-]+)(?::(\d+))?(/.*)?$", url)
    if not m:   # ${RELEASE_URL} 처럼 값이 실행 때 정해지면 이름을 정적으로 알 수 없다: 이름이 egress 안에 있다고 보장할 수 없다
        errs.append(f"MODEL_RUNTIME_RELEASE_URL 이 정적으로 egress 이름이 아니다: {url!r}")
    else:
        if m.group(1) not in egress: errs.append(f"RELEASE_URL 호스트 {m.group(1)} 가 egress {egress} 에 없다")
        if (m.group(2) or "443") != "443": errs.append(f"RELEASE_URL 포트 {m.group(2)} 는 443 이 아니다(게이트웨이 출구는 <이름>:443 만 연다)")
    hosts = " ".join(str(h) for sv in compose.values() for h in (sv.get("extra_hosts") or []))
    for name in egress:
        if name not in hosts: errs.append(f"egress {name} 를 풀어 줄 extra_hosts 가 없다")
    return errs


class T(unittest.TestCase):
    def test_compose_matches_the_declared_egress(self):
        eg = label_egress()
        if eg is None:
            print("SKIP: model-serving 이미지 라벨을 읽지 못했다(build/images.env, docker)"); sys.exit(77)
        self.assertEqual(problems(C, eg), [])

    def test_mutation_is_caught(self):
        good = {"model-serving": {"environment": {"MODEL_RUNTIME_RELEASE_URL": "https://release-gate"}}, "n": {"extra_hosts": ["release-gate:10.0.0.1"]}}
        self.assertEqual(problems(good, ["release-gate"]), [])
        bad = {"model-serving": {"environment": {"MODEL_RUNTIME_RELEASE_URL": "https://other:8443"}}, "n": {}}
        self.assertTrue(problems(bad, ["release-gate"]))


if __name__ == "__main__":
    unittest.main()
