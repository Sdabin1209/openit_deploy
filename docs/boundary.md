# 경계 문서: deploy

## 1. 소유하는 것

- 소유 저장소: 없음(브리프). 인프라 정의와 운영 스크립트를 소유한다: `compose.yaml`, `compose.registry.yaml`, `locks/`, `config/`, `scripts/`, 로컬 레지스트리의 내용.
- 제공: 배포 절차(적용, 롤백), 백업·복구 절차, E2E 실행 스크립트(`scripts/e2e.sh`, 헤드 전달본 E2E.md에 따라 deploy가 소유).
- 제공하지 않음: SDK, 계약. 이 영역은 계약을 소비하거나 생산하지 않는다.

## 2. 소비하는 것

| 소비 | 방식 |
| --- | --- |
| 각 영역 이미지 | 영역 리포지토리 HEAD를 `git archive`로 꺼내 deploy가 빌드하고 digest를 잠근다(CI가 생기면 영역 CI가 digest를 제출, D24) |
| 영역의 환경 변수·포트·볼륨·헬스체크 | 아래 3절. 각 영역 boundary/runbook/Dockerfile이 출처 |
| boundary-contracts | E2E의 검증기로만(`boundary_contracts.validator`, v1.1.0 태그 wheel). 이미지 안의 버전은 영역이 정한다 |
| 문진 스키마 | E2E의 QuestionBank 검증(`openit-survey-schema` wheel, 정수 버전 1) |

## 3. 서비스 4개: 환경 변수, 포트, 볼륨, 헬스체크

출처는 각 영역 문서와 Dockerfile이고 "확인"은 실제로 띄워 본 것이다. 모두 컨테이너 포트 8080, 사용자 uid 10001, `/healthz`(살아 있음)·`/readyz`(의존 준비됨).

| | survey-service | question-authoring | ops-feedback (ingest-api) | release-gate (gate-service) |
| --- | --- | --- | --- | --- |
| 이미지 digest 변수 | `SURVEY_SERVICE_DIGEST` | `QUESTION_AUTHORING_DIGEST` | `OPS_FEEDBACK_DIGEST` | `RELEASE_GATE_DIGEST` |
| 포트 변수 | `SURVEY_PORT`(8080) | `QA_PORT`(8080), `QA_HOST` | `OPS_PORT`(8080) | `PORT`(8080) |
| 필수 환경 변수 | `SURVEY_RELEASE_READER`, `SURVEY_TRACE_INGEST` (둘 다 I4/I6 구현의 `모듈:함수` 팩토리), `SURVEY_MODEL_BACKEND`(지금 `fake`만) | `QA_AUTHOR_TOKENS`(비밀; 없으면 모든 요청 403) | `OPS_INGEST_TOKEN`(비밀) | `GATE_READ_TOKEN`, `GATE_WRITE_TOKENS`(비밀, `역할=토큰,...`) |
| 선택·설정 | `SURVEY_STAFF_CONSOLE`, `SURVEY_RESULT_DISPATCHER`, `SURVEY_SESSION_DB`, `SURVEY_OUTBOX_DB`, `SURVEY_WORK_DIR`, `SURVEY_RELEASE_POLL_SECONDS`(5), `SURVEY_KEEP_RELEASES`(2), `SURVEY_EXPORT_*`, `SURVEY_OUTBOX_KEEP_SENT_HOURS`, `SURVEY_LOG_LEVEL` | `QA_DB_PATH`(/data/questions.sqlite3), `QA_SURVEY_SCHEMA`(이미지 안 /opt/survey-schema) | `OPS_LOG_DB`(/data/log.db) | `GATE_DATA_DIR`(/data), `GATE_SURVEY_SCHEMA_DIR`, `GATE_SUPPORTED_RUNTIME_CONTRACT_VERSION`(이미지 고정), `GATE_TURN_ENGINE_VERSION`, `GATE_MODEL_RUNTIME_VERSION`, `GATE_POLICY_FILE`, `GATE_I1_FACTORY`, `GATE_I3_FACTORY`, `GATE_WATCH_*`, `GATE_POLL_SECONDS`(60) |
| 볼륨 | `/data`: `sessions.db`, `outbox.db`, `releases/`(작업 폴더) | `/data`: `questions.sqlite3` | `/data`: `log.db` | `/data`: `registry.sqlite3` + `releases/` (쌍) |
| Compose 볼륨 | `survey-data` | `qa-data` | `ops-data` | `gate-data` |
| 이미지 HEALTHCHECK | 있음(/healthz) | **없음**(Compose가 지정) | 있음 | 있음 |
| 네트워크 | edge, serving | authoring, release | serving, logs | serving, release |
| 쓰기 토큰 소유 | — | 저자 토큰 | 수집 토큰(survey가 쓴다) | 역할별 5개 |
| 이미지 라벨 키 | `io.openit.*` | `openit.contract.*`, `openit.lib.*` | `io.openit.*` | `org.openit.*` |
| 경계 계약 태그 | v1.1.0 | v1.0.0 | v1.1.0 | v1.0.0 |
| 확인(Compose에서 이미지로 기동) | healthy, `/readyz` 200 (시험 대역 I4/I6로) | healthy, 등록→확인 흐름 | healthy, ACCEPTED/DUPLICATE | healthy, `can_pass:false`(정책 비어 있음) |

