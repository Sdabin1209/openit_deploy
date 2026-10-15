# CR-D01: 영역 사이 원격 클라이언트(SDK)가 소비 이미지에 들어갈 방법이 없다

- 상태: 제안(헤드 결정 필요)
- 보내는 곳: deploy -> head (영향: survey-service, release-gate, ops-feedback, question-authoring)
- 근거: 확인한 것(E2E 단계 4b, 5, 6b가 이 때문에 막힘)

## 확인한 것

| 소비자 | 필요한 것 | 지금 상태(각 영역 boundary/runbook 기준) |
| --- | --- | --- |
| survey-service | `SURVEY_RELEASE_READER`(I4 구현의 `모듈:함수`), `SURVEY_TRACE_INGEST`(I6) 필수. 없으면 종료 코드 2 | 팩토리를 담은 패키지가 survey 이미지에 없다. release-gate의 `open_release_reader(data_dir)`는 SQLite 읽기 전용 연결이라 레지스트리 볼륨과 `release_gate` 패키지가 필요하다. ops-feedback의 `HttpTraceIngest`는 `ops_feedback` 패키지 안에 있어 survey 이미지에 없다 |
| release-gate | `GATE_I1_FACTORY`, `GATE_I3_FACTORY` (둘 다 있어야 판정·수집이 켜진다) | I1 구현은 question-authoring의 `SqliteQuestionStore`(SQLite 읽기)뿐이고 게이트 이미지에 없다. I3(model-lab)는 서비스 형태가 없다 |
| 게이트 HTTP 읽기 | I4 `load_bundle`(질문지·어댑터 묶음) | 게이트 HTTP 읽기 면은 `active-pointer`, `releases/<id>`, `decisions/<id>`뿐이다. 묶음 내려받기 면이 없다 |
| I7 읽기(synthetic-data, model-lab, question-authoring) | `FailureStore` 원격 읽기 | ops-feedback은 ingest HTTP만 있다. I7은 SQLite SDK |
| I1 읽기(synthetic-data, model-lab, release-gate) | `QuestionReader` 원격 읽기 | question-authoring HTTP는 저작 API뿐, 읽기 면 없음 |

그래서 deploy는 서비스를 띄우고 `/healthz`·`/readyz`까지는 확인했지만 서비스끼리 정해진 인터페이스로 만나게 하지 못했다. E2E는 호스트에서 각 서비스의 HTTP 면을 직접 호출했다.

## 요청

헤드가 한 가지를 정한다(제안은 A).

- A. 원격(HTTP) 구현을 모은 설치 가능한 클라이언트 패키지(예: I1, I3, I4, I6, I7의 `Http*` 구현 + 팩토리)를 Git 태그로 배포하고, 소비 이미지가 태그로 설치한다. 각 서비스는 이에 맞는 읽기 면(HTTP)을 낸다(게이트: 묶음 내려받기, 문항 저작: I1 읽기, 수집: I7 읽기). 토큰은 CONVENTIONS 9절대로 환경 변수.
- B. 읽기 전용 볼륨 공유로 SQLite를 직접 읽게 한다. 단 이웃 패키지가 이미지에 들어가야 하고(영역 리포지토리끼리 코드를 가져오지 않는 규칙과 부딪힌다), WAL 모드 DB는 읽기 전용 마운트에서 열리지 않을 수 있다(CR-D07). 권하지 않는다.

덧붙임: 클라이언트가 토큰을 받는 환경 변수 이름을 정해 알려 주면 deploy가 `secrets/`와 `compose.yaml`에 연결한다.
