#!/usr/bin/env python3
"""계약 CONVENTIONS 6절(3.4.0): 게이트웨이는 인증을 마친 요청에 X-Openit-User 와 X-Openit-Roles 를 함께 붙이고, 클라이언트가 보낸 같은 이름의 헤더는 지운다.
정적 시험: (1) X-Openit-User 를 인증 계정으로 붙이는 모든 프록시가 X-Openit-Roles 도 붙인다, (2) X-Openit-User 를 지우는 모든 프록시가 X-Openit-Roles 도 지운다,
(3) question-authoring 설정에 삭제된 QA_USER_ROLES 가 없다. 사용: python3 scripts/test_gateway_roles_header.py"""
import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CF = (ROOT / "config/Caddyfile").read_text(encoding="utf-8")
CODE = [l.split("#", 1)[0] for l in CF.splitlines()]   # 주석 뒤는 보지 않는다


class T(unittest.TestCase):
    def test_every_proxy_that_sets_user_sets_roles(self):
        users = [i for i, l in enumerate(CODE) if re.search(r'header_up X-Openit-User "', l)]
        self.assertGreaterEqual(len(users), 10, "계정으로 사용자 헤더를 붙이는 프록시가 너무 적다(파서가 못 읽었다)")
        for i in users:
            self.assertIn("X-Openit-Roles", " ".join(CODE[i:i + 3]), f"Caddyfile:{i + 1} X-Openit-User 만 붙이고 X-Openit-Roles 는 안 붙인다")

    def test_every_proxy_that_strips_user_strips_roles(self):
        strips = [i for i, l in enumerate(CODE) if re.search(r'header_up -X-Openit-User\b', l)]
        self.assertGreaterEqual(len(strips), 5)
        for i in strips:
            self.assertIn("header_up -X-Openit-Roles", " ".join(CODE[i:i + 3]), f"Caddyfile:{i + 1} X-Openit-User 를 지우면서 X-Openit-Roles 는 안 지운다")

    def test_qa_user_roles_is_gone(self):
        for f in ("config/question-authoring.env", "compose.yaml"):
            self.assertNotIn("QA_USER_ROLES", re.sub(r"(?m)^\s*#.*$", "", (ROOT / f).read_text(encoding="utf-8")), f)


if __name__ == "__main__":
    unittest.main()
