# 실행 안내 (서버에 띄워 화면을 눌러 보려는 사람용)

표기: **확인함** = 이 저장소의 스크립트·E2E로 실제 확인한 것. **문서 기준** = 영역의 설계 문서에서 읽은 설명이며 사람이 실제 화면을 눌러 확인한 것이 아니다. 시간은 측정한 것만 쓰고 나머지는 "측정 안 함"이라 쓴다.

## 1. 한눈에

| | 상시 구성 | 데모 | E2E |
| --- | --- | --- | --- |
| 목적 | 운영 형태 그대로 띄운다 | 사람이 화면을 눌러 본다 | 합격 시나리오 자동 검증 |
| 명령 | `up.sh deploy` (3절) | `demo.sh up` (4절) | `e2e.sh` / `e2e.sh --fast` |
| 프로젝트 | `deploy` | `deploy-demo` | 임시 이름, 끝나면 지움 |
| 활성 릴리스 | 없음 (503 `no_active_release`가 정상) | 있음 (시험용으로 만들어 활성화) | 단계 안에서 만들고 지움 |
| 가짜 모델 | 모델 백엔드는 지금 `fake`뿐 | 가짜 모델 + 시험용 승인자 + 위험 문구 스위치 | 가짜 모델 + 시험용 대역 |
| 데이터 지속 | 볼륨에 남는다 | `demo.sh down`이 `state/demo`와 함께 지운다 | 끝나면 모두 지운다(`--keep`이면 남김) |

## 2. 전제

[SETUP.md](SETUP.md)를 따라 설치하고 `bash scripts/doctor.sh`가 FAIL 없이 끝나야 한다(형제 폴더 배치, Docker 데몬, compose 포함). `up.sh`와 `demo.sh up`은 시작에서 doctor를 자동으로 돌린다.

## 3. 상시 구성 기동

먼저 알아 둘 것: **활성 릴리스가 없으면 survey-service `/readyz`가 503 `no_active_release`이고, 키오스크가 "직원을 불러 주세요"(직원 호출) 화면을 띄운다. 둘 다 정상이다.** 화면을 눌러 보려면 4절의 데모를 쓴다.

```
cd <루트>/deploy
bash scripts/registry.sh up        # 로컬 레지스트리 기동(주소를 state/registry.env 에 기록)
bash scripts/build-images.sh       # 8개 영역 이미지를 현재 HEAD 소스로 빌드
bash scripts/publish-images.sh     # 이미지를 레지스트리에 올리고 digest를 locks/images.lock 에 기록
bash scripts/gen-secrets.sh        # 토큰·계정 암호를 secrets/ 에 만든다(값은 출력 안 함)
bash scripts/up.sh deploy          # compose 기동, healthy 확인
```

| 명령 | 하는 일 | 걸리는 시간 |
| --- | --- | --- |
| registry.sh up | registry:2 컨테이너 기동 | 측정 안 함 |
| build-images.sh | 이미지 8개 빌드 | 측정 안 함 (첫 빌드는 의존 내려받기 때문에 더 걸린다) |
| publish-images.sh | push + digest 잠금 | 측정 안 함 |
| gen-secrets.sh | 비밀 파일 생성 | 측정 안 함 |
| up.sh | 기동·healthy 대기 | 측정 안 함 (E2E의 compose 기동·검사 구간은 약 67~68초: STATUS.md) |

- 레지스트리 기본 호스트 포트는 5000이다. 충돌하면 `REGISTRY_HOST_PORT= bash scripts/registry.sh up`처럼 빈 값을 주면 빈 포트를 고른다.
- gateway의 호스트 포트는 Docker가 배정한다. `bash scripts/status.sh`로 본다.
- 이미 만든 상태에서 다시 올릴 때는 이미지가 그대로면 빌드·게시를 건너뛰어도 된다. 소스를 바꿨다면 다시 빌드·게시한다.

## 4. 데모 (화면을 눌러 보기)

```
bash scripts/demo.sh up                          # 시험 구성 기동 + 시험용 릴리스 생성·활성화 + 접속 안내 출력
bash scripts/demo.sh up --stop-before-approval   # 승인 대기까지만. /admin/ 에서 직접 승인한 뒤 아래 activate
bash scripts/demo.sh activate                    # 승인된 릴리스를 활성화
bash scripts/demo.sh status                      # 컨테이너·주소·/readyz 요약
bash scripts/demo.sh down                        # deploy-demo 자원과 state/demo 제거
bash scripts/demo.sh reset                       # down 후 up
```

- 처음에는 이미지 빌드가 들어가 오래 걸릴 수 있다(측정 안 함). E2E 단계 1~8 구간은 약 45초(STATUS.md).
- **출력 읽는 법.** 끝에 "데모 접속 안내" 블록이 나온다: 주소(Docker가 배정한 포트), 화면별 경로(`/` 키오스크, `/staff/` 직원 콘솔, `/admin/` 승인·검토), 계정 이름, 암호 파일 위치, 위험 문구. 암호 값은 출력하지 않는다.
- **계정.** 직원 `staff-e2e`(역할 staff), 운영자 `operator-e2e`(operator), 승인자 `trainer-e2e`(release-approver), 검토자 `reviewer-e2e`(reviewer). 암호는 각각 `state/demo/secrets/tokens/account-<계정>-password` 파일에 있다(`cat`으로 연다). 키오스크 기기 토큰은 `tokens/kiosk-device-e2e`(4-1-2).
- **직원 알림.** 입력원이 비어 있어(OPEN_GAPS G01) 알림이 만들어지지 않는다. 위험 문구로 정지시키는 시험은 없다. survey-service `/readyz`의 `staff_alert_source.active`가 `false`로 드러내며 고장이 아니다.
- **가짜 모델.** 시험 구성의 model-serving은 표준 model-runtime 서버(v0.7.3)에 `MODEL_RUNTIME_BACKEND=fake`와 `MODEL_RUNTIME_FAKE_FLOW_FILE`(`test/fake-model/question_flow.json`, survey-service `question_flow`의 문항 순서 사본, 순서가 다르면 E2E가 실패한다)만 준 것이다: A는 입력 문항의 다음 문항으로 가는 유효한 ActionExtraction(`NEXT`)이고, 흐름 파일이 객체 형식이라 칸 정의(`slots`)가 있는 문항에서는 발화로 첫 칸의 ANSWERED 값(boolean: '아니' 포함 여부, integer: 첫 숫자 또는 '없'·'아니'면 0)을 내며 `skips`로 next_item을 정한다(칸 키·타입은 survey-service `schema/data/question_flow.json`의 순서·건너뛰기 7규칙과 boundary-contracts V2_DRAFT.md의 칸 형태에서 가져왔고 Q3와 Q4_1 등 문자열 칸 문항은 칸 정의가 없어 값 없이 NEXT). B는 `(가짜 응답)`. 모델 정확성은 시험하지 않는다. E2E 단계 5g(가짜 A 값 추출·건너뛰기 직접 확인, 서비스 경유 값 있는 3턴이 검증·저장을 통과)와 5s(포인터 1->2 전후 다른 서비스 컨테이너 StartedAt·ID 불변, 새 릴리스 LOADED)가 이를 단언한다. 저장된 값 자체를 돌려주는 읽기 경로는 없어 값 내용은 단언하지 않는다(OPEN_GAPS U16).
- 이 데이터는 **시험용 대체**다(가짜 모델, 시험용 어댑터·평가 보고서, 시험용 승인자 스크립트). 실제 모델·실제 승인이 아니다.

## 4-1. 비밀 파일 (D84)

**방식.** 토큰·salt는 환경 변수가 아니라 파일이다. `scripts/gen-secrets.sh`가 `secrets/tokens/<이름>`에 값 하나짜리 파일을 만든다(개별 토큰, 서버가 받는 목록 값 `역할=토큰,...`, salt, 콘솔 암호). `compose.yaml`의 최상위 `secrets:`가 서비스마다 필요한 것만 `/run/secrets/<이름>`에 읽기 전용으로 마운트하고, 서비스에는 `NAME_FILE=/run/secrets/<이름>` 환경 변수(경로, 비밀 아님)만 준다. 서비스 코드는 `boundary_contracts.read_secret(NAME)`으로 읽는다. 예전처럼 `env_file`로 토큰을 넣으면 `docker inspect`, `docker exec <c> env`로 평문이 읽힌다(근본 원인).

**권한.** 비밀 폴더 700. 파일은 두 종류다: 호스트에서만 쓰는 것(계정 암호·해시, 기기 토큰 원본, 컨테이너에 마운트하지 않는 클라이언트 토큰)은 **600**, 컨테이너가 읽는 것은 644(폴더 700 안). 어느 쪽인지는 `lib.sh`의 `secret_mode`가 `compose.yaml`의 secrets를 읽어 정하고 `scripts/check-secret-perms.sh`(doctor --up이 부른다)가 어긋남을 잡는다. 근거와 한계: [adr/0022-secret-file-permissions.md](adr/0022-secret-file-permissions.md). 컨테이너가 읽는 파일을 600으로 못 만드는 이유: 컨테이너가 uid 10001로 실행되는데 compose의 파일 secrets는 호스트의 소유자·모드를 그대로 마운트하고(`uid/gid/mode` 옵션은 swarm 전용) 호스트 소유자가 달라서, 600이면 서비스가 읽지 못한다. 폴더가 700이라 호스트의 다른 사용자는 파일에 닿지 못한다.

**게이트웨이(Caddy).** 환경 변수 대신 Caddy의 표준 파일 치환 `{file./run/secrets/<이름>}`을 Caddyfile에서 쓴다(`header_up Authorization "Bearer {file./run/secrets/survey-api-kiosk}"`). 이유: Caddy는 `NAME_FILE` 규칙을 모르고, `{$ENV}`는 환경 변수를 요구하며, 파일 치환은 Caddy가 공식으로 지원하는 방법이라 래퍼 스크립트나 이미지 수정이 필요 없다. 값은 컨테이너 환경에 없고, 끝의 줄바꿈은 Caddy가 지운다(`caddy` 컨테이너에서 확인).