주기 잡·보조 프로세스: `ops-feedback`의 `python -m ops_feedback.job --config <파일>`(환경 `OPS_DEID_SALT`), release-gate의 `gate-worker`(환경 `GATE_RUNNER_FACTORY`, `GATE_WORKER_ID`, `GATE_POLL_SECONDS`; GPU 서버 몫이라 Compose에 없음).

### 어긋나는 곳 (모두 `docs/change-requests/`에 있다)

| 어긋남 | CR |
| --- | --- |
| survey-service의 필수 팩토리(I4, I6)와 gate의 `GATE_I1_FACTORY`·`I3_FACTORY`를 담은 패키지가 소비 이미지에 없다. 실제 서비스끼리 연결할 수 없다 | CR-D01 |
| 게이트 읽기 토큰이 하나뿐(영역마다 다른 읽기 토큰을 줄 수 없다), 수집기 run-once 부재, 게이트 버전 변수 | CR-D02 |
| question-authoring: 이미지 HEALTHCHECK 없음, `build/survey-schema`를 만드는 스크립트 없음, I1 원격(HTTP) 읽기 면 없음 | CR-D03 |
| synthetic-data, model-lab의 주기 잡 정보를 deploy가 모른다 | CR-D04 |
| ops-feedback 잡 설정 형식, 잡이 쓰는 볼륨·토큰 | CR-D05 |
| 이미지 라벨 키 이름 불일치, boundary-contracts 태그 불일치(v1.0.0 vs v1.1.0) | CR-D06 |
| 저장소가 모두 SQLite라 DB 계정 분리가 불가능, WAL과 읽기 전용 마운트 | CR-D07 |
| 모델 추론 서비스(GPU)의 위치와 survey의 실제 백엔드 | CR-D08 |

## 4. 이 영역이 이웃에게 지키는 것

- 이미지는 잠금 파일의 digest로만 뜬다. 이미지 안의 코드를 바꾸지 않는다.
- 릴리스 활성 포인터를 바꾸지 않는다(게이트 API를 호출하지 않는다. E2E의 롤백 요청은 시험 프로젝트에서 ops-feedback 토큰으로 한 시험이다).
- 비밀 값은 `secrets/`(gitignore)에만 있다. 서비스는 자기 `env_file`만 받는다.
- 이웃 리포지토리를 수정하지 않는다. 빌드는 `git archive` 사본에서 한다.
- 영역 주기 잡은 영역이 정한 `run-once` 성격의 명령을 그대로 실행한다. 스케줄러는 다른 영역을 깨우지 않고 정해진 주기에 그 영역의 잡만 실행한다(D39).

## 5. 이웃이 이 영역에 기대해서는 안 되는 것

- 공개 API 경로(O06 대기)와 TLS·도메인.
- 백업 주기·보관 기간·복구 시점(O16 미정). 설정이 없으면 백업은 거부한다.
- 서버 밖 감시의 실제 연동(자리만 있다).
- GPU 서버(model-lab, 승인 평가 워커, synthetic-data의 LLM 생성)의 운영. 이 Compose 밖(D40).

## 6. 장애 영향

| 상황 | 영향 | 복구 |
| --- | --- | --- |
| 서버 전체 중단 | 서비스 전체 중단(비보증, D10). 외부 감시가 담당에게 알린다(미정) | 서버 복구 후 `up.sh`(restart: unless-stopped) |
| gateway 중단 | 외부 입구만 막힌다. 서비스 사이 통신은 유지 | 재시작 |
| 로컬 레지스트리 중단 | 새 이미지 적용·롤백이 막힌다. 이미 떠 있는 컨테이너는 영향 없음 | 레지스트리 볼륨 복구 또는 재게시(`publish-images.sh`) |
| 잠금 파일 손상 | 적용 불가 | `locks/history/` 또는 git에서 복구 |
| 볼륨 손상 | 해당 저장소 서비스 영향 | `restore.sh`(백업이 있어야 한다. 설정 전에는 백업이 없다) |
| 스케줄러 중단 | 주기 잡이 서지 않는다(상태 파일로 재개) | `scheduler.py tick` 재개 |
