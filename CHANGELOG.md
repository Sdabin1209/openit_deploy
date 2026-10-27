# 변경 이력

## 운영·E2E 구성을 PostgreSQL로, 위험 신호·결과 조회 E2E 단계, 백업 잡에 pg_dump (코드·구성만, 컨테이너 검증 전)
- 결정(사용자 지시, 표준): 운영 구성은 PostgreSQL, SQLite는 각 영역의 개발·시험 기본으로만 남긴다. 이유: 권한·백업·보존을 DB 한 곳에서 걸고 서버가 나뉘어도 같은 방식으로 동작한다.
- `compose.yaml`: survey-service(`SURVEY_DATABASE_URL_FILE`), question-authoring(`QA_DATABASE_URL_FILE`), ops-feedback 서버·잡(`OPS_LOG_/OPS_FAILURE_DATABASE_URL_FILE`), release-gate 서버·수집 잡(`GATE_DATABASE_URL_FILE`)을 `db` 네트워크에 붙이고 `db-*-dsn` 비밀을 마운트, 서버 서비스는 postgres healthy에 의존. `qa-data`, `ops-data` 볼륨과 `OPS_FAILURE_DB` 설정을 정리(`gate-data/releases`, `survey-data` 릴리스 작업 폴더는 유지). survey-service에 `SURVEY_RESULT_READER_TOKEN_FILE`, `SURVEY_RISK_SOURCE_TOKEN_FILE`. `gen-secrets.sh`가 `survey-result-reader`, `survey-risk-source`를 만든다. `compose.test.yaml`에도 `db` 네트워크.
- 게이트웨이: `/v1/sessions/*/risk-signals`, `/v1/results*`를 404로 먼저 닫는다(내부 면, 이유는 docs/RUN.md 4-1-1).
- E2E 새 단계 5r(REAL, 가짜 모델): 세션 시작(기기 토큰, subject_ref) -> 발화 -> 위험 신호(risk-source) -> 알림 목록 -> 직원 세션 조회 -> 개입 RESUME(resolved_by=staff-e2e) -> 결과 조회(result-reader, 발화 없음). 네트워크 단언: 서비스 4개는 postgres:5432에 닿고 model-registry는 못 닿으며 호스트에 게시 없음.
- 백업: `backup-all.sh`(파일 저장소 + `pg-backup.sh`)를 backup 잡으로, `pg-fingerprint.sh` 추가. E2E 백업·복구 단계가 gate-data/models-data와 PostgreSQL 5개 데이터베이스(`pg-data` 볼륨 삭제 후 `pg-restore.sh`)의 왕복을 본다. `backup.sh` 기본 저장소는 `gate-data`.
- 실행해 본 것: compose 해석(서비스별 네트워크·환경 변수·의존), Caddyfile `caddy validate`, 스크립트 구문, check-all. 실행하지 않은 것: 새 E2E 단계와 백업 단계 전체, PostgreSQL 지원 이미지.

## E2E·데모의 activate를 헤더 있는 HTTP 호출로 (release-gate D85 행위자 식별 반영)
- release-gate가 activate·rollback에서 본문의 `requested_by_role`을 버리고 역할은 쓰기 토큰, 행위자는 `X-Openit-User`로 정한다(사람 역할 토큰에 헤더가 없으면 401). `GATE_SERVICE_ROLES`에 operator를 넣는 우회는 하지 않았다(더 엄격한 쪽). 이유: 감사 기록의 행위자는 서버가 정하고, 시험도 운영과 같은 경로를 탄다.
- `e2e_steps.py`: `gate_ops`/`gate_activate`(urllib, 이웃 코드 import 없음)로 activate를 부른다. 새 단언: 헤더 없이 operator 토큰으로 activate하면 401이고 포인터가 안 바뀐다, 헤더가 있으면 통과하고 `GET /v1/active-pointer`의 `ext["release-gate"].requested_by`가 그 ID. `demo_up`·`demo_activate`·단계 4b·단계 8도 같은 호출. ops-feedback 자동 롤백은 서비스 역할이라 그대로.
- 새 release-gate 이미지로는 아직 돌려 보지 못했다(이 변경은 그쪽 push 전이고 E2E는 이전 이미지로 한 번만 돌렸다). 이전 이미지에서는 이 단언(401)이 실패한다.