**예외(문서화).** `NAME_FILE`을 모르는 서드파티 이미지에는 이 방식을 쓸 수 없다. 현재 비밀을 받는 서드파티 이미지는 없다: `registry:2`(compose.registry.yaml)는 인증·비밀이 없고(운영 인증은 미정, docs/ci.md), Caddy는 위 파일 치환을 쓴다. 새 서드파티 이미지가 비밀을 받아야 하면 그 이미지가 지원하는 파일 방식(예: `*_FILE`)을 쓰고, 지원하지 않으면 예외로 여기에 적는다.

**점검.** `bash scripts/check-secrets-hidden.sh [프로젝트]`: (정적) compose 병합 결과에 비밀 이름(`…TOKEN/TOKENS/SALT/PASSWORD/SECRET`)의 값이 직접 들어 있거나 `NAME_FILE` 경로가 서비스의 secrets 마운트와 어긋나면 실패, (동적) 떠 있는 프로젝트의 컨테이너마다 `docker inspect`(Env/Cmd/Entrypoint)와 `docker exec env`·`/proc/1/environ`에 secrets 파일의 값이 하나라도 있으면 실패한다. 값은 출력하지 않고 컨테이너·변수 이름만 낸다. `scripts/e2e.sh`가 단계로 호출한다.

**이미 secrets/가 있는 경우.** 예전 `secrets/*.env`는 더는 쓰지 않는다(지워도 된다; gen-secrets.sh가 알려 준다). `gen-secrets.sh`를 다시 실행하면 기존 토큰은 그대로 두고 목록 값 파일(`gate-read-tokens` 등)만 새로 만든다. 토큰 파일 모드는 644로 바뀐다. 클라이언트(E2E, demo.sh)는 같은 경로 `secrets/tokens/<이름>`을 읽는다.

## 4-1-1. PostgreSQL (서비스마다 데이터베이스·계정 분리)

**결정(사용자 지시: 빈 곳은 표준적인 방법).** 영역별 SQLite 파일 대신 **PostgreSQL 서버 하나(공식 이미지 `postgres:16`, digest는 `locks/images.lock`의 `POSTGRES_IMAGE`)**를 `compose.yaml`의 `postgres` 서비스로 둔다. 서비스마다 데이터베이스와 최소 권한 계정을 따로 만든다. 소유 서비스만 쓰고 이웃은 HTTP로만 읽는 규칙(D49·D50)은 그대로다: 계정은 자기 데이터베이스에만 접속할 수 있다. 이유: 권한·암호화·백업·보존을 DB 계층 한 곳에서 걸 수 있고, 서버가 여러 대로 나뉘어도 같은 방식으로 동작한다.

**상태.** 운영 구성(`compose.yaml`)과 데모·E2E 구성은 PostgreSQL을 쓴다. survey-service, question-authoring, ops-feedback(서버·잡), release-gate(서버·수집 잡)가 서비스마다 따로인 `db-survey`/`db-qa`/`db-ops`/`db-gate` 네트워크(internal)에 붙고(postgres는 넷 모두에 붙는다. 하나의 `db`로 합치면 postgres 클라이언트끼리 서로 닿는다), 아래 표의 `…_DATABASE_URL_FILE`로 DSN 비밀을 받고, postgres가 healthy가 되어야 뜬다. SQLite 경로 설정(`OPS_FAILURE_DB` 등)은 compose에서 뺐다(각 영역의 개발·시험 기본으로만 남는다). 남긴 볼륨: `survey-data`(릴리스 작업 폴더), `gate-data`(번들 파일 `releases/`), `models-data`(model-registry). `qa-data`, `ops-data`는 없앴다(`/data`는 읽기 전용 루트에서 쓰기 위한 tmpfs). **작성 시점에 각 서비스 이미지가 PostgreSQL을 지원하는지는 컨테이너로 확인하지 못했다**(영역 쪽 작업 중). model-registry는 파일 레지스트리라 데이터베이스가 없다.

**이름 규칙(확정).** 서비스는 `boundary_contracts.read_secret(<환경 변수 이름>)`으로 읽는다. compose는 `<환경 변수 이름>_FILE=/run/secrets/<비밀 이름>`만 준다. 값은 `postgresql://<계정>:<암호>@postgres:5432/<데이터베이스>` 한 줄이다.

| 영역(저장소) | 환경 변수 이름 | 비밀 이름(`secrets/tokens/…`, `/run/secrets/…`) | 데이터베이스 = 계정 | 담는 것 |
|---|---|---|---|---|
| survey-service | `SURVEY_DATABASE_URL` | `db-survey-dsn` | `survey` | 세션, outbox, 알림 |
| question-authoring | `QA_DATABASE_URL` | `db-qa-dsn` | `qa` | 문항 |
| ops-feedback | `OPS_LOG_DATABASE_URL` | `db-ops-log-dsn` | `ops_log` | 원본 Trace 로그 |
| ops-feedback | `OPS_FAILURE_DATABASE_URL` | `db-ops-failure-dsn` | `ops_failure` | 실패 사례 |
| release-gate | `GATE_DATABASE_URL` | `db-gate-dsn` | `gate` | 릴리스 레지스트리 |

암호 파일은 `db-<이름>-password`(이름의 `_`는 `-`), 슈퍼유저 암호는 `postgres-password`다. 암호 파일은 `postgres` 서비스만 마운트하고(초기화 스크립트가 읽는다), DSN 파일은 소유 서비스만 마운트한다. 호스트 이름 `postgres`는 compose의 서비스 이름이고 `db-*` 네트워크(internal, 호스트 포트 없음)에서만 닿는다. `gen-secrets.sh`가 위 파일을 만든다(모드 644, 폴더 700, 값은 출력하지 않는다). `bash scripts/gen-secrets.sh --db-only [폴더]`는 이 비밀만 만든다(caddy 이미지 불필요). 암호를 바꾸면 DSN도 다시 쓰이고, 이어 `bash scripts/pg-roles.sh sync`가 서버의 계정 암호를 바꾼다.

**초기화.** 공식 이미지의 `/docker-entrypoint-initdb.d`(`config/postgres/initdb/10-roles.sh`)가 빈 볼륨에서 한 번 돈다. 계정마다 `CREATE ROLE`(LOGIN, 슈퍼유저·DB생성·역할생성·복제 없음), 같은 이름의 데이터베이스(소유자 = 그 계정), `PUBLIC`의 CONNECT 회수(다른 계정의 데이터베이스와 `postgres`·`template1`에는 접속 불가), 루프백 TCP의 `trust`를 암호 요구(scram-sha-256)로 교체. 스크립트는 멱등이라 다시 돌려도 안전하다(`pg-roles.sh sync`). 계정 암호는 비밀 파일에서 `psql`의 `\set … \`cat\``로 읽어 인자·환경 변수·로그에 나오지 않는다. 암호 없이 닿는 길은 컨테이너 안 유닉스 소켓(`docker exec`)뿐이다.

**백업·복구.** `pg-data` 볼륨을 파일째 복사하지 않는다(쓰는 중에는 일관되지 않다).
- `bash scripts/pg-backup.sh [db ...]`: 설정·거부 규칙·보관 기간은 `backup.sh`와 같다(`config/backup.env`). 데이터베이스의 소유 계정으로 `pg_dump -Fc`(데이터베이스 안에서는 한 시점의 일관된 스냅샷, 서버가 떠 있어도 된다)해 `$BACKUP_DIR/pg-<db>/<UTC 시각>/<db>.dump.age`(또는 `.gpg`, 수신자 공개키로 암호화, 평문은 남기지 않음) + `MANIFEST.json`(평문 sha256, 크기, 서버 버전, 덤프 시작·끝 시각)을 만든다. 5개는 병렬로 동시에 시작하지만 데이터베이스 사이 같은 시점은 아니다(한계: runbook 4-2절). 파일 600, 폴더 700. 설정이 불완전하면 CRIT와 종료 코드 2. 복호 개인키는 서버에 없다: 복구 절차는 [runbook.md](runbook.md) 4-3절.
- `bash scripts/pg-restore.sh <db> <스냅샷 폴더> --yes`: 해시 검증(불일치면 종료 코드 3), 그 데이터베이스에 다른 접속이 있으면 거부(서비스를 먼저 멈춘다), 그다음 `pg_restore --clean --if-exists --single-transaction`. 볼륨을 잃었다면 `postgres`를 먼저 띄운다(초기화가 빈 데이터베이스와 계정을 만든다). 그다음 복구한다.
- `scripts/backup-all.sh`가 backup 잡이다: 파일 저장소(`backup.sh`, 기본 `gate-data` 번들)와 PostgreSQL(`pg-backup.sh`)을 같은 `config/backup.env`로 백업한다. `e2e.sh`의 백업·복구 단계는 파일 저장소 2개(gate-data, models-data)와 데이터베이스 5개를 백업해 `pg-data` 볼륨까지 지우고, 초기화로 되살린 빈 데이터베이스에 `pg-restore.sh`로 복구한 뒤 `pg-fingerprint.sh`(스키마+행 집합 해시, 행 순서 무관)가 같은지 본다. 서버 단독 자체 시험은 `bash scripts/test-postgres.sh`.

