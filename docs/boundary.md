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

## 3. 서비스 6개(표는 5개 + 아래 model-serving): 환경 변수, 포트, 볼륨, 헬스체크

출처는 각 영역 런북·Dockerfile이고 확인은 Compose에서 실제로 띄운 것이다. 모두 컨테이너 포트 8080, uid 10001, `/healthz`·`/readyz`, 라벨 `io.openit.*` 6개.

| | survey-service | question-authoring | ops-feedback (ingest-api) | release-gate (gate-service) | model-registry (model-lab 소스) |
| --- | --- | --- | --- | --- | --- |
| digest 변수 | `SURVEY_SERVICE_DIGEST` | `QUESTION_AUTHORING_DIGEST` | `OPS_FEEDBACK_DIGEST` | `RELEASE_GATE_DIGEST` | `MODEL_REGISTRY_DIGEST` |
| 필수 환경 | `SURVEY_RELEASE_READER=http`, `SURVEY_TRACE_INGEST=http`, `SURVEY_MODEL_BACKEND=fake`; URL `*_URL`, 토큰 변수 이름 `*_TOKEN_ENV`; 공개 API `SURVEY_API_TOKEN`(없으면 시작 안 함), `SURVEY_STAFF_API_TOKEN` | `QA_AUTHOR_TOKENS`, `QA_READ_TOKENS` | `OPS_INGEST_TOKEN`; I7 읽기: `OPS_FAILURE_DB`+`OPS_READ_TOKENS` | `GATE_READ_TOKENS`, `GATE_WRITE_TOKENS`(역할에 release-approver 포함); `GATE_I1_FACTORY`/`GATE_I3_FACTORY`+`GATE_I1_URL/TOKEN`, `GATE_I3_URL/TOKEN`; 정책 파일은 선택(기본 정책) | `MODEL_REGISTRY_READ_TOKENS`, `MODEL_REGISTRY_WRITE_TOKENS`(역할 model-lab만) |
| 볼륨(`/data`) | `survey-data`: sessions.db, outbox.db, releases/ | `qa-data`: questions.sqlite3 | `ops-data`: log.db, failures.db (잡과 공유) | `gate-data`: registry.sqlite3 + releases/ (수집 잡·워커와 공유) | `models-data`: 파일 레지스트리 |
| 네트워크 | edge, serving | authoring, release | serving, logs, authoring | serving, release | release |
| 이미지 HEALTHCHECK | 있음 | 있음 | 있음 | 있음(서비스용; 워커는 끈다) | 있음 |
| 쓰기 토큰 소유 | — | 저자 | 수집(survey) | 역할 5개 | model-lab |
| 확인 | healthy, 활성 릴리스 전 `/readyz` 503 `no_active_release`, 적재 후 200 | healthy, I1 읽기 면 | healthy, 수집·I7 읽기 | healthy, `can_pass:false`(운영), 시험용 정책으로 true | healthy, 게시·조회 |

model-serving(model-runtime CPU/fake 변형): 포트 8080, uid 10001, `/healthz`·`/readyz`; 환경 `MODEL_RUNTIME_BACKEND`(fake), 문진 스키마는 이미지에 내장(`/opt/survey-schema`, D72; 마운트·`MODEL_RUNTIME_SCHEMA_DIR` 불필요), `MODEL_RUNTIME_RELEASE_URL`/`_TOKEN`(게이트 I4 읽기), `MODEL_RUNTIME_TOKENS`, 번들 캐시 기본 경로 `/var/lib/model-runtime/bundles`(볼륨 `serving-data`); 네트워크 serving. GPU 변형(VARIANT=gpu)은 GPU 서버 전용이라 이 Compose에 없다.

주기 잡: `job-ops-feedback`(`python -m ops_feedback.job --config`, `OPS_DEID_SALT`), `job-release-gate-collect`(`python -m release_gate collect`). GPU 서버 몫(Compose에 없음): model-lab `run-once`, release-gate `gate-worker`(승인 평가), synthetic-data의 LLM 생성. synthetic-data의 규칙 기반 run-once는 CPU만 쓰므로 어디서든 돌 수 있다(E2E는 호스트).

### 어긋나는 곳

첫 구간의 CR-D01..D08은 `docs/change-requests/CR-D14-status-of-previous.md`에 현재 상태를 정리했다. 출고 승인 화면(admin-console)의 게이트웨이 경로와 토큰 어긋남: CR-D19. D53 반영: CR-D16. 셋째 구간 상태: CR-D15. 이전 구간의 새 어긋남: CR-D10(승인 평가 실행기 구현 없음, 정책·실행기 형식 문서 없음), CR-D11(검토 게시 HTTP 면 없음), CR-D12(model-lab 파일 저장소 팩토리·GPU 접근 경로), CR-D13(수집기가 패키지 role을 구분하는지).

## 4. 이 영역이 이웃에게 지키는 것

- 이미지는 잠금 파일의 digest로만 뜬다. 이미지 안의 코드를 바꾸지 않는다.
- 릴리스 활성 포인터를 바꾸지 않는다(게이트 API를 호출하지 않는다. E2E의 롤백 요청은 시험 프로젝트에서 ops-feedback 토큰으로 한 시험이다).
- 비밀 값은 `secrets/`(gitignore)에만 있다. 서비스는 자기 secrets 파일만 `/run/secrets`로 받고 `NAME_FILE` 경로로 읽는다(D84). 토큰을 환경 변수로 넣지 않는다.
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
