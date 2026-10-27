# 끝에서 끝까지 한 바퀴 (합격 시나리오)

> 헤드 전달본(2026-10-15). 이 시나리오를 한 번에 실행하는 스크립트는 deploy가 소유한다. 모델 단계(3)는 GPU 호스트가 필요하므로, 이 환경에서는 model-runtime의 가짜 백엔드와 시험용 어댑터 디렉터리로 단계를 대신하고 그 사실을 보고서에 표시한다(시험 자료는 이름에 test를 넣는다).

시스템이 모델 성능을 제외하고 완성되었는지 확인하는 기준이다(D38). 품질은 보지 않고 **각 단계가 다음 단계의 입력을 만들고 순환이 닫히는지**만 본다. 이 시나리오를 한 번에 실행하는 스크립트는 deploy가 소유하며, 각 단계의 시험 자료(작은 문항 자료, 작은 기반 모델, 짧은 학습 설정)는 시험용임을 이름에 표시한다. 시험 자료가 운영 설정으로 흘러들어가면 안 된다.

| # | 단계 | 담당 | 인터페이스 | 확인할 것 |
| --- | --- | --- | --- | --- |
| 1 | 저자가 문항 자료를 올리고 미리보기를 확인한다 | question-authoring | I1 | `QuestionBank` 버전, `ReviewRecord`(clinical_basis_approved), `ChangeClassification`, 원본 해시 출처 |
| 2 | 문항을 읽어 학습·평가 데이터를 만든다(보지 못한 문항 평가 포함) | synthetic-data | I1→I2 | `DatasetManifest`, 평가 시나리오가 학습과 겹치지 않음 |
| 3 | 설정 하나로 학습·평가·패키징·게시가 돈다 | model-lab | I2→I3 | `ModelPackageManifest`(어댑터 해시, 계보), 같은 설정과 시드로 재실행 시 같은 결과 |
| 4 | 후보 수집기가 새 조합을 찾아 판정하고, 통과하면 릴리스와 번들을 만든다 | release-gate | I1,I3→I4,I5 | `GateDecision`, `ReleaseManifest`, 번들 해시 검증 |
| 5 | 서비스가 새 포인터를 보고 새 세션부터 새 릴리스로 한 턴 이상을 처리한다 | survey-service | I4,I8,I9→I6 | 턴 처리, `TraceEnvelope` 전송, 재전송해도 중복 없음 |
| 6 | Trace를 수집·비식별해 실패 사례를 만든다(보지 못한 문항 발화를 일부러 넣어 유도) | ops-feedback | I6→I7 | `FailureCase`에 비식별 전 데이터 없음 |
| 7 | 실패 사례가 데이터 생성·학습·저작으로 돌아간다 | synthetic-data, model-lab, question-authoring | I7 | 새 데이터셋 버전이 실패 사례를 시드로 인용 |
| 8 | 롤백 요청이 활성 릴리스를 되돌린다 | ops-feedback→release-gate | I5 | `RollbackReceipt`, 서비스가 새 세션부터 이전 릴리스 사용 |
| 9 | 모든 서비스가 Compose에서 이미지로 뜨고 주기 잡이 스케줄러로 돈다 | deploy | — | `/healthz`, digest 잠금으로 코드 축 롤백 |

합격 조건: 1~9가 사람 손 없이 순서대로 실행되고, 모든 레코드가 계약 스키마와 해시 검증을 통과한다.

## 단계 5c: 정정(CORRECT) 흐름 (deploy 소유, 시나리오 5의 일부)

`scripts/e2e_steps.py`의 `5c`. 가짜 A(model-runtime 0.7.2)의 선택 항목 `corrections`를 `test/fake-model/question_flow.json`에 둔다: 발화에 `아까 말`이 있고 입력 `question_id`가 `Q1.D02`이면 `Q1.D01.diagnosed`를 `false`로 정정하는 `CORRECT`를 낸다(`Q1.D01.diagnosed`는 survey-service의 문진 스키마 `QuestionFlow`/시험 문항 세트에 있는 실제 칸 키다). 흐름: (1) 추론 서버를 직접 불러 `Q1.D02`에서는 `CORRECT`(값 `CORRECTION`), `Q1.D03`에서는 일반 `NEXT`임을 본다. (2) 서비스를 거쳐 `Q1.D01`에 "네 있어요"(저장) 뒤 "아까 말한 거 아니에요"를 보낸다. (3) 같은 발화를 `Q1.D01`에서 보낸 대조 세션은 정정이 아니다.