**영역 개발용 서버(`scripts/dev-postgres.sh`).** 영역 에이전트가 자기 시험에 쓰는 일회용 서버다. 개발은 컨테이너 밖에서 하므로 서비스는 호스트에서 접속한다.
```
export SURVEY_DATABASE_URL=$(bash <deploy>/scripts/dev-postgres.sh up survey)   # stdout 한 줄: postgresql://survey:<일회용 암호>@127.0.0.1:<Docker가 배정한 포트>/survey
bash <deploy>/scripts/dev-postgres.sh down survey                                  # 컨테이너와 임시 비밀 지우기
```
데이터베이스 이름은 위 표의 이름(`survey qa ops_log ops_failure gate`). 운영과 같은 초기화 스크립트를 쓰므로 권한도 같다. 데이터는 메모리(tmpfs)라 down하면 사라진다. 포트는 고정하지 않는다. 이미 떠 있으면 같은 문자열을 다시 낸다. 같은 데이터베이스를 여럿 띄우려면 `DEV_PG_SUFFIX=<구분>`. 컨테이너 이름은 `deploy-devpg-<db>[-<구분>]`, `dev-postgres.sh status`로 목록을 본다. 접속 문자열은 암호를 담으므로 로그·커밋에 남기지 않는다. 서비스 쪽은 환경 변수 `…_DATABASE_URL_FILE`(운영)과 `…_DATABASE_URL`(개발) 둘 다 `read_secret`으로 읽힌다.

**확인하지 못한 것.** TLS(서버 안 암호화)는 켜지 않았다(내부 네트워크 한정, 서버가 나뉘면 필요). 저장 시 디스크 암호화와 보존 기간 정책(PITR, WAL 보관)은 정하지 않았다(O16). 서비스가 실제로 붙는 경로는 영역 쪽 작업 뒤에 E2E로 본다.

## 4-1-2. 게이트웨이 인증: 개별 계정과 키오스크 기기 토큰 (D85)

**결정(사용자 지시 D85, boundary-contracts `PUBLIC_API.md` 추가 인터페이스 E·F절).** 표준: 직원·운영자는 개별 계정으로 인증하고 행위자를 서비스에 전한다. 키오스크는 기기 토큰으로 인증한다. 이유: 누가 했는지가 감사 기록에 남고(공용 암호로는 못 남긴다), 게이트웨이에 닿는 누구나 키오스크 API를 부르는 상태를 없애며, 기기 하나를 다른 기기에 영향 없이 폐기할 수 있다.

**계정과 역할(E절).** 계정 목록은 `config/gateway-accounts.conf`(`<계정> <역할[,역할]>`, 비밀 아님). 역할: `staff`(직원 콘솔 `/staff/`, `/v1/staff/*`, 개입), `operator`(릴리스 운영 화면의 `GET /v1/active-pointer`, `GET /v1/releases`, `POST /v1/activate`, `POST /v1/rollback`), `release-approver`(출고 승인 경로), `reviewer`(실패 사례 검토). `scripts/gen-secrets.sh`가 계정마다 `tokens/account-<계정>-password`(암호)와 `-hash`(bcrypt, caddy 이미지로 만듦)를 만들고 `secrets/gateway-accounts.caddy`를 쓴다. 기존 파일은 바꾸지 않는다(암호를 바꾸려면 두 파일을 지우고 다시 실행). 값은 출력하지 않는다. 역할이 맞지 않으면 403, 인증이 없으면 401.
- 게이트웨이는 인증된 계정 ID를 `X-Openit-User`로 붙인다(직원 API·개입, 운영자 경로, 승인·검토 경로). 클라이언트가 보낸 같은 이름의 헤더는 덮어쓰거나(인증 경로) 지운다(키오스크 경로). 서비스는 본문 값이 아니라 이 헤더를 행위자로 쓴다.
- 위 operator 경로 네 개는 operator 계정 뒤에서만 열린다(읽기 둘은 게이트의 operator 읽기 토큰 `gate-read-operator`, 변경 둘은 쓰기 토큰 `gate-write-operator`. 두 토큰은 gen-secrets가 만들어 release-gate 목록의 역할 `operator`에 넣는다). 응답은 `Cache-Control: no-store`. `/v1/releases/*`(번들, I9)와 그 밖의 `/v1/*`는 404. release-gate가 헤더로 행위자를 기록하게 바뀌는 일은 그쪽 영역의 일이다.
- **병원 IdP가 정해지면 이 블록만 교체한다.** `config/Caddyfile`은 `(authenticate)`(인증 블록)와 `(role_matchers)`(`@role_staff/@role_operator/@role_approver/@role_reviewer`)라는 이름만 안다. OIDC로 바꿀 때는 `secrets/gateway-accounts.caddy`의 `(authenticate)`를 OIDC 인증 조각으로 바꿔 인증 뒤 `{http.auth.user.id}`가 계정 ID가 되게 하고, 역할을 IdP 클레임에서 얻으면 `(role_matchers)`도 그에 맞게 바꾼다. `X-Openit-User` 규칙과 역할별 경로는 그대로다. (OIDC 모듈은 이 단계에서 넣지 않았다: 미검증.)

**키오스크 기기 인증(F절).** 키오스크 API(`/v1/sessions`, `/v1/sessions/*`)는 `Authorization: Bearer <기기 토큰>`이 없거나 목록에 없으면 401이다. 통과하면 게이트웨이가 Authorization 을 바꾸지 않고 기기 토큰을 그대로 survey 에 넘긴다(기기 토큰은 서비스로 가지 않는다). 기기 토큰은 기기마다 파일 하나(`tokens/kiosk-device-<ID>`), `secrets/gateway-devices.caddy`가 그 목록이다. 기본으로 시험 기기 `e2e` 하나가 만들어진다.
- 기기 추가: `bash scripts/kiosk-add-device.sh add <기기 ID> [--apply]`. 토큰 값은 출력하지 않고 파일 경로만 알린다. 기기에는 그 값을 기기 설정이나 시작 URL 조각(`#`)으로 한 번 전한다(URL 쿼리 금지).
- 폐기: `kiosk-add-device.sh remove <ID> --apply`(또는 파일을 지우고 `sync`). **Caddy는 설정을 읽을 때 한 번 치환하므로 게이트웨이를 다시 시작해야 반영된다**(`--apply`가 `compose restart gateway`). 이 시험은 자체 시험(`scripts/test-gateway-auth.sh`)에서 목록 갱신까지 확인했고, 실행 중인 게이트웨이의 재시작 반영은 확인하지 못했다.
- 키오스크 앱(kiosk-frontend)이 기기 토큰을 받아 보내는 구현은 그 영역의 일이다. 그 전에는 브라우저 데모의 키오스크 화면이 API를 부르지 못한다(401). 병원 내부망 제한은 배포 설정으로 병행한다.

**내부 호출 면은 게이트웨이에 열지 않는다(판단, D85).** 위험 신호 입력(`POST /v1/sessions/{id}/risk-signals`, 역할 risk-source)과 결과 조회(`GET /v1/results…`, 역할 result-reader)는 감지기·병원/의사 시스템이 부르는 기계 간 호출이다. 근거: (1) 게이트웨이는 사람(브라우저)과 키오스크 기기를 위한 입구이고 인증이 계정/기기 토큰이라 시스템 토큰과 맞지 않는다. (2) 결과 조회는 환자 식별 자료(`subject_ref`)를 주므로 입구를 넓힐수록 노출이 는다. (3) 위험 신호는 PAUSED_RISK로 세션을 멈추므로 키오스크 와일드카드(`/v1/sessions/*`)로 새면 안 된다: Caddyfile이 두 경로를 먼저 404로 닫는다. 토큰은 `secrets/tokens/survey-result-reader`, `survey-risk-source`(gen-secrets, survey-service에만 마운트)다. **남은 문제(결정 필요):** 지금 survey-service는 호스트 포트가 없고 `edge`·`serving`·`db` 네트워크에만 있어 도커 밖의 감지기·병원 시스템은 닿지 못한다(E2E는 시험 구성의 게시 포트로 직접 부른다). 병원 시스템 연동 방식이 정해지면 게이트웨이와 별도의 내부 입구(병원망 한정 리스너 + 시스템 토큰 통과, 또는 mTLS)를 두는 것을 권한다. 이 단계에서 만들지 않았다.

## 4-2. 버전 표 (드리프트 점검)

경계 계약·turn-engine·model-runtime의 태그 기준은 `scripts/lib.sh`의 표 한 곳이다. 형제 영역(survey-service, release-gate, model-lab, ops-feedback, question-authoring, synthetic-data, turn-engine, model-runtime)의 requirements/lock/pyproject/Dockerfile/스크립트에 손으로 적힌 같은 태그가 표와 다르면 `bash scripts/check-versions.sh`가 실패하고 `파일:줄`을 알려 준다(읽기 전용, 문서·시험·변경 이력 제외). 점검기 자체의 시험은 `bash scripts/test-check-versions.sh`, 비밀 점검기는 `bash scripts/test-check-secrets-hidden.sh`. 태그를 바꿀 때는 표를 먼저 고치고 이 점검이 가리키는 곳을 영역 세션에서 맞춘다.

## 4-3. 정적 일관성 점검 (check-all, 수 초)

영역 단위 시험은 영역 사이 어긋남을 못 본다. `bash scripts/check-all.sh`는 실행 없이 읽어서 아는 어긋남을 E2E(6분) 앞에서 잡는다. `e2e.sh`가 시작할 때 자동으로 부르고 FAIL이면 E2E를 시작하지 않는다(`DEPLOY_SKIP_CHECK_ALL=1`로 건너뛸 수 있으나 개발 중에만 쓴다).

