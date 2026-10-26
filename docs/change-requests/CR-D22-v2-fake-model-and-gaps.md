# CR-D22: 계약 2.0.0 구조에서 E2E가 부딪힌 점 (model-runtime fake 출력, synthetic-data, survey-service 시험 입력원)

- 갱신(model-runtime v0.6.2): 1항과 4항은 v0.6.2에서 해소되어 deploy의 대응(fake_server.py, apply_system_prompts.py)을 지웠다. 아래는 당시 기록이다.
- 상태: 제안 (헤드에게). deploy는 아래 대응을 시험 자료 쪽에서 했고 다른 영역은 고치지 않았다.

## 1. model-runtime v0.6.1: fake 백엔드의 고정 출력이 v2 흐름에서 모든 턴을 반려시킨다 (확인함)

- 확인: fake의 A 고정 출력은 `{"action":"NEXT","next_item":"END","values":[]}`다. survey-service(846dc79)는 첫 문항(`Q1.D01`)에서도 이 출력을 받으면 turn-engine `validate_extraction`이 `next_item`이 문항 순서·건너뛰기 규칙과 다르다고 반려해(단계 `VALIDATE`) 모든 발화 턴이 실패 신호가 된다. 서버 로그와 survey-service 로그(`턴 단계 실패 ... step=VALIDATE`)로 확인했다. 계약 문서(HTTP.md I9)는 서버가 "항상 ActionExtraction 스키마를 통과하는 값"을 낸다고만 하므로 형식은 지키지만 의미 검증은 통과하지 못한다.
- deploy의 대응(시험 전용): `test/fake-model/fake_server.py`가 model-runtime 서버를 그대로 import해 실행하고 `FakeBackend`의 기본 응답 함수만 바꾼다(입력의 `question_id` 다음 문항으로 가는 `NEXT`, `values` 비어 있음; B는 `(가짜 응답)`). `test/compose.fake-model.yaml`로만 붙고 운영 구성·실제 LLM 모드에는 없다. 문항 순서는 시험용 사본이라 survey-service의 `question_flow`가 바뀌면 E2E가 실패해 알려 준다.
- 요청(model-runtime): fake 백엔드가 입력 문항 기준으로 의미 검증을 통과하는 출력을 내거나(예: `MODEL_RUNTIME_FAKE_NEXT_ORDER` 같은 시험 설정으로 문항 순서를 받는다), 출력을 환경 변수로 줄 수 있게 한다. 그러면 deploy의 대응을 지울 수 있다.

## 2. synthetic-data: 데이터셋이 게시되지 않는다 (OPEN_GAPS G02, 확인함)

- 확인: E2E 단계 2에서 run-once가 `NOTHING_TO_DO`로 끝난다(합성 샘플 전부가 v2 스키마 위반으로 제외, 시드만 남는 설정이 아니어서 빈 결과). 같은 입력으로 다시 돌려도 같다.
- deploy의 대응: 단계 2를 `BLOCKED`로 기록하고 이후 단계의 `lineage.dataset`에는 자리표시 참조(`0-test-sub`, TEST-SUB)를 쓴다. 단계 7(실패 사례 시드 인용)은 시드만으로 새 데이터셋 버전이 게시되어 통과한다.
- 요청(헤드/사용자): synthetic-data의 역할 결정(G02). 결정 전에는 E2E 단계 2의 학습·평가 데이터 확인(보지 못한 문항 평가 파일, 학습과 겹치지 않음)을 할 수 없다.

## 3. survey-service: 직원 알림 화면 시험용 입력원이 이미지에 없다 (OPEN_GAPS G01)

- 확인: 시험용 입력원은 survey-service 리포의 `tests/smoke_fakes.py`에만 있고 이미지에 없다(스모크가 `tests/`를 읽기 전용으로 붙인다).
- deploy의 대응: E2E 5d에서 알림이 *나오지 않는 것*과 `/readyz`의 `staff_alert_source.active=false`를 REAL로 확인하고, 직원 콘솔 알림 화면 시험(알림 OPEN, SSE, RESUME/END)은 `SKIPPED`로 기록한다. 다른 영역의 시험 코드를 시험 구성에 끌어오지 않았다.
- 요청(survey-service, 선택): 입력원이 정해지면(G01) 시험용 대역을 이미지에 넣지 않고도 켤 수 있는 방법(예: 시험 전용 팩토리 위치를 설정으로 받되 운영 설정에 두지 않는다)을 알려 달라.

## 4. 이웃 코드 의존 없이 만든 모델 패키지

- model-runtime v0.6.1 `make_neutral_package.py`는 시스템 프롬프트를 인자로 받지 않는다(자리표시 문장을 쓴다). deploy는 생성 뒤 `scripts/apply_system_prompts.py`로 프롬프트 파일을 바꾸고 해시를 다시 계산한다. 요청(model-runtime, 선택): `--system-prompt-a/-b` 인자.
- E2E의 시험용 어댑터 패키지는 model-lab 패키징 코드를 실행하지 않고 deploy가 계약(`ModelPackageManifest.system_prompt`)대로 만든다(이웃 코드를 가져오지 않는 규칙).