## 게이트웨이 개별 계정·키오스크 기기 인증, 스케줄러 주기, 잡 설정 파일 (D85)
- 결정(사용자 지시 D85, 표준): 직원·운영자는 개별 계정으로 인증하고 `X-Openit-User`로 행위자를 전한다. 이유: 감사 기록에 누가 했는지가 남고, OIDC로 바꿔도 같은 헤더 규칙을 쓴다. 키오스크는 기기 토큰으로 인증한다. 이유: 게이트웨이에 닿는 누구나 키오스크 API를 부르는 상태를 없애고 기기별로 폐기할 수 있다.
- `config/Caddyfile`: 인증 블록 `(authenticate)`와 `(role_matchers)`를 생성 파일로 분리(OIDC 교체 지점). staff/operator/release-approver/reviewer 역할 검사(403), 직원 개입 경로 포함. operator 계정만 여는 경로 넷(admin-console CR-004): `GET /v1/active-pointer`, `GET /v1/releases`(읽기 토큰 `gate-read-operator`)와 `POST /v1/activate`, `/v1/rollback`(쓰기 토큰 `gate-write-operator`), no-store. `gen-secrets.sh`가 release-gate 읽기 목록에 역할 operator를 더함. 키오스크 경로는 `@device_ok` 기기 토큰 대조 후 서비스 토큰으로 바꿔 붙이고 아니면 401, 클라이언트의 `X-Openit-User` 제거.
- `config/gateway-accounts.conf`(계정↔역할), `scripts/gateway-lib.sh`, `gen-secrets.sh`(계정 암호·해시 파일, 시험 기기 `e2e`), `scripts/kiosk-add-device.sh add|remove|list|sync [--apply]`, 자체 시험 `scripts/test-gateway-auth.sh`(e2e.sh가 실행). 예전 `staff-console-password` 등 공용 암호 파일과 `gateway-staff-auth/human-auth.caddy`는 쓰지 않는다(남아 있어도 된다).
- E2E(`e2e_steps.py`, `e2e.sh`)와 `demo.sh`: 키오스크 호출에 기기 토큰, 계정 이름 `staff-e2e`/`operator-e2e`/`trainer-e2e`/`reviewer-e2e`. 새 단언: 기기 토큰 없음·틀림·서비스 토큰은 401, 역할 밖 계정 403, 운영자 경로 인증 없이 401.
- `config/jobs.yaml`: release-gate-collector 600초, ops-feedback-job 3600초, backup 86400초(표준 주기). 이유: 새 조합은 10분 안에 후보가 되고, Trace 비식별은 시간 단위, 백업은 하루 단위가 표준이다.
- `config/ops-feedback-job.yaml`: root 소유 빈 디렉터리(Docker가 파일이 없을 때 만든 것)를 지우고 실제 파일로 둠. `rollback`, `retention.raw_days`는 사용자 결정 전이라 `null`.
- check-all 규칙 11: compose 바인드 마운트 원본(확장자 있는 파일)이 실제 파일이 아니면 FAIL(재발 방지). 자체 시험 포함.


## PostgreSQL 기반: 서버 하나, 서비스마다 데이터베이스·최소 권한 계정 (서비스 설정은 아직 그대로)
- 결정(사용자 지시: 빈 곳은 표준적인 방법): 영역별 SQLite 파일 대신 공식 `postgres:16` 서버 하나. 서비스마다 데이터베이스와 계정을 나눈다. 소유 서비스만 쓰고 이웃은 HTTP로만 읽는 규칙(D49·D50)은 그대로다.
  - 이유 1: 권한·암호화·백업·보존을 DB 계층 한 곳에서 걸 수 있다.
  - 이유 2: 서버가 여러 대로 나뉘어도 같은 방식으로 동작한다(접속 문자열만 바뀐다).
