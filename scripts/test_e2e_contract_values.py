#!/usr/bin/env python3
"""E2E 가 계약의 열거 값을 낡은 이름으로 기대하지 않는지 보는 정적 자체 시험(Docker 불필요). 사용: python3 scripts/test_e2e_contract_values.py
기대값의 출처: boundary-contracts PUBLIC_API.md StaffAlert: kind 의 알려진 값은 RISK_STOP, CALL_STAFF, USER_CALLED_STAFF 이고 목록 StaffAlert 와 세션 보기 StaffSessionView.alerts[] 가 같은 이름을 쓴다.
`pause_reason` 의 RISK 와 신호 `severity` 의 RISK 는 다른 필드라 그대로다. 서비스의 실제 응답이 아니라 계약이 기대값이다."""
import ast, os, pathlib, unittest

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ.get("E2E_STEPS", HERE / "e2e_steps.py")).read_text(encoding="utf-8")
TREE = ast.parse(SRC)
ALERT_KINDS = {"RISK_STOP", "CALL_STAFF", "USER_CALLED_STAFF"}


class T(unittest.TestCase):
    def test_alert_kind_is_never_compared_with_bare_RISK(self):
        """x["kind"] == "RISK" 꼴(알림 kind 를 뜻하는 비교)이 없다. 검사 종류의 kind(HUMAN_APPROVAL 등)와 섞이지 않게 RISK 만 본다."""
        bad = []
        for n in ast.walk(TREE):
            if isinstance(n, ast.Compare) and isinstance(n.left, ast.Subscript) and isinstance(n.left.slice, ast.Constant) and n.left.slice.value == "kind":
                if any(isinstance(c, ast.Constant) and c.value == "RISK" for c in n.comparators): bad.append(f"e2e_steps.py:{n.lineno}")
        self.assertEqual(bad, [], "알림 kind 를 RISK 로 기대한다(계약: RISK_STOP): " + ", ".join(bad))

    def test_no_stale_comment_saying_session_view_kind_is_RISK(self):
        stale = [i + 1 for i, l in enumerate(SRC.splitlines()) if "StaffViewAlert" in l or "kind 는 RISK(" in l]
        self.assertEqual(stale, [], f"낡은 주석(세션 조회 kind 가 RISK): e2e_steps.py:{stale}")

    def test_risk_alert_kind_asserted_as_RISK_STOP_in_both_views(self):
        n = sum(1 for l in SRC.splitlines() if '["kind"] == "RISK_STOP"' in l)
        self.assertGreaterEqual(n, 2, "목록과 세션 조회 둘 다 RISK_STOP 을 확인해야 한다")


class RuntimeVersionNotHardcoded(unittest.TestCase):
    """model-runtime 서버는 릴리스 매니페스트의 lineage.model_runtime_version MAJOR.MINOR 가 서버와 같을 때만 적재한다(0.7.x 릴리스는 UNSUPPORTED_VERSION; model-runtime v0.8.0).
    그러므로 E2E 가 만드는 매니페스트의 model_runtime_version 은 문자열 리터럴이 아니라 서버(/v1/info runtime_version) 또는 DEPLOY_MR_TAG 시점 패키지에서 와야 한다. 리터럴이면 태그를 올릴 때마다 조용히 어긋난다."""
    def test_manifest_runtime_version_is_not_a_literal(self):
        bad = []
        for n in ast.walk(TREE):
            if isinstance(n, ast.Dict):
                for k, v in zip(n.keys, n.values):
                    if isinstance(k, ast.Constant) and k.value in ("model_runtime_version", "runtime") and isinstance(v, ast.Constant) and isinstance(v.value, str):
                        bad.append(f"e2e_steps.py:{n.lineno}")
        self.assertEqual(bad, [], "model_runtime_version 을 리터럴로 박았다: " + ", ".join(bad))

    def test_no_pinned_runtime_version_in_fixtures(self):
        import re
        root = HERE.parent / "test"
        hits = [f"{p.relative_to(HERE.parent)}:{i + 1}" for p in root.rglob("*") if p.is_file() and p.suffix in (".json", ".txt", ".yaml", ".yml", ".py")
                for i, l in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines()) if re.search(r"model[_-]runtime[_-]version\W+\"?0\.\d+\.\d+", l)]
        self.assertEqual(hits, [], "시험 픽스처가 model_runtime_version 을 박고 있다: " + ", ".join(hits))

    def test_llm_attach_uses_runtime_constant(self):
        src = (HERE / "llm_attach_package.py").read_text(encoding="utf-8")
        self.assertIn('"model_runtime_version": mr.RUNTIME_VERSION', src)


class Step5pjMeasuresOnlyTheJob(unittest.TestCase):
    """5pj 는 '잡의 멱등'을 ops_log 지문으로 본다. ops_log 에는 잡 말고 ops-feedback-ingest(survey-service outbox 의 Trace 전송)도 쓴다(compose 의 OPS_LOG_DATABASE_URL_FILE 이 둘 다에 있다).
    앞 단계(5p·5pn)의 DB 장애로 밀린 Trace 가 5pj 도중에 전송되면 지문이 잡과 무관하게 바뀐다(gpu-dev e2e-bc220-run1 의 5pj 실패).
    그래서 첫 잡 실행·fp0 전에 survey outbox 가 비기를 기다리고(계약 SurveyReadyz.trace_outbox.pending == 0), fp1 에서 전송 수가 그대로인지 확인해야 한다."""
    def _body(self):
        fn = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "step5pj")
        return ast.get_source_segment(SRC, fn)

    def test_drains_outbox_before_baseline(self):
        b = self._body()
        self.assertIn("_outbox_drained(", b, "5pj 가 기준 지문 전에 outbox 가 비기를 기다리지 않는다")
        self.assertLess(b.index("_outbox_drained("), b.index("fp0 ="), "outbox 대기가 fp0 보다 뒤에 있다")
        self.assertLess(b.index("_outbox_drained("), b.index("rc0, tail0 = _run_ops_job()"), "outbox 대기가 첫 잡 실행보다 뒤에 있다(밀린 Trace 를 잡이 처리하기 전에 기준을 잡는다)")

    def test_checks_no_new_traces_between_fingerprints(self):
        b = self._body()
        self.assertRegex(b, r"sent1\s*==\s*sent0", "fp0~fp1 사이에 새 Trace 가 들어오지 않았음을 확인하지 않는다")

    def test_helper_uses_contract_field(self):
        fn = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "_outbox_drained")
        b = ast.get_source_segment(SRC, fn)
        self.assertIn('"trace_outbox"', b); self.assertIn('["pending"] == 0', b); self.assertIn('["sent"]', b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
