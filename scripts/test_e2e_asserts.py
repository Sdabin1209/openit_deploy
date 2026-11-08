"""e2e_asserts.py 자체 시험: 올바른 값은 통과하고 일부러 틀린 값은 AssertionError 가 나는지. 실행: python3 scripts/test_e2e_asserts.py"""
import copy, pathlib, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e2e_asserts as ea

OK_OUT = {"action": "NEXT", "next_item": "Q5", "values": [{"key": "Q4.answer", "precision": "exact", "save": True, "status": "ANSWERED", "value": False}]}
RB = {"inference": {"calls": 4, "failures": 0, "retries": 0, "timeouts": 0, "output_invalid": 0, "outcome_fallback": 0}, "trace_outbox": {"sent": 3}}
RA = {"inference": {"calls": 8, "failures": 0, "retries": 0, "timeouts": 0, "output_invalid": 0, "outcome_fallback": 0}, "trace_outbox": {"sent": 5}}
REP = [{"response_text": "(가짜 응답)", "turn_failure_signal": None}] * 2


class T(unittest.TestCase):
    def test_extraction(self):
        self.assertTrue(ea.check_fake_extraction(OK_OUT, "Q4.answer", False, "Q5"))
        for key, val, nxt in (("Q4.answer", True, "Q5"), ("Q4.answer", False, "Q4_1"), ("Q5.answer", False, "Q5")):   # 값·건너뛰기·키가 틀림
            with self.assertRaises(AssertionError): ea.check_fake_extraction(OK_OUT, key, val, nxt)
        with self.assertRaises(AssertionError): ea.check_fake_extraction({**OK_OUT, "values": []}, "Q4.answer", False, "Q5")   # 빈 values(옛 동작)
        with self.assertRaises(AssertionError): ea.check_fake_extraction(OK_OUT, "Q4.answer", 0, "Q5")   # bool 과 int 구분

    def test_out_of_range_reask(self):
        ok = {"action": "REASK", "next_item": "Q8_1", "values": [{"key": "Q8_1.days", "precision": "unspecified", "save": False, "status": "UNCLEAR", "value": None}], "reason": "OUT_OF_RANGE", "targets": ["Q8_1.days"]}
        self.assertTrue(ea.check_out_of_range_reask(ok, "Q8_1", "Q8_1.days"))
        for bad in ({**ok, "action": "NEXT"}, {**ok, "reason": "MISSING"}, {**ok, "next_item": "Q8_2"}, {**ok, "targets": ["Q9_1.days"]},
                    {**ok, "values": [{**ok["values"][0], "save": True}]}, {**ok, "values": [{**ok["values"][0], "value": 8, "status": "ANSWERED"}]}):
            with self.assertRaises(AssertionError): ea.check_out_of_range_reask(bad, "Q8_1", "Q8_1.days")

    def test_turns(self):
        self.assertTrue(ea.check_turns_clean(REP, RB, RA))
        bad = copy.deepcopy(REP); bad[1] = {"response_text": "(가짜 응답)", "turn_failure_signal": {"write_committed": "NOT_COMMITTED"}}
        with self.assertRaises(AssertionError): ea.check_turns_clean(bad, RB, RA)
        with self.assertRaises(AssertionError): ea.check_turns_clean([{"response_text": "안녕", "turn_failure_signal": None}] * 2, RB, RA)
        ra = copy.deepcopy(RA); ra["inference"]["output_invalid"] = 1
        with self.assertRaises(AssertionError): ea.check_turns_clean(REP, RB, ra)
        ra = copy.deepcopy(RA); ra["trace_outbox"]["sent"] = 3
        with self.assertRaises(AssertionError): ea.check_turns_clean(REP, RB, ra)

    def test_server_text_by_backend(self):
        self.assertTrue(ea.server_text_ok("(가짜 응답)", "fake")); self.assertFalse(ea.server_text_ok("네, 알겠습니다.", "fake"))
        self.assertTrue(ea.server_text_ok("네, 알겠습니다.", "mimic"))
        self.assertFalse(ea.server_text_ok("(가짜 응답)", "mimic"), "fake 문장이면 mimic 구성이 아니다")
        self.assertTrue(ea.server_text_ok("네. 다음 문항입니다.", "mimic", "다음 문항"))
        self.assertFalse(ea.server_text_ok("네. 다음 문항입니다.", "mimic", "다른 문항"), "문진표가 정한 다음 문항 문장이 없으면 실패")
        self.assertFalse(ea.server_text_ok("  ", "mimic")); self.assertFalse(ea.server_text_ok(None, "mimic"))
        mimic = [{"response_text": "네, 알겠습니다.", "turn_failure_signal": None}] * 2
        self.assertTrue(ea.check_turns_clean(mimic, RB, RA, "mimic"))
        self.assertTrue(ea.check_turns_clean(mimic, RB, RA, "mimic", {0: "알겠습니다"}))
        with self.assertRaises(AssertionError): ea.check_turns_clean(mimic, RB, RA, "mimic", {1: "없는 문장"})
        with self.assertRaises(AssertionError): ea.check_turns_clean(mimic, RB, RA)   # 기본(fake)은 그대로 엄격하다
        ra = copy.deepcopy(RA); ra["inference"]["calls"] = RB["inference"]["calls"]
        with self.assertRaises(AssertionError): ea.check_turns_clean(mimic, RB, ra, "mimic")   # 서버를 거쳤는지는 호출 수 증가로 본다

    def test_backend_identity_is_compared(self):
        src = (pathlib.Path(__file__).resolve().parent / "e2e_steps.py").read_text(encoding="utf-8")
        self.assertNotIn('info["backend"] == "fake"', src, "추론 서버 백엔드 대조는 --model-backend 로 한다")

    def test_no_neighbor_internals(self):
        """구조 규칙 1: 단계·샌드박스·데모는 이웃 영역의 내부 모듈을 import 하지 않는다(계약 boundary_contracts 와 통신 기반 openit_link 만). 예외를 삼켜 '대조 불가'로 넘어가는 것도 금지."""
        import re
        here = pathlib.Path(__file__).resolve().parent
        pat = re.compile(r"(?:import|from)\s+(model_runtime|survey_service|question_authoring|ops_feedback|release_gate|model_registry|dataset_store|kiosk_frontend)\b")
        for f in ("e2e_steps.py", "e2e_sandbox.py", "demo.sh", "e2e.sh"):
            src = (here / f).read_text(encoding="utf-8")
            self.assertIsNone(pat.search(src), f"{f} 가 이웃 영역 내부 모듈을 import 한다: {pat.search(src) and pat.search(src).group(0)}")
            self.assertNotIn("대조 불가(", src, f"{f}: 예외를 삼키고 대조 불가로 넘어가는 경로")

    def test_first_answer_exception_is_independent(self):
        slots = {"Q1.D01": [{"key": "Q1.D01.diagnosed"}]}   # 흐름 파일 slots: Q3 는 칸이 없다
        v1 = [{"key": "Q1.D01.diagnosed"}]
        self.assertEqual(ea.check_first_answer("Q1.D01", "Q1.D01", v1, "mimic", slots, "x", "다음"), "valued")
        self.assertEqual(ea.check_first_answer("Q3", "Q3", [], "mimic", slots, "감사합니다. 다음 문항", "다음 문항"), "slotless")
        # 변이: 칸이 있는 A 의 첫 값이 비면 실패(mimic 이어도)
        with self.assertRaises(AssertionError): ea.check_first_answer("Q1.D01", "Q1.D01", [], "mimic", slots, "다음", "다음")
        with self.assertRaises(AssertionError): ea.check_first_answer("Q1.D01", "Q1.D01", [{"key": "Q9.x"}], "mimic", slots, "다음", "다음")
        # 칸 없는 첫 문항이어도 다음 문항 문장이 없으면, 값이 저장돼 있으면 실패
        with self.assertRaises(AssertionError): ea.check_first_answer("Q3", "Q3", [], "mimic", slots, "엉뚱", "다음 문항")
        with self.assertRaises(AssertionError): ea.check_first_answer("Q3", "Q3", [{"key": "Q3.x"}], "mimic", slots, "다음 문항", "다음 문항")
        # fake 는 예외가 없다(원래 단언 그대로)
        with self.assertRaises(AssertionError): ea.check_first_answer("Q3", "Q3", [], "fake", slots, "다음 문항", "다음 문항")

    def test_literal_ids_fit_contract(self):
        """E2E 가 직접 만드는 ID 리터럴(RID 를 넣은 것)이 계약 5.0.0 ID 규칙을 따른다. 규칙의 사본은 두지 않고 계약 패키지로 판정한다(D117). --run-id 값은 e2e.sh(e2e-test)·demo.sh(demo-test)."""
        import boundary_contracts as bc
        for rid in ("e2e-test", "demo-test"):
            for raw in (f"s-{rid}", f"t-{rid}-9", f"sig-{rid}-1"):
                self.assertTrue(bc.is_id(raw), raw); self.assertEqual(bc.envelope_id(raw), raw)   # Id 형식이면 봉투 ID 는 원본 그대로
            body = {"kind": "SESSION_START", "question_set_id": "health-screening", "subject_ref": f"e2e-subject-{rid}"}
            v = bc.validator("PublicApiRequests#/$defs/SessionStartBody")   # subject_ref 패턴·상한은 계약이 판정한다
            self.assertEqual([e.message for e in v.iter_errors(body)], [])
        self.assertTrue(bc.envelope_id("공백 있는 ID").startswith("x-"))   # 변환 규칙은 계약 함수의 몫: deploy 는 호출만 한다

    def test_unchanged(self):
        b = {"survey-service": ("id1", "t1"), "gateway": ("id2", "t2")}
        self.assertTrue(ea.check_unchanged(b, dict(b), list(b)))
        with self.assertRaises(AssertionError): ea.check_unchanged(b, {**b, "gateway": ("id2", "t3")}, list(b))
        with self.assertRaises(AssertionError): ea.check_unchanged(b, {"survey-service": b["survey-service"]}, list(b))

    def test_loaded(self):
        self.assertTrue(ea.check_release_loaded({"release_id": "r2", "state": "LOADED", "error": None}, "r2"))
        for st in ({"release_id": "r2", "state": "LOADING", "error": None}, {"release_id": "r1", "state": "LOADED", "error": None}):
            with self.assertRaises(AssertionError): ea.check_release_loaded(st, "r2")


if __name__ == "__main__":
    unittest.main()