- `compose.yaml` `postgres`: 볼륨 `pg-data`, 호스트 포트 없음(internal 네트워크 `db`), 비루트(999), 읽기 전용 루트, `pg_isready` healthcheck, `POSTGRES_PASSWORD_FILE`(D84, 평문 환경 변수 없음), `--data-checksums`. 이미지는 `locks/images.lock`의 `POSTGRES_IMAGE`(digest 고정, `lock-third-party.sh`가 기록).
- `config/postgres/initdb/10-roles.sh`: 공식 `/docker-entrypoint-initdb.d`. 멱등. 계정 `survey qa ops_log ops_failure gate`, 각 계정은 자기 데이터베이스만 접속, 슈퍼유저 권한 없음, 루프백 TCP의 trust 제거.
- `gen-secrets.sh`: 계정 암호 파일(`db-<이름>-password`)과 DSN 파일(`db-<이름>-dsn`), `postgres-password`. `--db-only` 옵션. 이름 규칙 표는 `docs/RUN.md` 4-1-1.
- `pg-backup.sh`, `pg-restore.sh`, `pg-roles.sh sync`, `dev-postgres.sh up|down`(영역 개발용, 포트는 Docker가 배정, 암호는 일회용), 자체 시험 `test-postgres.sh`.
- `record-e2e.sh`: 환경 칸이 gpu-dev도 '이 PC (WSL2)'로 적던 버그를 고쳤다. `DEPLOY_ENV_NAME`이 있으면 그것, 없으면 hostname으로 식별(`gpu-dev*`만 gpu-dev, 원문 hostname은 기록하지 않음). 자체 시험은 `test-check-all.sh`.
- 이 단계에서 하지 않은 것: 서비스 컨테이너 설정 변경, `e2e.sh` 백업 단계에 Postgres 넣기, TLS, 디스크 암호화·WAL 보관 정책.

## demo.sh swap-adapters, 추론 서버 측정 도구 probe-serving.py (OPEN_GAPS U08)
- `demo.sh swap-adapters [--adapter-a/-b DIR --prompt-a/-b FILE]`: 떠 있는 데모에서 새 모델 패키지를 게시, 자동 검사, 시험용 승인자(스크립트) 승인, 활성화해 model-serving만 새 번들을 적재시킨다. 어댑터 인자는 `up --llm`과 같은 사전 검사를 거치고 거부되면 아무것도 게시하지 않는다. 전후 컨테이너 StartedAt(Env는 읽지 않음)과 새 release_id의 LOADED를 출력한다. 이전에는 `reset`(데모 전체 재생성)뿐이었다.
- `scripts/e2e_steps.py`: 단계 3의 게시·재확인을 `publish_packages()`로 뽑아 단계 3과 새 단계 `demo_swap`이 같이 쓴다(`demo_active`는 활성 포인터 읽기). 두 단계는 demo 전용이라 E2E 기본 실행에 들어가지 않는다. 단계 3의 동작은 같고, 어댑터 열기 위치만 패키지 ID가 들어간 폴더로 바뀌었다.
- `scripts/probe-serving.py`(+ 자체 시험 `scripts/test_probe_serving.py`): model-serving extract에 입력 묶음을 보내 성공/OUTPUT_INVALID 건수, 위반 키워드별 빈도, 첫 호출 대 이후 중앙값 지연, X-Openit-Outcome 분포를 표로 낸다. 토큰은 파일에서 읽고 출력하지 않는다.
- 문서: `docs/RUN.md` 7-2-3, `docs/GPU_HOLE.md` H2(교체)·H4(측정)가 두 도구를 쓰도록 바꿨다.
- 확인하지 못한 것: `--llm`(vLLM) 데모에서의 교체, 실제 모델의 OUTPUT_INVALID 분포. 전체 E2E는 돌리지 않았다.