**정정이 처리됐다고 판단하는 신호.** 저장된 값을 읽는 환자용 공개 경로는 없지만, 직원 세션 조회 `GET /v1/staff/sessions/{id}`(게이트웨이 경유, 직원 계정, `StaffSessionView`, boundary-contracts `PUBLIC_API.md`의 직원 콘솔 절)가 읽기 전용으로 두 가지를 낸다: `turns[].action`(LoRA-A가 낸 절차, 이 턴이 `CORRECT`인지)과 `values[]`(저장된 칸의 `value`와 `status`, 정정된 적이 있으면 `CORRECTION`). 근거 문구는 survey-service `docs/change-requests/CR-013-staff-session-view-public-api.md`(PUBLIC_API.md가 채택)와 `docs/design.md`의 저장 규칙(ANSWERED·CORRECTION만 저장)이다. 단언: 정정 전 `Q1.D01.diagnosed=true`(ANSWERED), 정정 뒤 턴 기록 action이 `[NEXT, CORRECT]`, 값 `false`·`CORRECTION`, 세션 `IN_PROGRESS`, 턴 실패 신호 없음, Trace 전송 수 증가. 이 단계는 서비스가 `CORRECT`를 검증·저장·기록하는 데까지만 본다.

**못 보는 것.** 직원 조회는 값의 현재 상태만 주므로, 정정 전 값이 이력(`NEW_REVISION`)에 남았는지는 볼 수 없다. 다음에 어느 문항을 묻는지(`progress_record.current_question_id`)도 공개 조회에 없어, 정정 뒤 같은 문항을 다시 묻는지는 확인하지 못한다. 응답 문장은 가짜 B의 고정 문장이라 환자에게 나간 문장의 내용은 보지 않는다. 가짜 A의 규칙(키워드와 `at`)이 맞는지를 볼 뿐 모델이 실제 정정 표현을 알아듣는지는 보지 않는다. 단독 실행은 활성 릴리스를 만드는 단계가 필요하다: `bash scripts/e2e.sh --only 1,2,3,4,5c`.

## 단계 5p: PostgreSQL 컨테이너 재시작 (deploy 소유, 시나리오 9의 일부)

`scripts/e2e_steps.py`의 `5p`. question-authoring에 자료를 등록해 쓴 뒤 postgres 컨테이너를 `docker stop`하고, 서비스 `/readyz`가 200이 아닌 상태가 되는 것(`/healthz`는 200 유지)을 관찰해 단계 출력에 코드와 경과 시간을 남긴다. `docker start`로 다시 띄우면 모든 서비스 `/readyz`가 200으로 돌아오는지, 재시작 전후 데이터베이스 행 지문(`pg-fingerprint.sh`)이 같은지, 복구 뒤 새 쓰기가 되는지 본다. 단계 8 뒤에 돈다. 단독 실행: `bash scripts/e2e.sh --only 5p`(활성 릴리스가 없어 survey-service는 제외). survey-service까지 보려면 활성 릴리스를 만드는 단계를 함께 준다: `--only 1,2,3,4,5p`. `--only`는 전체 합격이 아니며 `E2E_RESULTS.md`에 기록하지 않는다. 관찰에서 나온 영역 요청: [CR-D23](change-requests/CR-D23-survey-readyz-db-outage.md).

## gateway(Caddy)의 상류 장애 응답과 /readyz (FAULT_POLICY 5·6, deploy 소유)

