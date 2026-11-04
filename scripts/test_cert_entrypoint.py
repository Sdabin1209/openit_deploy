#!/usr/bin/env python3
"""정적 시험(RUNTIME-COMPONENTS.md DC-PKI.1, 실험 S8, ADR 0060): 인증서 컨테이너(<서비스>-cert, postgres-cert, 추론 model-serving-cert)는 시작할 때 파일의 존재가 아니라 검증(만료 포함)으로 발급 여부를 정한다
(`step certificate verify … ||` 발급). 존재만 보면 만료된 인증서가 남아 renew 가 `certificate expired` 로 거부된다. healthcheck 도 검증이라 만료된 인증서로는 healthy 가 아니다."""
import pathlib, unittest
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent


def certs(path):
    s = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))["services"]
    return {n: v for n, v in s.items() if n.endswith("-cert")}


class T(unittest.TestCase):
    def test_entrypoints_verify_before_skipping_issue(self):
        for path in ("compose.yaml", "compose.inference.yaml"):
            c = certs(path)
            self.assertTrue(c, path)
            for n, v in c.items():
                if True:   # 두 파일 모두 platform step-ca 이미지의 cert 부명령: 만료 검증·발급·갱신·HEALTHCHECK 는 이미지가 하고 platform 시험이 본다
                    env = v.get("environment") or {}
                    self.assertNotIn("command", v, f"{n}: 이미지 부명령을 deploy 가 적지 않는다(3.4.17: 역할은 StepCaEnv.STEP_ROLE)")
                    self.assertNotIn("user", v, f"{n}: 이미지가 선언한 사용자를 바꾸지 않는다(3.4.17)")
                    self.assertEqual(env.get("STEP_ROLE"), "cert", n)
                    self.assertEqual(env.get("STEP_CERT_NAME"), "${INFERENCE_TLS_NAME}" if path == "compose.inference.yaml" else n[:-5], f"{n}: 인증서 이름은 서비스 이름(추론 서버는 토큰이 정한 이름)")
                    self.assertTrue("openit/step-ca@" in v["image"] or "INFERENCE_STEP_IMAGE" in v["image"], n)
                    self.assertNotIn("entrypoint", v, f"{n}: 손으로 쓴 셸 한 줄 금지")
                    continue
                cmd = " ".join(v.get("entrypoint") or [])
                if "<<" in str(v) and not cmd:   # 앵커에서 오는 항목은 yaml 이 이미 합쳐 준다
                    continue
                self.assertIn("step certificate verify", cmd, f"{path} {n}: 시작 명령이 인증서 검증(만료)으로 발급을 정하지 않는다")
                self.assertNotIn("[ -s ", cmd, f"{path} {n}: 파일 존재만 본다(만료 뒤 복구 불가)")
                self.assertIn("step ca renew --daemon", cmd)

    def test_healthcheck_is_verification(self):
        for path in ("compose.yaml", "compose.inference.yaml"):
            for n, v in certs(path).items():
                self.assertNotIn("healthcheck", v, f"{path} {n}: 이미지 HEALTHCHECK 를 쓴다")


if __name__ == "__main__":
    unittest.main()