## E2E가 값 추출 경로를 지나가게 함 (model-runtime v0.7.1 가짜 A, OPEN_GAPS U16)
- `test/fake-model/question_flow.json`을 객체 형식(`order`, `slots`, `skips`)으로 확장: 순서·건너뛰기 7규칙은 survey-service `schema/data/question_flow.json`, 칸 키·타입은 같은 스키마의 키 이름과 boundary-contracts `V2_DRAFT.md`의 값 형태에서 가져왔다(Q1.D*/Q2.D*/Q4~Q6/Q7 bool, Q8_1/Q9_1/Q10 `days` 정수. 문자열 칸 문항은 칸 정의 없음).
- E2E 단계 5g: 가짜 A 직접 호출 6건(값·타입·건너뛰기), 서비스 경유 값 있는 3턴(실패 신호 없음, 추론 실패·형식 위반 증가 0, Trace 전송). 단계 5s: 포인터 1->2 전후 survey-service·release-gate·model-registry·ops-feedback-ingest·question-authoring·gateway의 컨테이너 ID·StartedAt 불변, model-serving 새 릴리스 LOADED.
- 단언은 `scripts/e2e_asserts.py`, 자체 시험 `scripts/test_e2e_asserts.py`(틀린 값이면 실패함을 확인, e2e.sh가 실행).
- 한계: 저장된 값을 돌려주는 공개 읽기 경로가 없어 저장 값 자체는 단언하지 않는다. 가짜 A는 CORRECT를 내지 않아 정정은 시험하지 않는다.

## GPU 구멍 준비: 진짜 어댑터 얹기, 데모 비밀 점검, 위치 독립 시험 수정
- `docs/GPU_HOLE.md`: GPU 서버가 열릴 때 따라 할 순서(H1~H4, 명령·합격 기준·진단·OPEN_GAPS에 적을 항목).
- `demo.sh up --llm --adapter-a/-b DIR --prompt-a/-b FILE`: `make-llm-package.sh`가 `llm_attach_package.py`로 진짜 어댑터 패키지를 만든다. 기반 모델 불일치·순위 초과·파일 누락은 이미지 빌드 전에 거부(`--check-only`). `demo.sh config --llm`도 같은 검사.
- 비밀 점검: `check-secrets-hidden.sh`가 인자 없이 부르면 데모(`state/demo`)도 점검하고 `--secrets-dir`를 받는다. `demo.sh check-secrets` 추가, `demo.sh up` 끝에서 자동 실행(실패하면 종료 코드 비0).
- `test-inference-location.sh`: 별도 추론 서버에 시험용 fake 문항 순서 파일(`test/compose.fake-model.yaml`)을 붙였다(없어서 단계 5가 VALIDATE에서 실패했다).

## 비밀 파일화(D84)와 태그 정렬: boundary-contracts v2.0.2, turn-engine v0.4.0, model-runtime v0.7.0
- 태그 표(`lib.sh`)와 E2E·문서 표기를 새 태그로 맞췄다.
- 비밀: compose의 `env_file`로 토큰을 넣던 것을 없애고 최상위 `secrets:`(`secrets/tokens/<이름>`)를 `/run/secrets`에 마운트, 서비스는 `NAME_FILE` 경로만 받는다. `gen-secrets.sh`는 목록 값도 파일로 만든다(`secrets/<서비스>.env` 제거). 게이트웨이는 Caddy `{file./run/secrets/…}`. 외부 추론 서버의 토큰 파일과 `compose.inference.yaml`도 같은 방식(`INFERENCE_TOKENS_FILE`, `INFERENCE_RELEASE_TOKEN_FILE`).
- 새 점검: `scripts/check-secrets-hidden.sh`(E2E 단계), `scripts/check-versions.sh` + `scripts/test-check-versions.sh`(E2E 단계).

## model-runtime v0.6.2 채택 (브랜치 follow-mr-0.6.2)
- 기준 태그: model-runtime v0.6.2(`lib.sh`의 `DEPLOY_MR_TAG`; 이미지 라벨 기대값도 이 값).
- 우회 제거(CR-D22 v2 1·4항 해소): `test/fake-model/fake_server.py`(FakeBackend 응답 바꿔치기)와 `scripts/apply_system_prompts.py`를 지웠다. fake 모델은 표준 서버 + `MODEL_RUNTIME_BACKEND=fake` + `MODEL_RUNTIME_FAKE_FLOW_FILE=test/fake-model/question_flow.json`(survey-service `question_flow` 순서 사본, 31개). 중립 패키지는 `make_neutral_package.py --system-prompt-a/-b`.

## 2026-10-27 계약 2.0.0 구조로 이전 (브랜치 migrate-contracts-2.0.0)

