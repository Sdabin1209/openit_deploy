# 경계 문서: deploy

## 1. 소유하는 것

- 소유 저장소: 없음(브리프). 인프라 정의와 운영 스크립트를 소유한다: `compose.yaml`, `compose.registry.yaml`, `locks/`, `config/`, `scripts/`, 로컬 레지스트리의 내용.
- 제공: 배포 절차(적용, 롤백), 백업·복구 절차, E2E 실행 스크립트(`scripts/e2e.sh`, 헤드 전달본 E2E.md에 따라 deploy가 소유).
- 제공하지 않음: SDK, 계약 스키마(계약은 헤드 소유다). deploy는 계약을 **소비하는 쪽**이고 계약 스키마를 만들거나 복사해 두지 않는다(스키마 사본은 지웠다: wo-28). 소비하는 계약의 실제 목록은 2절 표다.

## 2. 소비하는 것

| 소비 | 방식 |
| --- | --- |
| 각 영역 이미지 | 영역 리포지토리 HEAD를 `git archive`로 꺼내 deploy가 빌드하고 digest를 잠근다(CI가 생기면 영역 CI가 digest를 제출, D24) |
| 영역의 환경 변수·포트·볼륨·헬스체크 | 아래 3절. 각 영역 boundary/runbook/Dockerfile이 출처 |
| boundary-contracts 태그 | `scripts/lib.sh`의 `DEPLOY_BC_TAG`(표 한 곳). `build-images.sh`가 그 태그의 소스를 `git archive`로 꺼내 영역 진입점에 `dependency_sources`로 주고 deploy venv에도 설치한다 |
| 계약 스키마: 빌드·게시 경계 (사용 중) | **BuildImageRequest/BuildImageResult**(`build-images.sh`: 영역 `scripts/build-image.sh`에 요청을 쓰고 결과를 검증), **ImageLabels**(이미지 라벨 검증의 유일한 검사기 `scripts/check_image_labels.py`, 게시·빌드·E2E가 같은 검사기를 부른다), **PublishRequest/PublishResult**(`publish-image.sh`의 마지막 줄 = PublishResult, 서비스 이름 enum은 `lib.sh` `SERVICES`와 `scripts/test_services_enum.py`가 **일치를 강제**한다), **SetupEnvReport**(영역 `setup-env.sh`의 마지막 줄: `prepare-areas.sh`가 검증해 `state/setup-env/`에 모으고 doctor·check-all·verify-area가 읽는다), **JobsDeclaration**·**SyntheticJobError**·**BoundaryError**(`scripts/sd_jobs.py`: 라벨 `io.openit.jobs`로 잡을 돌리고 종료 코드 2·3·75의 stderr를 읽는다), **Exposure**(`check_exposure.py`: 라벨 `io.openit.exposure`와 Caddyfile 대조) |
| 계약 스키마: 설정·환경 (사용 중) | `test_config_contracts.py`(self-checks.list): **OpsFeedbackJobConfig**(ops-feedback 잡 설정 2개), **SurveyServiceEnv**·**OpsFeedbackServerEnv**(compose 병합 환경), **SurveyRiskRulesFile**(E2E 시험 위험 규칙 `test/risk-rules.e2e.json`), **SyntheticJobConfigRun/Import**(잡 설정, E2E가 라벨의 스키마 이름으로 검증) |
| 계약 스키마: E2E 검증 (사용 중) | `scripts/e2e_steps.py`가 단계 1~8의 모든 경계 값을 계약 validator로 검사한다(ReleaseManifest, ModelPackageManifest, DatasetManifest, GateSubmission/Decision/Approval, ApprovalRequest, ReviewReport, ActivePointer, Rollback*, ExtractRequest, ActionExtraction(Input), QuestionFieldSpec, StaffAlertPage, SessionState, FailureCase, IngestResult, TraceEnvelope 등), `boundary_contracts.clients`·`metrics`·`canonical` |
| 근거(코드에서 센 값) | `scripts/`·`test/`·`config/`의 `.py`·`.sh`·`.list`에서 계약 스키마 이름을 따옴표 문자열로 부르는 곳을 세었다(2026-10-30, wo-315 기준): 운영·E2E 코드(시험 파일 제외)에서 **스키마 35종 80곳**(e2e_steps.py가 대부분, build-images.sh·sd_jobs.py·setup_env_report.py·check_exposure.py 등), 시험 파일에서만 부르는 것은 ImageLabels·PublishRequest/Result·SurveyServiceEnv·OpsFeedbackServerEnv·OpsFeedbackJobConfig·SyntheticJobConfigImport. ImageLabels는 `check_image_labels.py`가 스키마 파일을 패키지에서 읽어(이름을 부르지 않고) 검증한다. 같은 세기로 다시 확인하려면 `git grep -nE "[\"']<스키마 이름>[\"']" -- scripts test config` |
| link 태그 (통신 기반 라이브러리, D118) | `scripts/lib.sh`의 `DEPLOY_LINK_TAG`(표 한 곳). deploy 의 Python 이 이웃을 부르는 곳(`link_*` 컴포넌트, E2E)이 `openit_link.clients` 로만 부른다. 호스트 설치는 `prepare-host.sh venv`. 영역 잠금 파일 대조(ADR 0046, `scripts/check_link_pins.py`) |
| 문진 스키마 | E2E의 QuestionBank·SessionResult 등 검증(`openit-survey-schema` wheel, 태그는 `lib.sh`의 `DEPLOY_SS_TAG`) |

## 3. 서비스 9개와 잡 2개(아래 표는 영역 서비스 5개, 그 뒤에 model-serving·게이트웨이·정적 화면 2개): 환경 변수, 포트, 볼륨, 헬스체크

출처는 각 영역 런북·Dockerfile이고 확인은 Compose에서 실제로 띄운 것이다. 영역 서비스는 모두 컨테이너 포트 8080, uid 10001, `/healthz`·`/readyz`, 라벨 `io.openit.*` 6개(키 목록은 루트 CLAUDE.md). 게이트웨이(Caddy)는 8080을 열고 `/healthz`를 점검한다(compose의 healthcheck).

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

정적 화면 2개(compose.yaml 확인): `kiosk-frontend`(키오스크 앱 + 직원 콘솔, 네트워크 edge, digest `KIOSK_FRONTEND_DIGEST`)와 `admin-console`(출고 승인 화면, edge, `ADMIN_CONSOLE_DIGEST`, `ADMIN_DEV_APPROVER_ID`는 설정하지 않음). 둘 다 포트 8080에 `/healthz`·`/readyz`를 두고 `/v1`은 처리하지 않으며, 게이트웨이가 경로로 나눠 전달한다. 게이트웨이는 `edge`·`serving` 네트워크에 걸쳐 있고 위 화면 둘과 survey-service, release-gate(승인 경로 네 개), ops-feedback-ingest가 healthy여야 뜬다.

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
| systemd timer 중단 | 주기 잡이 서지 않는다 | `systemctl start openit-*.timer` (재개 뒤 `OnBootSec`/`OnUnitActiveSec`으로 이어진다) |