- 규칙(0~11): 0 대상 열거(처리 방법을 모르는 영역·예시는 `모르는 대상`으로 FAIL), 1 버전표, 2 계약 예시 키 순서(대상은 scripts/check-all-ordered-schemas.txt), 3 완화 정책이 규칙을 빼지 않는지, 4 삭제된 이름의 잔존, 5 박은 `pipeline_schema_version`, 6 설정의 인라인 비밀, 7 compose의 환경 변수 비밀, 8 영역별 시험 수집, 9 영역 README 필수 절(정의는 scripts/check_all.py 주석과 출력에 있다), 11 compose 바인드 마운트의 원본(확장자가 있는 설정 파일)이 실제 파일인지(없으면 Docker가 root 소유 빈 디렉터리를 만들어 서비스가 설정을 못 읽는다).
- 규칙 10(E2E 통과 수는 정본에만): 모든 영역의 `*.md`에서 E2E 문맥의 통과 수 표기(`N PASS`, `PASS N`, `N 통과`)를 찾아 `docs/E2E_RESULTS.md`와 각 영역 `CHANGELOG.md` 밖에서 발견되면 FAIL. 문맥 판정은 `scripts/check-all-e2e-claims.txt`(claim/context/notcontext/allowed), 거짓 양성은 notcontext를 고치거나 `check-all-allow.txt`에 `10|경로|이유`로 적는다. 결과 줄은 e2e.sh가 끝에서 `scripts/record-e2e.sh`로 정본에 더한다.
- 출력: 규칙마다 PASS/FAIL/SKIP과 `검증됨 N/M, 어긋남, 대상 아님(이유), 검증 안 함(이유)`. 검증에서 빠진 것을 통과로 세지 않는다. SKIP은 어긋남은 없지만 검증 안 함이 있다는 뜻이다. FAIL이면 종료 코드 1이고 `영역/파일:줄` 근거를 낸다. 값·비밀은 출력하지 않는다.
- 예외: 정당한 언급은 `scripts/check-all-allow.txt`(규칙|경로 글롭|이유), 영역·예시를 점검에서 빼려면 `scripts/check-all.exclude`(`종류:이름 | 이유`, 이유 필수, 종류는 area/example/service). 두 목록은 출력에 그대로 나온다.
- 자체 시험: `bash scripts/test-check-all.sh`(임시 폴더에 어긋난 예시를 만들어 규칙마다 FAIL/PASS 확인). 형제 영역은 읽기 전용으로만 본다.

## 5. 화면별로 써 보는 법

아래 동작은 모두 **문서 기준**(kiosk-frontend, admin-console 설계 문서)이다. 게이트웨이를 거친 API 경로는 E2E로 확인했지만(확인함), **실제 브라우저에서 화면을 눌러 본 확인은 없다**(BLOCKED).

**키오스크 `/`** (인증 없음)
1. 시작 버튼 -> 안내 문장 -> 듣기. 음성(STT)을 쓸 수 없으면 입력창이 나온다. 문진 한 턴: 말하거나 입력하고 응답을 읽는다.
2. 위험 정지: 지금은 입력원이 없어 만들 수 없다(G01). 정지 화면(대기, `resume_text`)은 설계 문서 기준으로만 남아 있고 이 구성에서는 볼 수 없다.
3. 알림 전달에 실패하면(`DELIVERY_FAILED`) "직원을 직접 불러 주세요" 화면이 최우선으로 뜬다.

**직원 콘솔 `/staff/`** (계정 `staff`)
- 알림 목록과 실시간 알림(SSE). 지금은 알림 입력원이 없어 목록이 비어 있는 것이 정상이다(G01). 아래 `DELIVERED` 등의 서술은 v1 구조에서 확인한 것이며 이번 v2 E2E에서는 건너뛰었다(5d-skip).
- `DELIVERED`/`DELIVERY_FAILED`는 알림이 직원 쪽에 전달되었는지에 따라 갈린다. 직원 콘솔을 열어 SSE로 연결해 둔 상태에서 위험 정지를 내면 `DELIVERED`로 나오는 것을 E2E에서 확인했다(확인함). 연결이 없을 때 정확히 어떤 값이 되는지는 설계 문서 기준이며 데모에서 직접 확인하지 않았다.
- 알림마다 재개(RESUME) 또는 종료(END)를 고른다. 확인 후 전송이며, 같은 알림에는 같은 `turn_id`가 쓰인다. E2E에서 두 경로 모두 API로 확인함.

**승인 화면 `/admin/`** (계정 `trainer-e2e`)
1. 목록: 승인 대기(`AWAITING_APPROVAL`) 제출. (`up --stop-before-approval`로 띄우면 문항 세트 v1·v2 제출이 모두 대기한다.)
2. 보고서: 제출 정보와 자동 검사 결과 아래에 **SAFETY 지표를 먼저**, 그다음 나머지 그룹을 본다. "나빠짐"은 참고 표시일 뿐이다.
3. 결정: 승인 또는 반려(반려는 사유 필수). 확인창에서 보고서 해시 앞부분·결정·사유를 다시 보고 확정한다. 승인자 ID는 게이트웨이가 인증한 계정이 자동으로 기록된다.
- 화면은 합격/불합격을 판단하지 않는다. **합격 판정은 사람**이다. 다른 역할 계정은 403, 인증이 없으면 401(확인함).
- `--stop-before-approval`로 띄웠다면 승인 뒤 `demo.sh activate`.

**실패 사례 검토 화면 `/admin/` 의 검토 메뉴** (계정 `reviewer-e2e`)
- 시험 사례가 1건(PENDING) 있다. 사례를 열어 실패 유형·출처·비식별 trace를 보고 CONFIRMED 또는 반려로 검토한다. CONFIRMED는 종류(`expected_kind`: PARSER 또는 GENERATOR)를 고르고 고쳐 쓴 입력(`reviewed_input`)과 선택 정답을 JSON으로 쓴다.
- 검토자 계정만 쓸 수 있다(승인자 계정은 403, 확인함).

## 6. 원격 서버의 화면을 내 PC 브라우저로 열기

기본 바인드는 127.0.0.1이라 서버 밖에서 바로 열리지 않는다. SSH 터널을 쓴다.

```
bash scripts/status.sh                         # (서버에서) gateway 주소의 포트를 확인
ssh -L <포트>:127.0.0.1:<포트> <사용자>@<서버>   # (내 PC에서) 그 다음 브라우저로 http://127.0.0.1:<포트>
```

주의 한 줄: 이 PC에서 기본 SSH가 키 교환에서 멈추면 `-o KexAlgorithms=curve25519-sha256` 옵션을 붙인다.

HTTP·기본 인증이라 시험용이다. `DEMO_BIND=0.0.0.0`으로 열어 두는 것은 암호가 평문으로 흐르므로 권하지 않는다.

## 7. 수명주기

`bash scripts/status.sh`로 지금 상태(컨테이너, gateway 주소, `/readyz` 요약)를 본다. 내릴 때는 `scripts/down.sh [프로젝트=deploy] [옵션]`이다(`dc`는 셸 함수라 터미널에서 칠 수 없다). 프로젝트 이름은 `deploy`·`deploy-*`만 받는다.

| 명령 | 컨테이너 | 네트워크 | 데이터 볼륨 | 로컬 레지스트리 |
| --- | --- | --- | --- | --- |
| `down.sh deploy --stop` | 멈춤(남음) | 남음 | 남음 | 그대로 |
| `down.sh deploy` (= `--remove`) | 삭제 | 삭제 | 남음 | 그대로 |
| `down.sh deploy --purge` | 삭제 | 삭제 | **삭제(되돌릴 수 없음)**. 목록을 보이고 프로젝트 이름을 입력해야 진행 | 그대로 |
| 위에 `--registry` 추가 | | | | 내림. 이미지는 레지스트리 볼륨에 남음(`--purge`와 함께일 때만 볼륨 삭제, 따로 확인) |

비대화형 삭제는 `--purge --yes-purge-<프로젝트>`를 명시해야 한다. 끝나면 남은 자원을 출력한다.

다시 켜기: `--stop` 뒤에는 `docker compose -p deploy start`(또는 `scripts/up.sh deploy`). `--remove` 뒤에는 `scripts/up.sh deploy`(데이터 볼륨을 이어 쓴다). 데모는 `demo.sh down` 또는 `reset`.

디스크 정리: 먼저 `docker system df`로 크기를 확인한다. 지울지는 사용자가 판단한다. 대상은 `deploy-build/*` 이미지와 빌드 캐시, 데모·E2E가 남긴 `deploy-*` 자원 위주다. 예: `docker image ls 'deploy-build/*'`로 보고 필요 없으면 `docker rmi`, 빌드 캐시는 `docker builder prune`. 다른 이름의 자원은 건드리지 않는다.

## 7-1. 추론 서버를 다른 곳에 두는 법 (D72)

추론 서버(model-serving)는 컨테이너이고 어디에 두든(같은 컴포즈, 다른 GPU 서버) 기능 차이가 없어야 한다. 호출하는 survey-service는 주소(`SURVEY_INFERENCE_URL`)와 토큰만 알고, 서버는 release-gate 주소·토큰·프로파일을 환경 변수로만 받는다. **이 절의 구성은 파일과 스크립트를 만든 단계이며, 이 PC에서는 Docker 데몬이 꺼져 있어 컨테이너로 실행해 확인하지 못했다(미확인).** 확인된 것은 `bash -n`, 인자 검사, doctor 점검의 가짜 서버 시험, YAML 문법뿐이다. 실제 GPU 이미지는 이 단위에서 빌드·내려받지 않았다.

**(a) 추론 서버를 둘 호스트에서** (`compose.inference.yaml` 파일 하나와 이미지, 토큰 파일 두 개만 있으면 된다. deploy의 잠금 파일·네트워크·서비스 이름에 의존하지 않는다. 문진 스키마는 이미지에 내장되어 있어 스키마 마운트나 survey-service 이미지가 필요 없다)

