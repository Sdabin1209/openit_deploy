#!/usr/bin/env python3
"""R2.3·R5.1 정적: 게이트웨이 자신의 /healthz·/readyz 응답은 평문 "ok" 가 아니라 JSON 본문이다(R5.1 개정: 서비스의 Readyz 스키마가 계약에 없는 게이트웨이는 비어 있지 않은 JSON 객체. `{"status":"ok"}`/`{"status":"not-ready"}`). config/Caddyfile 에서 읽는다.
읽는 쪽(감시 blackbox, E2E)도 본문의 status 를 보는지 함께 본다. 사용: python3 scripts/test_gateway_health_body.py"""
import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CF = (ROOT / "config/Caddyfile").read_text(encoding="utf-8")


def responds_in(block_start_re):
    """Caddyfile 에서 정규식이 가리키는 `handle` 블록(들여쓰기 짝이 맞는 곳까지)의 텍스트들."""
    out = []
    for m in re.finditer(block_start_re, CF):
        depth, i = 0, CF.index("{", m.start())
        j = i
        while True:
            if CF[j] == "{": depth += 1
            elif CF[j] == "}":
                depth -= 1
                if depth == 0: break
            j += 1
        out.append(CF[i:j + 1])
    return out


class T(unittest.TestCase):
    def test_no_plain_ok_bodies(self):
        self.assertNotIn('respond "ok"', CF, "게이트웨이 건강 확인 본문이 평문 ok 다(HealthStatus JSON 이어야 한다)")
        self.assertNotIn('{"ready":false}', CF)

    def test_healthz_blocks_are_json_status(self):
        blocks = responds_in(r"handle /healthz \{")
        self.assertGreaterEqual(len(blocks), 2, "평문·TLS 사이트 모두에 /healthz 가 있어야 한다")
        for b in blocks:
            self.assertIn("Content-Type application/json", b); self.assertIn('{"status":"ok"}', b)

    def test_readyz_ok_and_not_ready_are_json_status(self):
        b = responds_in(r"handle /readyz \{")
        self.assertEqual(len(b), 1)
        self.assertIn('{"status":"ok"}', b[0]); self.assertIn('{"status":"not-ready"}', b[0])

    def test_readers_check_the_body(self):
        bb = (ROOT / "config/prometheus/blackbox.yml").read_text(encoding="utf-8")
        self.assertIn("fail_if_body_not_matches_regexp", bb.split("http_2xx_gateway:")[1].split("http_2xx:")[0], "게이트웨이를 보는 blackbox 모듈이 본문을 보지 않는다")
        e2e = (ROOT / "scripts/e2e.sh").read_text(encoding="utf-8")
        self.assertNotIn("grep -q '^ok'", e2e)

    def test_mutation(self):
        self.assertTrue(re.search(r'respond "ok"', 'respond "ok" 200'))   # 감지 규칙이 평문 ok 를 잡는다


if __name__ == "__main__":
    unittest.main()
