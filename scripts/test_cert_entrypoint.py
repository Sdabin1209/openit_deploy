#!/usr/bin/env python3
"""정적 시험(RUNTIME.md R4.4, 실험 S8, ADR 0060): 인증서 컨테이너(<서비스>-cert, postgres-cert, 추론 model-serving-cert)는 시작할 때 파일의 존재가 아니라 검증(만료 포함)으로 발급 여부를 정한다
(`step certificate verify … ||` 발급). 존재만 보면 만료된 인증서가 남아 renew 가 `certificate expired` 로 거부된다. healthcheck 도 검증이라 만료된 인증서로는 healthy 가 아니다."""
import pathlib, unittest
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent


def certs(path):
    s = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))["services"]
    return {n: v for n, v in s.items() if n.endswith("-cert") or n == "postgres-cert"}


class T(unittest.TestCase):
    def test_entrypoints_verify_before_skipping_issue(self):
        for path in ("compose.yaml", "compose.inference.yaml"):
            c = certs(path)
            self.assertTrue(c, path)
            for n, v in c.items():
                cmd = " ".join(v.get("entrypoint") or [])
                if "<<" in str(v) and not cmd:   # 앵커에서 오는 항목은 yaml 이 이미 합쳐 준다
                    continue
                self.assertIn("step certificate verify", cmd, f"{path} {n}: 시작 명령이 인증서 검증(만료)으로 발급을 정하지 않는다")
                self.assertNotIn("[ -s ", cmd, f"{path} {n}: 파일 존재만 본다(만료 뒤 복구 불가)")
                self.assertIn("step ca renew --daemon", cmd)

    def test_healthcheck_is_verification(self):
        for path in ("compose.yaml", "compose.inference.yaml"):
            for n, v in certs(path).items():
                self.assertIn("verify", " ".join(map(str, v["healthcheck"]["test"])), f"{path} {n}")


if __name__ == "__main__":
    unittest.main()