| 변수 | 필수 | 뜻 |
| --- | --- | --- |
| `INFERENCE_IMAGE` | 필수 | model-serving 이미지 전체 참조(digest 고정). GPU 변형 이미지도 여기에 둔다 |
| `RELEASE_URL` | 필수 | release-gate 주소. 이 호스트에서 닿아야 한다 |
| `INFERENCE_TOKENS_FILE` | 필수 | 파일 경로(값이 아니다). 내용 `<호출자>=<토큰>[,...]` 한 줄(`MODEL_RUNTIME_TOKENS`, D84) |
| `INFERENCE_RELEASE_TOKEN_FILE` | 필수 | 파일 경로. 내용: 게이트 읽기 토큰 하나(`MODEL_RUNTIME_RELEASE_TOKEN`). 두 파일은 secrets로 `/run/secrets`에 마운트된다(환경 변수로 넣지 않는다). 컨테이너(uid 10001)가 읽을 수 있어야 한다(모드 644, 폴더 700) |
| `INFERENCE_CONFIG_ENV_FILE` | 선택 | (비밀이 아닌) 모델 설정 env 파일(프로파일 등). 기본 `/dev/null`. 토큰을 넣지 않는다 |
| `INFERENCE_BACKEND` | 선택 | 기본 `fake`. GPU 변형은 model-runtime이 정한 값 |
| `INFERENCE_BIND` / `INFERENCE_PORT` | 선택 | 호스트 바인드(기본 127.0.0.1: 다른 호스트가 닿게 하려면 사설 인터페이스 주소나 0.0.0.0을 명시하고 방화벽으로 호출자만 허용한다) / 포트(기본 8080, 빈 값이면 Docker 배정 -> `docker port`로 읽는다) |

```
# INFERENCE_BIND 기본은 127.0.0.1 이라 다른 호스트의 호출자가 닿으려면 아래처럼 명시한다(방화벽으로 호출자만 허용)
INFERENCE_IMAGE=<레지스트리>/openit/model-serving@sha256:... \
RELEASE_URL=http://<release-gate 주소>:<포트> \
INFERENCE_TOKENS_FILE=/안전한/경로/model-runtime-tokens INFERENCE_RELEASE_TOKEN_FILE=/안전한/경로/gate-read-model-serving \
INFERENCE_BIND=<이 서버의 사설 인터페이스 주소> \
docker compose -p deploy-inference -f compose.inference.yaml up -d --wait
```

- 데몬 없이 병합만 보려면 세 변수를 주고 `docker compose -f compose.inference.yaml config`(이 PC에서는 docker가 없어 실행해 보지 못했다).
- GPU 예약과 HF 캐시 볼륨은 파일 안에 주석 처리된 예시가 있다(GPU 이미지의 캐시 폴더 쓰기 권한은 확인 안 함).
- 배포용 model-serving 이미지는 `build-images.sh`가 문진 스키마(survey-service의 `survey-schema-v1.0.0` 태그 시점 `schema/`)를 `--build-context schema=`로 내장해 만든다. **이미지를 다시 만들고 게시해 `locks/images.lock`의 model-serving digest를 갱신해야 한다**(이 변경 전 digest의 이미지는 스키마가 없다).
- 토큰 값을 파일·인자로 저장소에 넣지 않는다.

**(b) 본 구성(호출자) 쪽에서**

```
export INFERENCE_TOKEN=<서버의 MODEL_RUNTIME_TOKENS 에 등록한 이 호출자 토큰>   # 또는 INFERENCE_TOKEN_FILE=<토큰 값 하나가 든 파일 경로>
bash scripts/doctor.sh --up --inference http://<서버>:8080        # 닿는지, 토큰이 통과하는지
bash scripts/up.sh deploy --external-inference http://<서버>:8080   # 이 구성의 model-serving 은 프로필로 꺼진다
bash scripts/demo.sh up --external-inference http://<서버>:8080     # 데모도 같은 옵션
```

토큰 값은 인자로 받지 않고 출력하지 않는다(`INFERENCE_TOKEN`이면 `secrets/tokens/external-inference`로 파일을 만든다. 컨테이너가 읽도록 모드 644, 폴더 700).

**양방향 도달성.** 호출자 -> 서버(위 doctor가 확인)와 서버 -> release-gate가 모두 열려야 한다. 후자는 서버 호스트에서 `RELEASE_URL`이 닿는지 직접 확인한다(doctor가 대신 확인하지 못한다). 상시 구성에서 release-gate는 호스트 포트를 열지 않으므로, 다른 호스트의 서버가 읽게 하려면 게이트를 노출하는 방법(운영 결정: 사설 네트워크·TLS·접근 제한)을 정해야 한다. 이 결정은 아직 없다(미정). 시험은 임시로 게이트를 0.0.0.0의 빈 포트에 한 번 더 노출한다.

**위치 독립 시험.** `bash scripts/test-inference-location.sh` : 추론 서버(CPU/fake)를 별도 컴포즈 프로젝트(`deploy-e2e-loc-inf`)로 띄우고, 본 구성이 `--external-inference`로 그 서버를 불러 E2E 단계 1~5를 통과하는지 본다(서버 중단·복구는 건너뛴다: Docker 배정 포트가 재시작 뒤 바뀔 수 있다). 호스트 포트는 모두 Docker가 배정하고, 먼저 127.0.0.1 게시로 시도하며 컨테이너가 닿지 못할 때만 시험 동안 0.0.0.0으로 올린다. 자원은 `deploy-e2e-loc*` 접두사이며 끝나면 지운다(`--keep`, `--clean`). 이 PC에서는 실행하지 못했다(미확인). 서버에서 한 번 돌려 확인해야 한다.

## 7-2. GPU로 실제 LLM 쓰기 준비 (D72/D73)

이 절은 **준비 단계**(이미지 빌드, compose override, 점검)다. 릴리스에 연결해 데모에서 실제 LLM으로 문진하는 것(`demo.sh --llm`)은 다음 단위이며 아직 없다. 이 PC에서는 Docker가 꺼져 있어 아래 명령을 **실행해 확인하지 못했다**(미확인). 서버(GPU)에서 확인해야 한다.

| 항목 | 값 | 상태 |
| --- | --- | --- |
| GPU 이미지(`model-serving-gpu`) 용량 | 약 13GB | model-runtime의 안내값. 서버에서 측정 전 |
| HF 캐시 볼륨(`deploy-llm-hf-cache`) 용량 | 약 4GB (기반 모델 Qwen/Qwen3-1.7B, bf16: 약 2B 파라미터 x 2바이트 계산값) | 계산한 추정, 서버에서 측정 전 |
| **합계** | **약 17GB** = 이미지 13GB(데몬에 한 벌) + 캐시 4GB(추정). 데모는 이미지를 레지스트리에 올리지 않으므로 **이중 보관이 없다** | 서버에서 측정 전 |
| 첫 기동 시간(모델 내려받기+적재) | 모름 | 측정 전. 헬스체크 start_period를 900초로 넉넉히 잡았다(잠정) |
| 프로파일 | `/app/profiles/gpu-12g.json`(12GB급, 기본), `rtx4090-24g.json`(24GB) | 이미지 안. `DEMO_LLM_PROFILE`로 고른다 |

순서:

```
bash scripts/doctor.sh --up --llm               # GPU 컨테이너 접근, 프로파일 대 GPU 메모리, 도커 디스크, huggingface.co 도달
bash scripts/build-images.sh --gpu              # GPU 변형만 빌드(model-runtime `DEPLOY_MR_TAG`, 현재 v0.7.3, 문진 스키마 내장). 빌드 전 docker system df 와 약 13GB 안내.
                                                #   비대화형이면 --yes-large 를 명시해야 진행한다
bash scripts/publish-images.sh model-serving-gpu   # 레지스트리에 올리고 잠금에 MODEL_SERVING_GPU_DIGEST 기록
```

- 기본 빌드(`build-images.sh`, 옵션 없음)에는 GPU 이미지가 들어가지 않는다. 기존 8개 서비스 흐름은 그대로다. 옵션 없이 `publish-images.sh`를 부르면 `build/images.env`에 GPU 이미지가 있을 때 그것도 올라가므로(약 13GB) 이름을 지정하는 편이 안전하다.
- `compose.llm.yaml`: model-serving을 GPU 이미지·`MODEL_RUNTIME_BACKEND=vllm`·`MODEL_RUNTIME_PROFILE`로 바꾸고, GPU 장치 1개 예약(`deploy.resources.reservations.devices`), 프로젝트 밖 이름 있는 볼륨(`external`, 기본 `deploy-llm-hf-cache`, `HF_CACHE_VOLUME`; 직접 쓸 때는 먼저 `docker volume create deploy-llm-hf-cache`)을 이미지가 준비한 `/var/lib/model-runtime/hf`(HF_HOME 기본값, uid 10001 소유)에 마운트한다(HF_HOME은 덮어쓰지 않는다). 쓰는 법(릴리스 연결 전의 수동 확인용): `docker compose -p <프로젝트> -f compose.yaml -f compose.llm.yaml -f compose.llm.digest.yaml --env-file locks/images.lock --env-file state/registry.env up -d`. 기본 `compose.yaml`은 바뀌지 않았다. **이미지 선택은 파일로 나눴다**: 운영/CI는 `-f compose.llm.digest.yaml`(게시된 digest), 데모는 `-f compose.llm.local.yaml`(`MODEL_SERVING_GPU_IMAGE`=로컬 태그, `pull_policy: never`). 중첩 기본값 한 파일(`${A:-${B:?}}`)은 일부 compose 버전이 안쪽 필수 변수를 미리 평가해 로컬 태그를 줘도 실패했다(서버 시험의 오류로 추정, 이 PC의 compose 5.0.2는 정상).
- **조합 규칙.** `compose.llm.yaml`은 `compose.external-inference.yaml`과 함께 쓰지 않는다(그쪽은 이 구성의 model-serving을 끈다). 다른 GPU 서버에 두려면 그 서버에서 `compose.inference.yaml`에 `INFERENCE_IMAGE=<GPU 이미지>`, `INFERENCE_BACKEND=vllm`과 프로파일을 준다. `compose.test.yaml`(가짜 백엔드)과 같이 쓰면 `-f` 순서에서 `compose.llm.yaml`이 뒤에 와야 한다.
- **인터넷.** 첫 기동은 huggingface.co에서 모델을 받는다. 오프라인이면 `hf-cache` 볼륨을 미리 채우고 `HF_HUB_OFFLINE=1`을 준다(이 볼륨 채우는 절차는 정리하지 않았다).
- 읽기 전용 루트에서 vLLM이 쓸 캐시 위치가 더 필요한지는 GPU 서버에서 확인 전이다(`XDG_CACHE_HOME`을 볼륨 안으로 두었다).

