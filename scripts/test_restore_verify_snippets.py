#!/usr/bin/env python3
"""복구 검증(link_restore_verify)이 컨테이너 안에서 실행할 코드 조각을 호스트에서 **실행**해 본다(가짜 주소라 호출은 실패하고 except 경로로 JSON 이 나와야 한다).
왜: 4차·5차 E2E(2026-11-01)에서 format 하지 않는 조각(_GATE, _POST)에 겹친 중괄호가 남아 set 리터럴이 되어 컨테이너 안에서만 TypeError 가 났다. 컴파일만으로는 잡히지 않는다(문법은 맞다)."""
from child_env import child_env  # R9.1: 하위 프로세스는 최소 환경만(scripts/child_env.py)
import json, pathlib, subprocess, sys, unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from openit_deploy.components import link_restore_verify as m


class SnippetsRun(unittest.TestCase):
    def test_snippets_run_and_emit_json(self):
        for name, cls, body in (("_QA", "HttpQuestionReader", m._QA.format(qs="qs-x")), ("_OPS", "HttpTraceIngest", m._OPS.format(env="{}")),
                                ("_MR", "HttpModelRegistry", m._MR.format(pid="p")), ("_GATE", "HttpReleaseReader", m._GATE)):
            src = m._snippet(cls, "http://127.0.0.1:1", "t", body)   # 포트 1: 아무도 듣지 않아 연결 거부 -> except 경로
            self.assertNotIn("{{", src, name)
            r = subprocess.run([sys.executable, "-"], input=src, capture_output=True, text=True, timeout=60, env=child_env())
            self.assertEqual(r.returncode, 0, f"{name}: {r.stderr[-300:]}")
            out = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertIn("ok", out, name); self.assertFalse(out["ok"], name); self.assertIn("error", out, name)


if __name__ == "__main__":
    unittest.main()