- 기준 태그: boundary-contracts v2.0.0, model-runtime v0.6.1(prompt-4), turn-engine v0.3.0(`lib.sh`, `DEPLOY_TE_TAG`는 환경 변수로 내보내 E2E 매니페스트 lineage와 게이트 기준을 맞춘다). 이미지는 이웃 리포의 현재 main에서 빌드(방식 그대로).
- E2E v2 흐름: PUT 적재 -> extract(JSON) -> respond(text), 서버 직접 호출 검사(헤더·스키마·400·404·시스템 프롬프트 해시), 모델 패키지에 시스템 프롬프트(`ModelPackageManifest.system_prompt`), v2 문항 양식(ID 31개), v2 TurnTrace·FailureCase(LORA_A). 직원 알림은 입력원이 없음을 확인하고 알림 화면 시험은 건너뜀. fake 모델은 시험용 진입점(CR-D22; 0.6.2 채택으로 삭제됨).
- 실제 LLM 데모: `make-llm-package.sh`가 Qwen3-1.7B(`config.json` 고정 리비전 + sha256)와 데모 시스템 프롬프트(`test/llm-demo`)로 중립 패키지를 만든다. 서버 미검증.
- 지움: `test/compose.llm-demo.yaml`, `MODEL_RUNTIME_FAKE_RISK_PHRASE`(계약 2.0.0에서 없어짐).

## 2026-10-15 여섯째 구간

- model-runtime v0.5.1: init 제거, 기대값 기반 serving_config, 위험 정지 -> 직원 개입 E2E, CR-D18.

## 2026-10-15 다섯째 구간

- model-serving(추론 서버) 추가, survey가 I9로 호출, E2E 5단계가 추론 서버를 거침(중단·복구 포함), model-runtime v0.5.0·LangGraph survey 이미지, CR-D17.

## 2026-10-15 넷째 구간

- 사람 승인 출고(D53)·공개 API(D55)·계약 v1.3.1 반영, 시험용 정책·실행기 삭제, 게이트웨이가 `/v1/sessions` 전달, 승인자·키오스크·직원 토큰 추가, CR-D16.

## 2026-10-15 셋째 구간

- 검토 HTTP 면·개선 신호·게이트 운영 모드 거부·정책 스키마 검증을 E2E에 반영, 잠금 갱신, CR-D15.

## 2026-10-15 둘째 구간: 영역 사이 HTTP 연결(D49~D51)

- 서비스 5개(model-registry 추가), 모든 영역 사이 호출을 HTTP로 연결, 역할별 토큰(`gen-secrets.sh` 개편), 수집기 run-once 잡.
- E2E를 실제 서비스로 재작성(1~8단계), 시험용 정책·실행기·잡 설정 분리, 복구 검증을 HTTP로.
- 문서 갱신, 변경 요청 CR-D10..D14. 이미지 빌드(`build-images.sh`)가 model-lab 사본과 survey-service clone을 다룬다.

## 2026-10-15 첫 구성

- Compose(`compose.yaml`): gateway(Caddy)와 네 서비스. 이미지는 digest로만 참조, 네트워크 edge/serving/authoring/release/logs, 저장소별 볼륨, 읽기 전용 루트, cap_drop ALL, 비root.
- digest 잠금(`locks/images.lock`, `locks/history/`), `build-images.sh`(git archive 사본에서 빌드), `publish-images.sh`, `rollback.sh`, 로컬 레지스트리(`compose.registry.yaml`).
- 비밀 값: `scripts/gen-secrets.sh` -> `secrets/`(gitignore), `.env.example`.
- 백업·복구(`backup.sh`, `restore.sh`, `backup_tool.py`): 설정이 없으면 거부(O16 미정).
- 주기 잡 스케줄러(`scheduler.py`, `config/jobs.yaml`): 주기는 설정으로만, GPU 잡은 서버 밖.
- `scripts/e2e.sh`: 합격 시나리오 실행. 시험 대역은 `compose.test.yaml`, `test/fixtures/`로 분리.
- 문서: design, boundary, runbook, 변경 요청 CR-D01..D08.
