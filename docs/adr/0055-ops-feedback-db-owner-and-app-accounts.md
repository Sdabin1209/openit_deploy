# 0055. ops-feedback DB 계정을 소유자(DDL)와 앱(DML)으로 나눈 배선

- 상태: 채택 (OPEN_GAPS L08, 2026-11-03). ops-feedback ADR 0031 의 배포 쪽
- 날짜: 2026-11-03

## 맥락

ops-feedback 은 서버·잡을 `OPS_DB_SCHEMA=verify` 로만 띄우고 스키마는 `admin migrate` 가 소유자 계정으로 만든다고 정했다(ops-feedback ADR 0031). 같은 환경 변수 이름(`OPS_LOG_DATABASE_URL_FILE`, `OPS_FAILURE_DATABASE_URL_FILE`)에 migrate 에는 소유자 접속 문자열 파일을, 서버·잡에는 앱 접속 문자열 파일을 주는 것은 deploy 가 정한다. 지금까지는 데이터베이스 소유자 한 계정이 서버·잡 모두에 쓰여 앱 침해가 곧 스키마 파괴였다.

## 결정

- PostgreSQL 초기화(`config/postgres/initdb/10-roles.sh`)가 `PG_APP_ACCOUNTS`(기본 `ops_log ops_failure`)마다 `<이름>_app` 계정을 더 만든다: 접속, public 스키마 USAGE, 표 SELECT/INSERT/UPDATE/DELETE, 시퀀스 USAGE/SELECT 만. 소유자가 나중에 만드는 표·시퀀스에도 `ALTER DEFAULT PRIVILEGES` 로 같은 권한이 붙는다.
- 비밀: 소유자 `db-ops-log-dsn`/`db-ops-failure-dsn`(기존 이름 그대로), 앱 `db-ops-log-app-dsn`/`db-ops-failure-app-dsn`와 `-app-password`. `gen-secrets.sh` 가 만든다.
- compose: 일회성 서비스 `ops-feedback-migrate`(소유자 접속 문자열만, `python -m ops_feedback.admin migrate`, restart 없음, 기본 기동에 포함). 서버 `ops-feedback-ingest`와 잡 `job-ops-feedback` 은 앱 접속 문자열만 받고 `OPS_DB_SCHEMA=verify`, migrate 가 `service_completed_successfully` 한 뒤에 뜬다.

## 왜

- 최소 권한(NIST SP 800-53 AC-6, OWASP ASVS V1)과 마이그레이션 도구의 표준 배포 방식(별도 DDL 계정)을 따른다. 앱 계정은 DDL 이 불가능함을 `test-postgres.sh` 가 실제 PostgreSQL 에서 CREATE/ALTER/DROP/TRUNCATE 실패로 확인한다.
- 일회성 서비스는 `depends_on` 조건으로 순서를 compose 가 보장한다. `job-*` 로 이름 짓고 profile 을 걸면 상시 서버가 profile 비활성 서비스에 의존하게 되어 compose 가 거부할 수 있어 쓰지 않았다(확인한 것은 아니고 피한 것이다).
- 계약 `OpsFeedbackServerEnv.OPS_DB_SCHEMA` 의 기본이 verify 이고 값은 `check_config_contracts` 가 검증한다.

## 검토한 대안과 버리는 이유

- 소유자 계정을 서버·잡에도 준다(현행): 위 맥락.
- 새 환경 변수로 소유자 URL 을 구분: 계약에 이름을 추가해야 한다. 파일만 바꿔 주는 것으로 충분하다(ops-feedback ADR 0031).

## 결과

- 얻는 것: 서버·잡 침해로 스키마를 바꿀 수 없다. 배포 순서(migrate 먼저)가 compose 에 고정된다.
- 감수하는 것: 비밀 파일 4개와 서비스 1개가 늘었다. 이미 운영 중인 볼륨에는 앱 계정이 없으므로 `scripts/pg-roles.sh sync` 로 만든 뒤 올려야 한다(멱등). 소유자 계정이 가진 표에 앱 권한을 주는 것은 초기화 때 한 번(기존 표)과 기본 권한(새 표)이다.
- 확인하지 못한 것: 실제 ops-feedback 이미지로 migrate → verify 서버 기동이 이어지는지(E2E 에서만 확인, 돌리지 않았다). `up --wait` 가 종료된 일회성 서비스를 정상으로 보는지도 E2E 에서 본다.

## 되돌리는 조건

단일 계정만 쓰는 호스팅이면 앱 접속 문자열 파일을 소유자와 같은 내용으로 두면 된다(ops-feedback ADR 0031).
