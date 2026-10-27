# CR-D25: NOT_COMMITTED로 끝난 턴을 같은 turn_id로 재전송해도 계속 같은 실패 응답이 온다

- 상태: 제안 (영향: survey-service의 turn_id 멱등 처리)
- 확인(관찰): E2E 단계 5m(`bash scripts/e2e.sh --only 1,2,3,4,5m`, 이 PC)에서 model-serving을 `docker pause`한 동안 환자 턴(`turn_id` m-2)이 `200`과 `turn_failure_signal`(`write_committed: NOT_COMMITTED`, `staff_alert: NONE`)로 끝났다(값 미저장은 확인). model-serving을 `unpause`하고 healthy가 된 뒤 같은 `turn_id`로 20회(약 60초) 다시 보냈지만 매번 같은 `turn_failure_signal` 응답이었다. 같은 세션에 **새 turn_id**로 보내면 바로 확정됐다.
- 해석(추정): 서비스가 실패 응답을 turn_id의 저장된 결과로 취급해 되풀이하는 것으로 보인다. 확인하지 않았다(survey-service 코드는 읽지 않았다).
- 정책과의 차이: FAULT_POLICY 원칙 1·2는 "`NOT_COMMITTED`로 끝난 턴은 같은 `turn_id` 재전송이 안전하고, 확정되지 않은 턴은 다시 처리된다"고 한다. 키오스크는 같은 turn_id로 재시도하므로(원칙 7), 이 동작이면 모델 서버가 잠시 멈춘 뒤 복구돼도 그 턴은 영영 확정되지 않고 직원 호출 화면으로 간다.
- 비교: PostgreSQL 중지 중 실패(503 UNAVAILABLE)와 gateway 단계 실패(5q, 5w)는 같은 turn_id 재전송이 확정된다. 문제는 서비스가 턴을 처리하다 모델 단계에서 실패해 `turn_failure_signal`을 응답한 경우에 한한다.
- 요청(survey-service): `write_committed: NOT_COMMITTED`로 끝난 턴의 turn_id는 결과를 저장하지 않고 재전송을 새로 처리한다(또는 같은 turn_id가 재시도 가능함을 정책 문서에 명시하고 그 근거를 알려 준다). deploy는 5m의 정책 단언이 이 변경을 기다린다(통과하면 자동으로 REAL로 바뀐다).
