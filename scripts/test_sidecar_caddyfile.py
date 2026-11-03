#!/usr/bin/env python3
"""정적 시험(RUNTIME.md R1.2·R3.9, ADR 0060): 서비스 TLS 사이드카 설정(config/tls-sidecar.caddy)은 (1) 평문 리스너를 열지 않는다(http:// 사이트·:80 없음, auto_https off),
(2) 사이트 이름은 서비스 이름 하나(+ 이름 없는 catch-all)이고 localhost 는 Host 매처다(사이트 이름이 localhost 면 Caddy 가 local CA 인증서를 만들려 한다),
(3) 서빙은 파일 인증서(tls <crt> <key>)이고 ACME 도전·internal 발급자가 없다. 사용: python3 scripts/test_sidecar_caddyfile.py"""
import pathlib, re, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
TXT = "\n".join(l for l in (ROOT / "config/tls-sidecar.caddy").read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))
SITES = re.findall(r"^(\S.*?)\s*\{\s*$", TXT, re.M)   # 들여쓰지 않은 줄의 사이트 블록(전역 옵션 블록 `{` 는 제외)


class T(unittest.TestCase):
    def test_no_plaintext_listener(self):
        self.assertIn("auto_https off", TXT)
        self.assertNotRegex(TXT, r"http://|:80\b|http_port")
        for s in SITES:
            self.assertTrue(s.strip().startswith("https://"), f"사이트 {s!r}: https:// 가 아니다")

    def test_sites_are_service_name_and_catch_all_only(self):
        sites = [s.strip() for s in SITES]
        self.assertEqual(sites, ["https://{$TLS_NAME}", "https://"], sites)
        self.assertIn("@local host {$TLS_ALT_NAME:localhost}", TXT)

    def test_file_certificate_only(self):
        self.assertEqual(len(re.findall(r"tls /certs/tls\.crt /certs/tls\.key", TXT)), 2)
        self.assertNotRegex(TXT, r"issuer|acme|internal|on_demand")


if __name__ == "__main__":
    unittest.main()
