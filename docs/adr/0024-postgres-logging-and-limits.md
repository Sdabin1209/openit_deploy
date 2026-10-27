# 0024. PostgreSQL 로그에 값이 남지 않게, 연결 상한, 로컬 인증

- 상태: 채택 (연결·타임아웃 값은 잠정)
- 날짜: 2026-10-28
- 관련: 점검 C4(비식별)·G2(연결)·B12, ADR 0021

## 맥락

PostgreSQL은 설정 파일이 없어 기본값으로 떴다. 기본 `log_min_error_statement=error`는 오류가 난 SQL 문장을 리터럴 값과 함께 서버 로그에 쓴다. 오류의 DETAIL 줄도 값을 담는다(예: 'Key (id)=(…) already exists'). 그 로그는 호스트의 json-file에 쌓인다. 환자 데이터가 로그로 새는 경로다. 연결 상한은 기본 100뿐이고 서비스별 상한이 없었다.

## 결정

postgres 서비스에 서버 인자로 다음을 준다(`compose.yaml`의 `command`):

- `log_statement=none`, `log_min_duration_statement=-1`: 문장 로깅과 느린 쿼리 로깅 끔(기본값이지만 못 박는다).
- `log_min_error_statement=panic`: 오류 때 문장을 로그에 쓰지 않는다.
- `log_error_verbosity=terse`: DETAIL·HINT·QUERY·CONTEXT 줄을 뺀다.
- `max_connections=100`(기본값을 명시), `idle_in_transaction_session_timeout=300000`(5분).
- 계정마다 `CONNECTION LIMIT 20`(`PG_ROLE_CONN_LIMIT`, `10-roles.sh`).
- pg_hba: 루프백 TCP의 `trust`를 `scram-sha-256`으로 바꾼다(이미 있던 `all` 줄에 더해 **`replication` 줄도**). 로컬 유닉스 소켓의 trust는 남긴다(컨테이너 안 `docker exec`로만 닿는다: 백업이 암호 없이 소유 계정으로 들어가는 길이다).
- `scripts/pg-config-check.sh`가 떠 있는 서버에서 이 설정과 `pg_hba_file_rules`를 읽어 확인한다.

## 왜 (따른 표준과 근거)

- 설정 이름과 의미는 PostgreSQL 공식 문서(런타임 설정 '오류 보고와 로깅')를 따른다. 이 세션에서 문서를 다시 열지는 않았고 **동작은 실제로 확인했다**: 일부러 중복 키 오류를 일으킨 뒤(값 `LOGLEAK_probe_value`) 서버 로그에 오류 자체는 있고 값과 'Key (id)=' 줄은 없음을 `test-postgres.sh`가 확인한다. `terse`에서도 **오류의 첫 줄 본문에 값이 들어가는 오류 종류**(예: 잘못된 입력 값 오류)는 남을 수 있다. 완전한 차단은 아니다.
- 최소 권한과 암호 인증: 루프백 trust는 컨테이너 안의 어떤 프로세스든 암호 없이 들어가게 한다. `pg-config-check.sh`가 `replication` 줄의 루프백 trust가 남아 있음을 찾아냈다(이전 `sed`는 `all` 줄만 바꿨다). 고쳐서 host 줄에 trust가 0개임을 확인했다.
- 계정별 연결 상한: 한 서비스의 연결 폭주가 이웃을 막지 않게 하는 서버 쪽 강제(D85(6) 근거 (3)).

## 검토한 대안과 버리는 이유

- **로그 수준을 `log_min_messages` 등으로 낮추기만**: 문장 로깅은 막지 못한다. 버린다.
- **로그 드라이버를 none으로**: 장애 진단이 불가능해진다. 값이 새지 않는 로그는 남기는 편이 낫다.
- **전역 `statement_timeout`**: 마이그레이션·`pg_dump`·복원 같은 긴 정상 작업을 끊을 수 있고 서비스별 마이그레이션 정책을 deploy가 모른다(**확인 못 함**). 적용하지 않았다. 서비스별로 영역이 정할 일이다.
- **로컬 소켓도 scram**: 백업/복원 스크립트(`docker exec`, 소유 계정, 암호 없음)와 초기화가 깨진다. 소켓은 컨테이너 안에서만 닿으므로 trust를 둔다.

## 결과

- 얻는 것: 오류 로그에서 SQL 문장·DETAIL의 값이 빠진다, 서비스별 연결 상한, 방치된 트랜잭션 정리, 루프백 인증 일관.
- 감수하는 것: DB 오류 진단이 덜 자세하다(문장이 없다). **연결 상한 20과 idle 트랜잭션 5분에는 근거 기록이 없다**(서비스의 연결 풀 크기를 확인하지 못했다: 풀 합이 상한을 넘으면 연결 거부가 난다. E2E와 H1에서 확인). 이미 떠 있는 서버에는 `pg-roles.sh sync`로 연결 상한을 적용한다(재기동은 서버 인자를 적용한다). 데이터베이스 TLS와 볼륨 암호화는 이번 범위가 아니다(C5, 호스트 일).

## 되돌리는 조건

- 진단에 문장이 꼭 필요한 사고가 반복되면 그 시간 동안만 `log_min_error_statement`를 올리고 로그를 즉시 회수한다(운영 절차).
- 서비스 풀 크기가 확인되면 연결 상한을 그에 맞춘다.