### 7-2-1. 데모를 실제 LLM으로 (`demo.sh up --llm`)

```
bash scripts/demo.sh up --llm [--profile gpu-12g] [--yes-large]     # reset --llm 도 같은 옵션
bash scripts/demo.sh config --llm                                    # 컨테이너를 띄우지 않고 병합된 compose 설정만 검증(이미지 참조가 로컬 태그인지, GPU 이미지가 이미 있는지)
bash scripts/demo.sh status                                          # model-serving 의 /readyz 사유(적재 중인지)와 survey-service 의 inference 요약
```

`up --llm`이 하는 일(순서): (0) **병합 사전 검증**(빌드·게시 전에 `docker compose config`로 model-serving 이미지가 로컬 태그인지 확인, 실패하면 빌드·게시 없이 멈춤) (1) `doctor.sh --up --llm` (2) 기본 8개 이미지 빌드(없을 때) (3) `model-serving-gpu`가 없으면 `build-images.sh --gpu`(용량 안내, 비대화형이면 `--yes-large`) (4) `make-llm-package.sh`로 중립 LoRA 패키지 생성 (5) 임시 레지스트리에 기본 8개 이미지만 게시한다(**GPU 이미지는 게시하지 않는다**: model-serving은 방금 빌드한 로컬 이미지 `deploy-build/model-serving-gpu:<커밋>`를 태그로 직접 쓰고 `pull_policy: never`. digest 고정은 데모에서 하지 않는다. 운영/CI는 게시된 digest를 쓰는 기존 방식 그대로 -- `compose.llm.yaml`의 `MODEL_SERVING_GPU_IMAGE`/`MODEL_SERVING_GPU_PULL`로 고른다) (6) 기동 직전 병합 검증을 한 번 더 한 뒤 `compose.yaml` + `compose.test.yaml` + `compose.llm.yaml` + `compose.llm.local.yaml` + `test/compose.llm-demo.yaml`로 기동 (7) E2E 단계 1~3·데모 단계를 돌려 릴리스를 만들고 활성화 (8) 적재가 끝날 때까지 기다린다.

- **모델은 학습하지 않은 Qwen/Qwen3-1.7B(프로파일 `gpu-12g`, 파이프라인 데모용. 학습된 4B/8B 어댑터는 ≥24GB GPU 프로파일에서 서빙한다) + 학습 데이터의 시스템 프롬프트(`prompt-4` 조립) + 효과 없는 LoRA(lora_B=0)이다. 시험용 대체다.** 학습하지 않았으므로 A 출력이 ActionExtraction 형식(문항 ID, `values`, `next_item` 규칙)을 못 지킬 수 있다. 그러면 서버가 재시도한 뒤 503 `OUTPUT_INVALID`를 내고, survey-service가 한 번 다시 보낸 뒤에도 안 되면 그 턴을 실패 신호로 처리한다(값을 지어내지 않는다, D75). B 출력은 문장이며 형식이 깨지면 규칙 기반 대체 문장이 나간다. **서버(gpu-dev)에서 Qwen3-1.7B가 12GB에 적재되는지, A·B 어댑터 동시 적재가 되는지, 제약 디코딩이 형식을 지키는지는 모두 미검증이다**(OPEN_GAPS U01, U07, U03, U04).
- **진단.** 릴리스 준비가 실패하면(`데모 릴리스 준비 실패`) `bash scripts/demo.sh diag`: release-gate의 모든 제출(status)과 각 GateDecision의 checks(kind, result, detail)·reject_codes, 활성 포인터, 후보 수집기 다시 실행(멱등) 결과, model-registry 패키지 요약, model-serving `/v1/info`(vllm 백엔드는 모델을 올리기 전에는 `serving_config_expectation`이 비어 있어 서빙 설정을 서버 값에서 맞출 수 없다: 그래서 패키지의 설정을 쓴다)를 읽기 전용으로 보여 준다. 자동 검사에서 반려되면 데모 실행도 60초를 기다리지 않고 같은 사유를 바로 출력한다.
- **재실행.** 이미 있는 이미지는 다시 빌드하지 않는다: 기본 8개는 `build/images.env`의 기록과 로컬 이미지가 모두 있으면 건너뛰고, GPU 이미지(13GB)는 기록과 이미지가 있으면 건너뛴다(8개를 다시 빌드해도 GPU 기록은 지우지 않는다). 강제: `--rebuild`(8개), `--rebuild-gpu`(GPU). 실패한 뒤에는 `demo.sh down`으로 상태(`state/demo`)를 지우고 다시 `up --llm`을 한다(로컬 이미지와 HF 캐시는 남는다).
- **중립 LoRA 패키지.** `scripts/make-llm-package.sh <프로파일> <폴더>`가 model-runtime 태그(`DEPLOY_MR_TAG`, 현재 v0.7.3)의 `git archive`에서 `make_neutral_package.py`와 `profiles/<이름>.json`을 꺼내 deploy의 `.venv`로 만든다. Docker 없이 실행되고 같은 입력이면 같은 바이트다(이 PC에서 실행해 `SUMMARY.json`과 결정성을 확인했다). **Qwen3-1.7B의 차원(은닉 2048, 28층, 어텐션 헤드 16, KV 헤드 8, head_dim 128)은 코드에 박지 않고** Hugging Face `config.json`(리비전 `70d244cc…` 고정, sha256 `1ddb5b89…` 검사)을 받아 `--model-config`로 넘긴다(받은 파일은 `build/hf-config/`에 보관한다. 인터넷이 없으면 `미확인`으로 중단하고 차원을 추정하지 않는다. 표에 없는 모델(예: `rtx4090-24g`의 Qwen3-8B)도 같은 이유로 중단한다). **시스템 프롬프트**는 `make_neutral_package.py`의 `--system-prompt-a/-b`(v0.7.0)로 `test/llm-demo/lora_a.system.txt`(927자), `lora_b.system.txt`(281자)를 넘긴다(생성기가 해시를 계산한다. 예전의 `apply_system_prompts.py` 후처리는 지웠다). 이 두 파일은 학습 서버 데이터의 system 메시지를 model-lab 리포의 `prompts/`에서 복사한 데모 입력이며 학습과 짝인지는 이 PC에서 확인하지 못했다. 데모의 단계 3은 이 패키지의 서빙 설정·어댑터·프롬프트로 자기 매니페스트를 만들며 lineage의 turn-engine 버전은 게이트 기준(`DEPLOY_TE_TAG`)과 같은 값을 쓴다(패키지 자체의 `none`은 쓰지 않는다). 단계 3이 단계 3이 이 패키지를 model-registry에 게시한다. 서빙 설정은 fake의 `/v1/info` 기대값이 아니라 패키지의 vllm 설정이고, 서버가 적재할 때 같은 설정인지 스스로 검사한다. 평가 보고서는 이전처럼 **시험용 고정 지표**(TEST-SUB)다.
- **시험 위험 문구는 없어졌다.** 계약 2.0.0에서 `MODEL_RUNTIME_FAKE_RISK_PHRASE`가 없어졌고(설정이 남아 있으면 서버가 시작을 거부한다) 직원 알림의 입력원이 비어 있다(OPEN_GAPS G01). `test/compose.llm-demo.yaml`은 필요 없어져 지웠다.
- **기다림.** 첫 기동은 모델 내려받기(약 4GB, 추정)와 적재로 오래 걸린다. `up`은 최대 20분(`DEMO_LLM_WAIT_MIN`) 30초마다 model-serving과 survey-service의 `/readyz`를 보여 준다. 시간이 지나도 **실패로 끝내지 않고** "아직 적재 중"이라 안내하고 끝낸다. `status`로 확인한다. **모델 캐시는 기본적으로 남는다**: `deploy-llm-hf-cache`는 프로젝트 밖 이름 있는 볼륨(없으면 `up --llm`이 만든다)이라 `demo.sh down/reset`, `down.sh --remove/--purge`가 지우지 않고, 다음 `up --llm`이 모델(약 8GB, 추정)을 다시 받지 않는다. 지우기: `bash scripts/demo.sh down --purge-cache` 또는 `bash scripts/down.sh --purge-hf-cache` (볼륨 이름을 직접 입력, 비대화형은 `--yes-purge-deploy-llm-hf-cache`). `status.sh`가 이 볼륨의 존재와 크기(`docker system df -v` 표를 읽음, 형식이 다르면 '알 수 없음')를 보여 준다. 로컬 GPU 이미지(`deploy-build/model-serving-gpu`)도 `down`이 지우지 않는다(`docker rmi`는 사용자가 판단).
- **미확인(서버에서 확인 필요).** 이 PC에서는 Docker가 꺼져 있어 이 흐름을 실행하지 못했다. 확인한 것은 `bash -n`, 인자 검사, `py_compile`, 중립 패키지 생성기 실행(`SUMMARY.json`)과 패키지 매니페스트의 `ModelPackageManifest` 스키마 통과다. 후보 수집·자동 검사(문항-모델 호환)가 vllm 설정에서 통과하는지, 서버의 실제 적재 시간, 위험 정지 동작은 확인하지 않았다.
- **조합 규칙.** `--llm`은 `--external-inference`와 함께 쓰지 않는다. 다른 GPU 서버에 두려면 7-1절을 따른다.

