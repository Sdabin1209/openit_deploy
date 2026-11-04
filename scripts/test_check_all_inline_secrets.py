#!/usr/bin/env python3
"""단독 시험(check-all 규칙 6, D84 비밀은 파일로): 설정 파일의 인라인 비밀 점검은 값 기준이다. 참·거짓·정수 문자열("true"/"false"/숫자)은 비밀로 보지 않는다(파일별 예외 목록 없음).
- Keycloak realm 템플릿 모양(`*.token.claim: "true"`, `secret: OPENIT_GATEWAY_CLIENT_SECRET` 자리표시)은 통과한다. - 같은 키에 임의 문자열을 넣으면 걸린다(변이)."""
import json, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from openit_deploy.components import consistency_check as C  # noqa: E402

REALM = {"clients": [{"clientId": "gateway", "secret": "OPENIT_GATEWAY_CLIENT_SECRET", "protocolMappers": [{"name": "roles", "config": {
    "id.token.claim": "true", "access.token.claim": "true", "userinfo.token.claim": "true", "introspection.token.claim": "true", "claim.name": "roles"}}]}]}


def findings(doc):
    return C.inline_secret_findings(C.compose_doc(json.dumps(doc)))


class T(unittest.TestCase):
    def test_realm_template_shape_passes(self):
        self.assertEqual(findings(REALM), [])

    def test_literals_that_cannot_be_secrets(self):
        for v in ("true", "False", "12", "-3"):
            self.assertEqual(findings({"a": {"token.claim": v}}), [], v)

    def test_mutation_random_string_on_the_same_key_is_caught(self):
        bad = json.loads(json.dumps(REALM)); bad["clients"][0]["protocolMappers"][0]["config"]["id.token.claim"] = "hunter2-Xk9fQ"
        self.assertEqual([p for _, p in findings(bad)], ["clients[0].protocolMappers[0].config.id.token.claim"])
        bad2 = json.loads(json.dumps(REALM)); bad2["clients"][0]["secret"] = "s3cr3tvalue"
        self.assertEqual(len(findings(bad2)), 1)


if __name__ == "__main__":
    unittest.main()
