#!/usr/bin/env python3
"""정적 시험(CONVENTIONS 13절, platform 입력): 공개 입구(gateway)는 platform public-ingress 이미지로, deploy 는 영역 Exposure 선언 폴더(/etc/openit/exposures)만 마운트한다.
사람 인증 경로(/oauth2/*·/auth/*) 선언은 이미지에 내장돼 있으므로 deploy 에 손으로 쓴 프록시 설정(Caddyfile·auth 조각)이 없고, PIPELINE_SCHEMA_VERSION 은 deploy 가 주지 않는다(이미지가 계약 패키지 값으로 낸다).
변이 확인: Caddyfile 마운트를 더하거나 PIPELINE_SCHEMA_VERSION 을 주면 실패한다."""
import copy, unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
S0 = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]


def problems(S):
    g = S["gateway"]; errs = []
    if "openit/public-ingress@" not in str(g.get("image", "")): errs.append("공개 입구가 platform public-ingress 이미지가 아니다")
    targets = [str(c.get("target", "")) for c in (g.get("configs") or []) if isinstance(c, dict)]
    if any(t.endswith(("Caddyfile", "auth.caddy")) for t in targets): errs.append(f"손으로 쓴 프록시 설정을 마운트한다: {targets}")
    mounts = [str(v.get("target", "")) for v in (g.get("volumes") or []) if isinstance(v, dict)]
    if "/etc/openit/exposures" not in mounts: errs.append("영역 Exposure 선언 폴더(/etc/openit/exposures)를 마운트하지 않는다")
    if "/etc/openit/exposures-builtin" in mounts or "INGRESS_BUILTIN" in (g.get("environment") or {}): errs.append("내장 선언(exposures-builtin)을 deploy 가 덮어쓴다")
    if "PIPELINE_SCHEMA_VERSION" in (g.get("environment") or {}): errs.append("PIPELINE_SCHEMA_VERSION 은 이미지가 계약 패키지 값으로 낸다: deploy 가 주지 않는다")
    # 기기 인증(mTLS, 계약 PUBLIC_API F절·DeviceAllowlist, D136)
    env = g.get("environment") or {}
    if env.get("INGRESS_DEVICE_CA_FILE") != "/etc/openit/device-ca.pem": errs.append("INGRESS_DEVICE_CA_FILE 이 기기 CA 인증서 경로가 아니다")
    allow = env.get("INGRESS_DEVICE_ALLOWLIST_FILE", "")
    if not allow.startswith("/etc/openit/devices/"): errs.append(f"INGRESS_DEVICE_ALLOWLIST_FILE 이 목록 폴더 안이 아니다: {allow!r}")
    vols = [v for v in (g.get("volumes") or []) if isinstance(v, dict)]
    dev = [v for v in vols if v.get("target") == "/etc/openit/devices"]
    if len(dev) != 1 or not dev[0].get("read_only"): errs.append("기기 허용 목록 폴더(/etc/openit/devices)를 읽기 전용으로 마운트하지 않는다")
    elif "device-allowlist" not in str(dev[0].get("source", "")): errs.append("허용 목록 마운트의 원본이 전용 폴더(device-allowlist)가 아니다(파일이 아니라 부모 폴더, 비밀 폴더 아님)")
    if any(str(v.get("source", "")).rstrip("/").endswith(("/secrets", "device-ca.key", "device-certs")) or "/secrets/devices" in str(v.get("source", "")) for v in vols): errs.append("비밀 폴더·CA 개인 키·기기 키를 입구에 마운트한다")
    if "INGRESS_DEVICE_TOKENS_DIR" in env or any(str(v.get("target", "")) == "/run/secrets/devices" for v in vols): errs.append("기기 토큰 경로가 남아 있다(D136: 없어졌다)")
    return errs


class T(unittest.TestCase):
    def test_gateway_gets_only_area_declarations(self):
        self.assertEqual(problems(S0), [])

    def test_mutation_hand_written_caddyfile(self):
        m = copy.deepcopy(S0); m["gateway"]["configs"] = list(m["gateway"]["configs"]) + [{"source": "x", "target": "/etc/caddy/Caddyfile"}]
        self.assertTrue(problems(m))

    def test_mutation_secrets_folder_mounted(self):
        m = copy.deepcopy(S0); m["gateway"]["volumes"] = list(m["gateway"]["volumes"]) + [{"type": "bind", "source": "./secrets", "target": "/x", "read_only": True}]
        self.assertTrue(problems(m))

    def test_mutation_allowlist_mounted_as_file(self):
        m = copy.deepcopy(S0)
        for v in m["gateway"]["volumes"]:
            if isinstance(v, dict) and v.get("target") == "/etc/openit/devices": v["target"] = "/etc/openit/devices/allowlist.json"
        self.assertTrue(problems(m))

    def test_mutation_device_tokens_dir(self):
        m = copy.deepcopy(S0); m["gateway"]["environment"]["INGRESS_DEVICE_TOKENS_DIR"] = "/run/secrets/devices"
        self.assertTrue(problems(m))

    def test_mutation_schema_version_env(self):
        m = copy.deepcopy(S0); m["gateway"]["environment"]["PIPELINE_SCHEMA_VERSION"] = "2.0"
        self.assertTrue(problems(m))


if __name__ == "__main__":
    unittest.main()
