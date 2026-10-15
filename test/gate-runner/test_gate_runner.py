"""시험용 승인 평가 실행기(E2E 전용, TEST-SUB). 실제 평가를 하지 않는다: 모델을 부르지 않고 고정된 시험 지표를 낸다.
release-gate는 AcceptanceRunner 구현을 갖고 있지 않다(GPU와 O11이 필요, CR-D10). 호출 형태(factory() -> 객체, run(EvalJob) -> dict)는
게이트의 로그로 확인했다. 이 파일은 운영 구성에 들어가지 않는다."""


class TestRunner:
    def run(self, job):
        return {"evidence_ref": f"ev-test-{job.submission_id}", "metrics": {"test_metric": 1.0}, "unseen_question_eval": True}


def make():
    return TestRunner()