`config/Caddyfile`. Caddy v2.11.7(`locks/images.lock`의 digest 이미지, `caddy validate`는 `scripts/test-gateway-auth.sh`가 돌린다). 설정에 명시한 것: 상류 연결 2초(`dial_timeout`), 응답 헤더 대기(환자 API 9초: 서버 턴 총 마감 8초보다 길고 키오스크 대기 10초보다 짧게 / 직원·정적 화면 10초 / `/readyz` 2초), 재시도 없음(`lb_try_duration 0`). `handle_errors`가 Caddy의 502·503을 `503`, 504를 `504`로 바꾸고 둘 다 본문 `{"code":"UPSTREAM_UNAVAILABLE"}`, `Content-Type: application/json`, `Retry-After: 2`, `Cache-Control: no-store`를 준다. Caddy의 `{http.error.*}`를 쓰지 않으므로 본문에 상류 주소·오류 문구가 없다. gateway `/healthz`는 상류와 무관한 정적 200이고, `/readyz`는 survey-service `/readyz`를 프록시해 2xx면 `ok` 200, 아니면 서비스의 상태 코드와 `{"ready":false}`(서비스의 내부 문제 목록은 밖에 내지 않는다)를 준다.

**Caddy 기본 동작의 관찰(추정이 아니라 설정 없이 돌려 본 값, 이 PC, 같은 이미지, `docker stop`/`pause` 한 python 서버 앞에서).** 설정 없는 `reverse_proxy`: 이름 해석 실패 502(3.0초 뒤), 상류 컨테이너 중지 502(3.1초 뒤), 상류 무응답(pause)은 60초를 기다려도 응답이 없었다(시간 제한 없음, 호출자가 먼저 끊음). 위 설정을 단 같은 구성: 중지 503(2.0초 뒤), 무응답 504(응답 헤더 대기를 3초로 둔 시험에서 3.0초 뒤). 즉 기본 상태에서는 "연결 거부는 503, 시간 초과는 504"가 저절로 되지 않고 무응답에는 마감이 없어서 명시 설정이 필요하다.

## 단계 5q, 5w, 5p 확장: 장애 주입 (FAULT_POLICY, deploy 소유)

모두 `scripts/e2e_steps.py`. 단독 실행은 활성 릴리스가 필요해 `bash scripts/e2e.sh --only 1,2,3,4,5q,5w,5p`처럼 단계 1~4를 함께 준다(`--only`는 전체 합격이 아니고 정본에 기록하지 않는다). 상태 `POLICY-PENDING`은 실패가 아니다: FAULT_POLICY가 정한 기대인데 현재 영역 코드로는 통과하지 않는 정책 단언이며, 약화하지 않고 어떤 변경을 기다리는지와 지금 값을 단계 출력에 남긴다(통과하면 같은 줄이 REAL로 나온다).

- **5q**: survey-service `docker stop` 동안 gateway 경유 환자 턴이 `503 {"code":"UPSTREAM_UNAVAILABLE"}`(+`Retry-After`, JSON, 내부 주소 없음), gateway `/readyz` 비정상, `/healthz` 200. `docker start` 뒤 `/readyz` 200, 이전 값 보존, 상류에 닿지 못한 턴은 기록 없음, 같은 `turn_id` 재전송이 200으로 확정. 정책 단언: 재시작 뒤 이미 확정된 `turn_id` 재전송이 저장된 응답과 같고 한 번만 기록된다.
- **5w**: survey-service `docker pause`(연결은 되나 무응답) 동안 gateway 경유 환자 요청이 응답 헤더 마감(9초) 근처에서 `504 UPSTREAM_UNAVAILABLE`(단언 범위 8.0~10.5초), gateway `/readyz`는 2초대에 504, `/healthz` 200. `unpause` 뒤 복구. 관찰: 504를 받은 턴을 서비스가 `unpause` 뒤에 처리했는지(횟수 출력)와 같은 `turn_id` 재전송 뒤 발화 기록이 한 번인지(정책 단언).
- **5p 확장**(활성 릴리스가 있을 때): PostgreSQL 중지 중 환자 턴을 gateway 경유로 보내 실패 응답이 오는지(성공으로 답하면 FAIL), 값이 저장되지 않는지(부분 저장 없음), 복구 뒤 같은 `turn_id` 재전송이 확정되고 값이 한 번 저장되는지 본다. 정책 단언: 총 마감(8.5초 이내), 실패 응답에 `write_committed=NOT_COMMITTED` 표시, 재전송 뒤 발화 기록 한 번.
- 정정 신호로 쓰는 읽기 경로는 직원 세션 조회(`GET /v1/staff/sessions/{id}`)다(단계 5c와 같다). 이 조회는 survey-service 서버 상태를 읽을 뿐 gateway 경유 직원 계정으로 부르므로 survey-service가 멈춰 있는 동안은 부르지 않는다.