- **읽기 전용 루트에서의 캐시·홈·원격 측정.** model-serving은 `read_only` 루트(보안 설정 유지)라서 캐시·홈이 쓰기 가능한 serving-data 볼륨(`/var/lib/model-runtime/…`)을 가리켜야 한다(안 그러면 ~/.cache(컨테이너 HOME 아래)에서 `OSError: [Errno 30] Read-only file system`으로 적재 실패, `/readyz` 503 `RuntimeError`). 이 환경 변수(`HOME`, `XDG_CACHE_HOME`, `VLLM_CACHE_ROOT`, `TORCHINDUCTOR_CACHE_DIR`, `TRITON_CACHE_DIR`, `TORCH_HOME`)와 원격 측정 차단(`VLLM_NO_USAGE_STATS`, `DO_NOT_TRACK`, `HF_HUB_DISABLE_TELEMETRY`)은 **model-runtime v0.5.3부터 이미지의 ENV 기본값**이라 `compose.llm.yaml`은 다시 정하지 않는다(두 곳에서 어긋나는 것을 막으려는 것). 서버는 시작 때 캐시 디렉터리를 만들고 쓸 수 없으면 `/readyz`에 분명한 사유를 낸다. `compose.llm.yaml`에는 백엔드·프로파일·오프라인 같은 배포마다 달라지는 값만 있다. `TMPDIR`는 돌리지 않는다(`/tmp`는 noexec tmpfs, tmpfs exec 허용은 보안 설정 약화). 이 구성은 GPU 서버에서 확인 전이다.

### 7-2-1b. 진짜 어댑터 얹기와 GPU 구멍
`demo.sh up --llm --profile rtx4090-24g --adapter-a DIR --adapter-b DIR --prompt-a FILE --prompt-b FILE`은 중립 LoRA 대신 학습 서버에서 가져온 어댑터를 얹는다(기반 모델 불일치·순위 초과는 이미지 빌드 전에 거부, 평가하지 않음). GPU 서버가 열릴 때 따라 할 순서는 `docs/GPU_HOLE.md`. `demo.sh swap-adapters`는 떠 있는 데모의 model-serving만 새 어댑터로 바꾼다(7-2-3). `demo.sh up`은 끝에 비밀 노출 점검을 자동으로 돌린다(`demo.sh check-secrets`로 다시, 인자 없는 `check-secrets-hidden.sh`는 떠 있으면 데모도 점검).

### 7-2-2. 서버(gpu-dev)에서 할 일 -- Qwen3-1.7B 기준 (서버 미검증)

이 PC(GPU 없음)에서는 아래를 **하지 않았다.** 서버에 접속해 차례로 하고 결과를 OPEN_GAPS U07(새 구조의 실제 LLM 데모), U01(12GB에서 Qwen3-1.7B 적재, A·B 동시 적재)에 기록한다.

1. 최신 `main`을 받는다: 영역 리포 전부와 태그(boundary-contracts `v2.0.2`, turn-engine `v0.4.0`, model-runtime `v0.7.3`). `bash scripts/doctor.sh --up --llm`이 태그와 GPU·디스크·huggingface.co 도달을 본다.
2. `bash scripts/demo.sh up --llm --yes-large` (프로파일은 기본 `gpu-12g` = Qwen3-1.7B). 이미지가 v0.5.x 라벨이면 기본 8개와 GPU 이미지를 다시 빌드한다(약 13GB, 7-2절의 전환 안내). 첫 기동은 모델(약 4GB, 추정)을 받는다.
3. 패키지 생성 단계가 `config.json`을 받으려면 서버에서도 huggingface.co에 닿아야 한다. 닿지 않으면 `미확인`으로 멈춘다(`build/hf-config/Qwen__Qwen3-1.7B.config.json`을 다른 곳에서 받아 같은 위치에 두면 sha256 검사 뒤 쓴다).
4. 확인할 것(결과를 있는 그대로 적는다): (a) model-serving `/readyz`가 200이 되는가(적재, 메모리), (b) `/v1/info`의 `system_prompt_sha256`이 패키지(`test/llm-demo` 프롬프트)와 같은가, (c) 제출 3건이 `REJECTED_AUTO` 없이 승인 대기까지 가는가(`demo.sh diag`), (d) 키오스크 한 턴이 형식 위반(`OUTPUT_INVALID`) 없이 도는가 -- 학습하지 않은 모델이라 실패할 수 있고, 그 빈도가 U04 자료다, (e) `nvidia-smi`의 사용 메모리(프로파일 `engine` 값이 추정이므로 확정 근거).
5. 안 되면 `bash scripts/demo.sh diag`와 model-serving 로그(발화·모델 출력 원문은 로그에 없다)를 모아 헤드에게 넘긴다. 프로파일 값(`max_model_len`, `gpu_memory_utilization` 등)은 deploy가 아니라 model-runtime이 소유한다.
6. LoRA 교체 시험(D72, U08): 같은 기반 모델의 두 번째 어댑터가 생기면 `bash scripts/demo.sh swap-adapters --adapter-a ... `(7-2-3)로 model-serving만 바꾸고 나머지가 그대로 도는지 본다. 이 PC에서는 가짜 백엔드로만 해 봤고 실제 LoRA로는 하지 못했다.

**모델 캐시가 쓰기 불가일 때** (`/readyz` 503 사유 `OSError`, `status.sh`/`diag`에 "모델 캐시 쓰기 불가 가능성" 안내).
- 원인: model-serving은 uid 10001로 도는데, HF 캐시 볼륨이 이미지가 준비하지 않은 경로에 마운트되었거나(예: 옛 설정의 `/var/lib/hf-cache`) root 소유로 초기화되어 쓸 수 없다. 이미지는 `/var/lib/model-runtime/hf`와 `bundles`를 uid 10001 소유로 만들어 두므로 `compose.llm.yaml`은 그 경로에 마운트한다. 빈 새 볼륨은 처음 마운트될 때 그 경로의 소유자로 초기화된다.
- 확인(읽기만): `bash scripts/demo.sh diag`가 컨테이너 안의 실행 uid, HF 경로 소유자, 쓰기 가능 여부(`test -w`)를 보여 준다. 직접: `docker exec <프로젝트>-model-serving-1 sh -c 'id -u; stat -c %U /var/lib/model-runtime/hf; test -w /var/lib/model-runtime/hf && echo writable'`.
- 이미 root 소유로 만들어진 **빈** 볼륨이면 한 번 지우고 다시 만든다(내려받은 모델이 없는 볼륨이다. 모델이 들어 있다면 지우지 않는다): `bash scripts/demo.sh down` 뒤 `docker volume rm deploy-llm-hf-cache`(또는 `bash scripts/down.sh --purge-hf-cache`), 비어 있는지는 `docker system df -v`의 SIZE로 본다(`0B`). 그다음 `demo.sh up --llm`이 새로 만든다. 이미지 재빌드는 필요 없다.

**v0.5.2 -> v0.5.3 전환 시 서버 재실행과 용량 계획(이번 한 번).** `demo.sh up --llm`은 기본 8개 이미지의 `io.openit.model-runtime` 라벨이 현재 태그와 다르면 다시 빌드하고(약 3분, 1.7GB 안팎), **GPU 이미지도 라벨이 다르면 다시 빌드한다**(자동. 비대화형은 `--yes-large` 필요; 안내 문구에 이유를 출력한다).
- 서버의 빌드 캐시는 LABEL이 앞에 있던 이전 Dockerfile로 만든 것이라, 새 층 구조(LABEL을 맨 뒤로)에서는 첫 빌드가 pip 층부터 다시 이뤄진다: 약 9분, 새 층 약 13GB(측정 전 추정).
- **옛 이미지는 자동으로 지워지지 않는다.** 이미지 태그에 model-runtime 커밋이 들어 있어 새 빌드의 태그가 달라서, 옛 GPU 이미지(v0.5.2, 13.1GB)는 dangling이 아니라 **옛 태그를 가진 채** 남는다. 빌드 끝에 `docker rmi <옛 태그>` 목록을 출력한다. 회수 절차(사용자가 판단): ① `docker system df`를 기록 ② 새 이미지로 `demo.sh up --llm`이 성공하는 것을 확인 ③ `docker image ls deploy-build/model-serving-gpu`에서 옛 태그를 `docker rmi` (기본 8개의 옛 태그도 마찬가지) ④ `docker image prune -f`(dangling)와 `docker builder prune -f`(옛 빌드 캐시) ⑤ `docker system df`를 다시 기록해 전후를 비교. Docker Desktop(WSL2)은 지워도 호스트 디스크 파일이 줄지 않을 수 있다.
- 이후 빌드부터는 REVISION이 바뀌어도 무거운 층이 재사용된다(LABEL이 뒤라서).

**용량과 정리.**
- 확인: `docker system df`(이미지·볼륨·빌드 캐시의 크기와 회수 가능량). Docker Engine(리눅스)은 보통 `/var/lib/docker`(`docker info --format '{{.DockerRootDir}}'`), Docker Desktop은 VM 디스크 안이라 이 셸의 `df`로 보이지 않는다(설정의 Resources > Disk image 위치).
- 지울지는 사용자가 판단한다. GPU 이미지: `docker image ls 'deploy-build/model-serving-gpu'`로 보고 필요 없으면 `docker rmi <이미지>`(레지스트리에 올렸다면 레지스트리 볼륨에도 있다: `scripts/down.sh <레지스트리 프로젝트> --registry --purge`는 레지스트리 볼륨까지 지운다). HF 캐시: `bash scripts/down.sh --purge-hf-cache`(또는 `demo.sh down --purge-cache`)로만 지워진다. **Docker Desktop(WSL2)은 이미지·볼륨을 지워도 호스트의 디스크 파일이 줄지 않을 수 있다**(디스크 이미지 축소는 Docker Desktop 설정에서 사용자가 판단). 빌드 캐시: `docker builder prune`.

