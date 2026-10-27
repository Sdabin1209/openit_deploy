"""e2e_asserts.py 자체 시험: 올바른 값은 통과하고 일부러 틀린 값은 AssertionError 가 나는지. 실행: python3 scripts/test_e2e_asserts.py"""
import copy, os, sys, unittest
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

    def test_turns(self):
        self.assertTrue(ea.check_turns_clean(REP, RB, RA))
        bad = copy.deepcopy(REP); bad[1] = {"response_text": "(가짜 응답)", "turn_failure_signal": {"write_committed": "NOT_COMMITTED"}}
        with self.assertRaises(AssertionError): ea.check_turns_clean(bad, RB, RA)
        with self.assertRaises(AssertionError): ea.check_turns_clean([{"response_text": "안녕", "turn_failure_signal": None}] * 2, RB, RA)
        ra = copy.deepcopy(RA); ra["inference"]["output_invalid"] = 1
        with self.assertRaises(AssertionError): ea.check_turns_clean(REP, RB, ra)
        ra = copy.deepcopy(RA); ra["trace_outbox"]["sent"] = 3
        with self.assertRaises(AssertionError): ea.check_turns_clean(REP, RB, ra)

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
