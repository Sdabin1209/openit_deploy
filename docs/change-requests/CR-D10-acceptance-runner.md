# CR-D10: release-gate에 승인 평가 실행기(AcceptanceRunner) 구현이 없다

- 상태: 제안 (E2E 단계 4의 PASS를 막는 직접 원인이었고, deploy가 시험용 실행기로 우회해 TEST-SUB로 표시했다)
- 보내는 곳: deploy -> head (영향: release-gate)

## 확인한 것

- 정책(`gate_policy`)만으로는 PASS가 나지 않는다. 정책이 완전해도(`can_pass: true`) 판정의 `ACCEPTANCE_EVAL`은 gate-worker가 `GATE_RUNNER_FACTORY`로 받은 실행기를 불러 `{evidence_ref, metrics, unseen_question_eval}`을 내야 하는데, 이 리포지토리에는 구현이 없다(design.md 5절, STATUS). 실행기를 꽂지 않으면 접수가 `EVAL_REQUESTED`에서 멈춘다.
- 실행기의 호출 형태가 runbook에 없다. deploy는 시험용 모듈로 탐침을 꽂아 로그로 알아냈다: `GATE_RUNNER_FACTORY=모듈:함수`의 함수는 인자 없이 불리고 반환 객체의 `run(job)`이 `EvalJob(submission_id, subject, policy_version)`을 받는다. 이것을 문서화하지 않으면 다른 영역이 같은 시도를 해야 한다.
- runbook에 정책 JSON 형식도 없다(design.md에 필수 항목의 이름만 있다). deploy가 알아낸 최소 형식: `{"gate_policy_version", "o11_resolved": true, "required_checks": [CLINICAL_SAFETY, CONTRACT_COMPAT, ACCEPTANCE_EVAL], "checks": {"ACCEPTANCE_EVAL": {"thresholds": {"<지표>": {"min": 숫자}}}}}`. 시험용 정책은 `test/policy/test-gate-policy.json`.

## 요청

(1) 런북에 정책 JSON 형식과 실행기 인터페이스(팩토리 호출 형태, `EvalJob` 필드, 반환 키, 실패 시 동작)를 쓴다. (2) model-runtime FakeBackend와 turn-engine으로 도는 **시험용 실행기**를 이 리포지토리에 `test` 이름으로 제공해(운영 이미지에는 넣지 않거나 구별되게) deploy가 우회 모듈을 직접 갖지 않게 한다. (3) 운영 실행기(GPU)는 O11 이후.