### 7-2-3. 어댑터 교체와 추론 서버 측정 도구

**어댑터 교체 `demo.sh swap-adapters`** (D72, OPEN_GAPS U08): 떠 있는 데모에서 `reset`처럼 전체를 다시 만들지 않고 model-serving만 새 번들을 적재하게 한다. 순서는 새 모델 패키지 게시, 후보 수집·자동 검사, 시험용 승인자(스크립트, TEST-SUB) 승인, 활성화, model-serving에서 새 release_id `LOADED` 확인이다. 승인·활성화는 E2E 단계 코드(`scripts/e2e_steps.py`의 `demo_swap`: 게시는 단계 3과 같은 `publish_packages`, 컨테이너 비교는 단계 5s와 같은 `container_ids`·`check_unchanged`)를 그대로 쓴다.
```bash
bash scripts/demo.sh swap-adapters          # 가짜 백엔드 데모: 시험용 어댑터 쌍(새 패키지 ID)으로 교체
bash scripts/demo.sh swap-adapters --adapter-a DIR --adapter-b DIR --prompt-a FILE --prompt-b FILE   # --llm 데모: 진짜 어댑터
```
- 어댑터 인자는 `up --llm`과 같은 사전 검사(`make-llm-package.sh --check-only`, 기반 모델·순위·파일)를 먼저 거친다. 거부되면 아무것도 게시하지 않고 비0으로 끝난다(활성 릴리스 그대로). 가짜 백엔드 데모에 진짜 어댑터를 주면 검사 뒤에 "가짜 백엔드라 얹을 수 없다"로 멈춘다. `--llm` 데모에서 인자 없이 부르면 거부한다.
- 출력: 교체 전후 활성 릴리스와 pointer_version, 서비스별 컨테이너 StartedAt(전 -> 후, `불변`), model-serving의 새 release_id 상태. 컨테이너 Env는 읽지 않는다.
- 같은 어댑터 쌍을 다시 주면 이미 활성이라 교체 없음으로 끝난다. 문항 세트는 가장 최근 것을 그대로 쓴다.
- 이 PC에서 확인한 것: 가짜 백엔드 데모의 시험용 어댑터 교체와 기반 모델 불일치 거부. 확인하지 못한 것: `--llm`(vLLM) 데모의 교체.

**추론 서버 측정 도구 `scripts/probe-serving.py`**: 떠 있는 model-serving의 `extract`와 `respond`에 입력 묶음을 보내 집계한다(표준 라이브러리만 씀, 서비스를 거치지 않음). `--endpoints extract|respond|extract,respond`(기본 둘 다); respond 입력은 `../boundary-contracts/examples/ResponseRequest*.json`.
```bash
python3 scripts/probe-serving.py --demo [--repeat N] [--concurrency K] [--inputs FILE]     # 데모 스택(포트는 Docker 배정을 compose port로 찾는다)
python3 scripts/probe-serving.py --url http://HOST:PORT --token-file FILE [--release-id ID]  # 다른 model-serving(예: 외부 추론 서버)
```
- 토큰: `NAME_FILE`처럼 파일에서 읽는다(값 하나가 든 파일). `--demo`의 기본은 `state/demo/secrets/tokens/inference-survey-service`. 토큰 값은 출력하지 않는다.
- 입력: 없으면 `../boundary-contracts/examples/ActionExtractionInput.json`에 내장 발화 10개를 바꿔 넣는다. 파일은 ActionExtractionInput 하나, 그 배열, 또는 `{"inputs": [...]}`.
- 출력 표: 성공 / `OUTPUT_INVALID` / 그 밖의 실패 건수, `X-Openit-Outcome` 분포, `details.violations`("경로:키워드")의 키워드별 빈도와 경로:키워드 상위, 지연(첫 호출 대 이후 중앙값·최소·최대). 발화·모델 출력은 출력하지 않는다. `OUTPUT_INVALID`가 있어도 종료 코드는 0이다(측정 도구, 합격 판정이 아님). 서버에 닿지 못하면 3, 사용 오류는 2.
- 지연 표(엔드포인트별 한 줄): 호출 수, 성공(HTTP 200)·성공률, fallback 수(respond), 콜드 첫 호출, 이후 p50/p95/max, `X-Openit-Attempts` > 1 인 재시도 호출의 호출 수와 p50/p95/max(따로). 백분위는 최근접 순위, 표본 20 미만이면 p95 = max. 시간 상한 재정(GPU_HOLE H1)에 쓴다.
- 첫 호출은 항상 혼자 보내므로 문법 컴파일 같은 첫 호출 비용이 이후 중앙값과 분리되어 보인다(재시작 직후에 쓴다).
- 자체 시험: `python3 scripts/test_probe_serving.py`(일부러 OUTPUT_INVALID를 섞은 가짜 응답과 가짜 서버로 집계를 확인). GPU 측정 절차는 `docs/GPU_HOLE.md` H4.
- 한계: 이 PC에서는 가짜 백엔드(출력 고정)에만 돌려 봤다. 실제 모델의 OUTPUT_INVALID 분포는 측정 전이다.

## 8. 흔한 문제

| 증상 | 원인·조치 |
| --- | --- |
| `docker 실행 파일을 찾을 수 없다` / docker.exe 없음 | Docker가 설치되지 않았거나 PATH에 없다. WSL이면 Docker Desktop의 WSL 통합을 켠다. `bash scripts/doctor.sh`, [SETUP.md](SETUP.md) |
| `Docker 데몬에 닿지 않는다` | 데몬이 꺼졌거나 접근 권한(리눅스는 docker 그룹)·`DOCKER_HOST`/context가 틀렸다. doctor가 원인을 구분해 안내한다 |
| 빌드가 `docker-credential-desktop.exe: exec format error`로 실패 | WSL interop이 꺼진 상태에서 `credsStore`가 윈도 도우미를 가리킨다. 우회하지 않는다: doctor가 FAIL로 알리고 SETUP.md E절이 조치를 설명한다 |
| 형제 리포 또는 태그가 없다 | `head/setup.sh`로 받는다. 태그가 없으면 doctor가 어떤 리포의 어떤 태그인지 알린다([SETUP.md](SETUP.md) C절) |
| survey-service `/readyz` 503 `no_active_release`, 키오스크가 직원 호출 화면 | 상시 구성에서는 정상(활성 릴리스 없음). 눌러 보려면 데모 |
| 게이트웨이 401 | 인증 없이 직원·승인 경로를 부른 것. 계정과 `secrets/tokens/*-password` 파일의 암호로 로그인. 역할이 다르면 403 |
| 제출이 `REJECTED_AUTO`, `CONTRACT_COMPAT` FAIL (model-runtime 버전이 게이트 기준과 다르다) | 이미지마다 model-runtime 태그가 다르다. 모든 이미지는 같은 태그(`lib.sh`의 `DEPLOY_MR_TAG`, 현재 v0.7.3)로 빌드해야 한다 | 이미지를 다시 빌드(`demo.sh up`은 라벨이 다르면 기본 8개를 자동 재빌드, GPU 이미지는 라벨이 같으면 건너뜀). `demo.sh diag`로 확인 |
| `up --llm` 뒤 model-serving `/readyz`가 503 `OSError`로 계속 | HF 캐시 경로가 uid 10001이 쓰지 못하는 곳(root 소유 볼륨/이미지에 없는 경로) | 7-2절 '모델 캐시가 쓰기 불가일 때' (`demo.sh diag`로 확인, 빈 볼륨이면 `down` 뒤 `docker volume rm deploy-llm-hf-cache`) |
| model-serving `/readyz` 503 사유 `RuntimeError`, 로그에 `OSError: [Errno 30] Read-only file system: '~/.cache(컨테이너 HOME 아래)'` | 읽기 전용 루트에서 vLLM·torch 캐시가 홈 아래를 쓰려 한다 | `compose.llm.yaml`의 캐시·홈 환경 변수가 있는지 확인(`demo.sh config --llm`). 7-2절 '읽기 전용 루트에서의 캐시·홈·원격 측정' |
| 포트 충돌 | 컨테이너 호스트 포트는 Docker가 배정하므로 드물다. 레지스트리는 `REGISTRY_HOST_PORT=`(빈 값)으로 빈 포트를 고른다 |
| `state/registry.env`가 없다 | 레지스트리를 아직 안 띄웠다. `bash scripts/registry.sh up`을 먼저 |
| `이미 데모 상태가 있다` | `demo.sh down` 또는 `reset` |

## 9. 알려진 한계

- 실제 브라우저에서 화면을 눌러 본 확인이 없다(렌더링은 E2E에서 BLOCKED). 5절은 설계 문서 기준이다.
- 모델은 가짜 백엔드뿐이다(실제 GPU 모델은 이 PC에서 시험하지 못했다: 7-2-2절은 서버 미검증). 데모의 승인자·어댑터·평가 보고서는 시험용 대체다.
- 운영 로그인 방식과 HTTPS(도메인·인증서)는 미정이다. 지금은 HTTP + 기본 인증이다.
- 웹 푸시·음성 인식(STT) 수신 확인, 백업 설정(O16), 주기 잡 간격은 미정 또는 미확인이다.
- 이 문서의 시간은 측정한 것만 적었다.
