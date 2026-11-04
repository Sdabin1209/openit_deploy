#!/usr/bin/env python3
"""R1.3 (호출하는 쪽만): 다른 서비스를 https 로 부르는 컨테이너(호출자)는 모두 step-ca 루트를 믿는다: 환경에 SSL_CERT_FILE(또는 서비스별 CA 파일 변수)이 있고 pki-root 볼륨을 마운트한다.
호출자 목록은 고정하지 않고 compose.yaml 의 환경·env_file 값에서 `https://<compose 서비스 이름>` 을 찾아 뽑는다. 호출받는 쪽(사이드카·인증서 컨테이너)은 대상이 아니다.
사용: python3 scripts/test_callers_trust_root.py"""
import copy, pathlib, re, unittest, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
_Y = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
S = _Y["services"]
CONFIGS = _Y.get("configs") or {}
TRUST_ENV = ("SSL_CERT_FILE", "OAUTH2_PROXY_PROVIDER_CA_FILES")   # 서비스별 CA 파일 변수(oauth2-proxy 는 자기 변수를 쓴다)
# 호출하지 않는 서비스: 사이드카·인증서 컨테이너·일회용은 서비스를 https 로 부르지 않는다(이름 값만 있다)
SKIP_SUFFIX = ("-tls", "-cert", "-net")


def env_text(svc):
    parts = [str(v) for v in (svc.get("environment") or {}).values()]
    for f in svc.get("env_file") or []:
        fp = ROOT / str(f).replace("${CONFIG_DIR:-./config}", "config")
        if fp.exists(): parts.append(fp.read_text(encoding="utf-8"))
    # 마운트하는 설정 파일(게이트웨이의 Caddyfile·auth.caddy, ops 잡의 job.yaml)도 호출 주소를 담는다
    for v in svc.get("volumes") or []:
        for m in re.finditer(r"config/[A-Za-z0-9_./-]+", str(v).split(":")[0] + (str(v).split(":")[1] if str(v).startswith("${") else "")):
            fp = ROOT / m.group(0)
            if fp.is_file(): parts.append(fp.read_text(encoding="utf-8"))
    for c in svc.get("configs") or []:   # 게이트웨이 Caddyfile 등: compose configs 의 원본 파일
        src = (c.get("source") if isinstance(c, dict) else c)
        f = (CONFIGS.get(src) or {}).get("file", "")
        fp = ROOT / re.sub(r"^\$\{CONFIG_DIR:-\./config\}", "config", str(f))
        if fp.is_file(): parts.append(fp.read_text(encoding="utf-8"))
    return "\n".join(parts)


def callers(svcs):
    names = [n for n in svcs if not n.endswith(SKIP_SUFFIX)]
    out = {}
    for n, s in svcs.items():
        if n.endswith(SKIP_SUFFIX) or n in ("step-ca", "pki-root", "pki-tokens"): continue
        txt = env_text(s)
        hit = sorted({m for m in names if m != n and re.search(r"https://%s(?![A-Za-z0-9-])" % re.escape(m), txt)})
        if n == "gateway":   # 공개 입구(platform 이미지)의 상류는 영역 Exposure 선언에서 온다(이미지 라벨). compose 에서는 기다리는 영역 게이트웨이(<서비스>-gw)와 인증(keycloak·oauth2-proxy)으로 안다
            dep = set((s.get("depends_on") or {}).keys())
            hit = sorted(set(hit) | {d[:-3] for d in dep if d.endswith("-gw") and d[:-3] in svcs} | {d for d in ("keycloak", "oauth2-proxy") if d in dep})
        if hit: out[n] = hit
    return out


def trust_problems(svcs):
    bad = []
    for n in callers(svcs):
        s = svcs[n]; env = s.get("environment") or {}
        # 게이트웨이(Caddy)는 환경 변수가 아니라 설정의 tls_trusted_ca_certs 로 같은 루트 파일을 믿는다
        via_caddy = "tls_trusted_ca_certs /etc/openit/pki/root_ca.crt" in env_text(s) or (n == "gateway" and any("pki-root:/etc/openit/pki" in str(v) for v in s.get("volumes") or []))   # platform 공개 입구는 /etc/openit/pki/root_ca.crt 를 이미지 설정이 믿는다
        if not any(k in env for k in TRUST_ENV) and not via_caddy: bad.append(f"{n}: 루트 파일 환경 변수({'/'.join(TRUST_ENV)})가 없다")
        if not any("pki-root" in str(v) for v in s.get("volumes") or []): bad.append(f"{n}: pki-root 볼륨 마운트가 없다")
    return bad


class T(unittest.TestCase):
    def test_callers_found_from_compose(self):
        c = callers(S)
        self.assertTrue(c, "호출자를 하나도 못 뽑았다: 뽑는 규칙이 깨졌다")
        self.assertIn("survey-service", c)

    def test_every_caller_trusts_the_root(self):
        self.assertEqual(trust_problems(S), [])

    def test_mutation_missing_trust_is_caught(self):
        m = copy.deepcopy(S); m["survey-service"]["environment"] = {k: v for k, v in m["survey-service"]["environment"].items() if k != "SSL_CERT_FILE"}
        self.assertTrue(any("survey-service" in x for x in trust_problems(m)))
        m = copy.deepcopy(S); m["survey-service"]["volumes"] = [v for v in m["survey-service"].get("volumes", []) if "pki-root" not in str(v)]
        self.assertTrue(any("survey-service" in x and "마운트" in x for x in trust_problems(m)))


if __name__ == "__main__":
    unittest.main()
