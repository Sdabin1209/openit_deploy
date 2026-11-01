#!/usr/bin/env python3
"""복구 검증(link_restore_verify)이 컨테이너 안에서 실행할 코드 조각은 호스트에서 먼저 컴파일된다.
왜: 4차 E2E(2026-11-01)에서 format 하지 않는 조각(_GATE)에 겹친 중괄호가 남아 set 리터럴이 되어 컨테이너 안에서 TypeError 가 났다. 가짜 runner 시험은 조각을 실행하지 않아 못 잡았다."""
import pathlib, sys, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from openit_deploy.components import link_restore_verify as m


class SnippetsCompile(unittest.TestCase):
    def test_snippets_compile_and_have_no_doubled_braces(self):
        for name, body in (("_QA", m._QA.format(qs="qs-x")), ("_OPS", m._OPS.format(env="{}")), ("_MR", m._MR.format(pid="p")), ("_GATE", m._GATE)):
            self.assertNotIn("{{", body, name)
            compile(m._snippet("X", "http://127.0.0.1:8080", "t", body), name, "exec")


if __name__ == "__main__":
    unittest.main()
