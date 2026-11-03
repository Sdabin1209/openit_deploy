#!/usr/bin/env bash
# 서비스 토큰과 salt를 만든다. 사용: gen-secrets.sh [디렉터리]  (기본 secrets/, gitignore). 이미 있는 파일은 건드리지 않는다.
# CONVENTIONS 9절: 서버는 토큰에 역할을 묶는다. 호출하는 영역마다 다른 읽기 토큰, 쓰기 토큰은 역할마다 하나.
# secrets/tokens/<이름> : 비밀 값 하나가 파일 하나(개별 토큰, 서버가 받는 목록 값 "역할=토큰,...", salt, 콘솔 암호).
#   compose.yaml 의 최상위 secrets 가 이 파일을 /run/secrets/<이름> 에 마운트하고, 서비스는 NAME_FILE 경로로만 읽는다(D84).
#   예전 방식 secrets/<서비스>.env(환경 변수로 토큰 주입)는 없앴다: 남아 있으면 지워도 된다(아래에서 알려 준다).
# PostgreSQL: tokens/pg-superuser-<영역>(영역 DB 의 슈퍼유저), tokens/db-<이름>-password(서비스 계정 암호), tokens/db-<이름>-dsn(접속 문자열 한 줄,
#   postgresql://<계정>:<암호>@<서비스>-db:5432/<데이터베이스>). 이름 규칙은 docs/RUN.md 4-1-1. DSN 은 암호가 바뀌면 같이 갱신된다.
#   --db-only : PostgreSQL 비밀만 만든다(caddy 이미지가 필요 없다. 시험·개발용).  사용: gen-secrets.sh [--db-only] [디렉터리]
# 권한: 디렉터리 700(호스트 다른 사용자 차단). 파일은 secret_mode(lib.sh): 컨테이너가 읽는 것은 640 + 그룹(추론 서버용 토큰도 같다, RUNTIME.md R6.3), 호스트에서만 쓰는 것(계정 암호·해시, 기기 토큰 원본)은 600.
#   컨테이너가 읽는 파일을 600 으로 만들지 못하는 이유: compose 의 파일 secrets 는 호스트 소유자·모드를 그대로 마운트하고 uid/gid/mode 옵션은 적용되지 않아(측정함),
#   uid 10001 인 컨테이너가 호스트 사용자 소유 600 파일을 읽지 못한다. docs/adr/0022-secret-file-permissions.md. 이미 있는 파일의 모드도 실행할 때마다 바로잡는다.
#   --test-fixtures : 시험 자격(시험 기기 e2e, e2e-a/b/c)을 **더한다**. E2E·데모·자체 시험만 넘긴다. 사람 계정은 비밀 파일이 아니라 Keycloak 에 있다(U82, ADR 0057): 시험 사용자는 E2E·데모가 Keycloak 에 만든다(scripts/idp-test-users.sh).
#     없으면 운영 자격만 만든다(기기 0대, 사람 계정은 Keycloak realm openit 의 초기 admin 하나). 시험 자격이 운영 gateway 에서 유효해지는 것을 막는다(12-factor 10항, OWASP 기본 자격 금지).
#     시험 폴더에는 .test-fixtures 표시를 남기고, 운영 기동 점검(check-test-fixtures.sh)이 시험 자격이 든 폴더를 거부한다.
set -euo pipefail
ONLY_DB=0; TEST_FIX=0
while [ "${1:-}" = "--db-only" ] || [ "${1:-}" = "--test-fixtures" ]; do case "$1" in --db-only) ONLY_DB=1;; --test-fixtures) TEST_FIX=1;; esac; shift; done
[ "$ONLY_DB" = 1 ] && DEPLOY_NO_DOCKER=1   # --db-only 는 docker 를 쓰지 않는다
source "$(dirname "$0")/lib.sh"
D=${1:-$DEPLOY_ROOT/secrets}; mkdir -p "$D/tokens"; chmod 700 "$D" "$D/tokens"
rnd() { python3 -c 'import secrets;print(secrets.token_hex(24))'; }
tok() { [ -s "$D/tokens/$1" ] || ( umask 077; rnd > "$D/tokens/$1" ); secret_fix "$D/tokens/$1" "$1"; cat "$D/tokens/$1"; }
putlist() { local f="$D/tokens/$1"; [ "$(cat "$f" 2>/dev/null)" = "$2" ] || ( umask 077; printf '%s\n' "$2" > "$f" ); secret_fix "$f" "$1"; }
roles() { local srv=$1 kind=$2; shift 2; local out=""; for r in "$@"; do out+="${out:+,}$r=$(tok "$srv-$kind-$r")"; done; echo "$out"; }

# PostgreSQL 계정: 이름 = 데이터베이스 = 계정. 환경 변수 이름은 docs/RUN.md 4-1-1 표(SURVEY_DATABASE_URL 등)
gen_db() {
  # 영역마다 자기 DB 컨테이너(<서비스>-db)와 자기 슈퍼유저 암호를 가진다: 다른 영역의 DB 계정·접속은 없다(RUNTIME R6.2, 구조 규칙 1)
  for su in survey qa ops gate keycloak; do tok "pg-superuser-$su" >/dev/null; done
  local a n h
  dbhost() { case "$1" in survey) echo survey-db;; qa) echo question-authoring-db;; ops_log|ops_failure) echo ops-feedback-db;; gate) echo release-gate-db;; keycloak) echo keycloak-db;; esac; }
  for a in survey qa ops_log ops_failure gate keycloak; do
    n=${a//_/-}; tok "db-$n-password" >/dev/null
    putlist "db-$n-dsn" "postgresql://$a:$(cat "$D/tokens/db-$n-password")@$(dbhost "$a"):5432/$a?sslmode=verify-full&sslrootcert=/etc/openit/pki/root_ca.crt"
  done
  # L08: 스키마를 만드는 소유자 계정(위 db-$n-*, admin migrate 잡만 쓴다)과 DML만 가진 앱 계정(<이름>_app, 서버·잡이 쓴다)을 나눈다. 앱 계정 비밀은 db-$n-app-*
  for a in $PG_APP_DBS; do
    n=${a//_/-}; tok "db-$n-app-password" >/dev/null
    putlist "db-$n-app-dsn" "postgresql://${a}_app:$(cat "$D/tokens/db-$n-app-password")@$(dbhost "$a"):5432/$a?sslmode=verify-full&sslrootcert=/etc/openit/pki/root_ca.crt"
  done
}
gen_db
# 인증기관(ADR 0060): step-ca 가 루트·중간 키를 암호화하는 비밀번호. 키 자체는 step-ca 가 처음 기동에 1회 만들어 pki-ca 볼륨에 둔다(값은 출력하지 않는다). 개행 없이 만든다(step-ca 는 파일 내용을 그대로 비밀번호로 쓴다)
[ -s "$D/tokens/step-ca-password" ] || ( umask 077; python3 -c 'import secrets;print(secrets.token_hex(24),end="")' > "$D/tokens/step-ca-password" ); secret_fix "$D/tokens/step-ca-password" step-ca-password
# 사람 인증(U82, ADR 0057): Keycloak 부트스트랩 관리자, realm openit 의 초기 admin 임시 비밀번호, OIDC 클라이언트 비밀(Keycloak 과 oauth2-proxy 가 같은 값), oauth2-proxy 쿠키 키(32자: 16·24·32바이트만 받는다)
gen_idp() {
  tok keycloak-bootstrap-admin-password >/dev/null; tok openit-initial-admin-password >/dev/null
  # oauth2-proxy 는 *_file 의 내용을 다듬지 않고 그대로 쓴다(끝 줄바꿈이 비밀 값의 일부가 되어 Keycloak 에서 invalid_client_credentials 가 났다). 이 두 파일은 줄바꿈 없이 만든다(Keycloak 래퍼는 줄바꿈을 떼므로 같은 값이다)
  [ -s "$D/tokens/oauth2-proxy-client-secret" ] || ( umask 077; python3 -c 'import secrets;print(secrets.token_hex(24),end="")' > "$D/tokens/oauth2-proxy-client-secret" ); secret_fix "$D/tokens/oauth2-proxy-client-secret" oauth2-proxy-client-secret
  [ -s "$D/tokens/oauth2-proxy-cookie-secret" ] || ( umask 077; python3 -c 'import secrets;print(secrets.token_hex(16),end="")' > "$D/tokens/oauth2-proxy-cookie-secret" ); secret_fix "$D/tokens/oauth2-proxy-cookie-secret" oauth2-proxy-cookie-secret
}
gen_idp
# Keycloak --config-file(비밀 파일): db-password 와 bootstrap-admin-password. 환경 변수로 넘기지 않는다(프로세스 환경에 값이 남는다, D84). 값이 바뀌면 다시 쓴다
kc_conf="db-password=$(tr -d '\r\n' < "$D/tokens/db-keycloak-password")"$'\n'"bootstrap-admin-password=$(tr -d '\r\n' < "$D/tokens/keycloak-bootstrap-admin-password")"
[ "$(cat "$D/keycloak-secrets.conf" 2>/dev/null)" = "$kc_conf" ] || ( umask 077; printf '%s\n' "$kc_conf" > "$D/keycloak-secrets.conf" ); secret_fix "$D/keycloak-secrets.conf" keycloak-secrets.conf; unset kc_conf
# 영역 백업(RUNTIME R10.1, CommonEnv OPENIT_BACKUP_*): 영역마다 다른 자격(HTTP 기본 인증 "<사용자>:<암호>" 한 줄, RFC 7617)과 다른 저장소 암호. 저장소 경로도 영역마다 다르다(https://backup-store/<영역>/).
# 한 영역의 자격으로 다른 영역의 저장소를 읽지 못하게 암호가 다르다. 저장소 쪽 htpasswd 는 이 자격들에서 만든다(아래, docker 가 있을 때)
gen_backup() {
  local a
  for a in survey qa ops gate; do
    [ -s "$D/tokens/backup-$a-credentials" ] || ( umask 077; printf '%s:%s\n' "$a" "$(python3 -c 'import secrets;print(secrets.token_hex(24),end="")')" > "$D/tokens/backup-$a-credentials" ); secret_fix "$D/tokens/backup-$a-credentials" "backup-$a-credentials"
    tok "backup-$a-repo-password" >/dev/null
  done
}
gen_backup
[ "$ONLY_DB" = 0 ] || { echo "PostgreSQL 비밀 위치: $D/tokens (리포지토리에 커밋하지 않는다)"; exit 0; }
# 백업 저장소(platform backup-store)의 htpasswd: 영역 자격에서 bcrypt(caddy hash-password)로 만든다. 자격이 바뀌면 다시 쓴다
gen_backup_htpasswd() {
  local a user pw line out="" img
  [ -s "$D/tokens/backup-store-htpasswd" ] && [ "$(cut -d: -f1 "$D/tokens/backup-store-htpasswd" | tr '\n' ' ')" = "survey qa ops gate " ] && return 0   # 이미 있으면 그대로(bcrypt 는 매번 달라 값 비교가 안 된다; 자격이 바뀌면 이 파일을 지우고 다시 만든다)
  img=$(sed -n 's/^GATEWAY_IMAGE=//p' "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}")
  for a in survey qa ops gate; do
    user=$(cut -d: -f1 "$D/tokens/backup-$a-credentials"); pw=$(cut -d: -f2- "$D/tokens/backup-$a-credentials" | tr -d '\r\n')
    line=$(printf '%s\n%s\n' "$pw" "$pw" | "$DOCKER" run --rm -i "$img" caddy hash-password 2>/dev/null | tail -1 | tr -d '\r\n') || return 1
    [ -n "$line" ] || return 1; out+="$user:$line"$'\n'
  done
  [ -s "$D/tokens/backup-store-htpasswd" ] && [ "$(cut -d: -f1 "$D/tokens/backup-store-htpasswd" | tr '\n' ' ')" = "survey qa ops gate " ] && return 0   # 이미 있으면 그대로(bcrypt 는 매번 달라 값 비교가 안 된다; 자격이 바뀌면 이 파일을 지우고 다시 만든다)
  ( umask 077; printf '%s' "$out" > "$D/tokens/backup-store-htpasswd" ); secret_fix "$D/tokens/backup-store-htpasswd" backup-store-htpasswd
}
gen_backup_htpasswd || { echo "백업 저장소 htpasswd 를 만들지 못했다" >&2; exit 1; }

# 서버가 받는 목록 값(역할=토큰,...): 값 하나짜리 파일로 만든다
GATE_R=$(roles gate read survey-service ops-feedback question-authoring model-lab synthetic-data model-serving release-approver operator)
GATE_W=$(roles gate write operator ops-feedback question-authoring model-lab release-gate-collector release-approver)
QA_R=$(roles qa read release-gate synthetic-data model-lab)
OPS_R=$(roles ops read synthetic-data model-lab question-authoring reviewer)
MR_R=$(roles model-registry read release-gate model-lab)
MR_W="model-lab=$(tok model-registry-write-model-lab)"
DS_R=$(roles dataset-store read model-lab)                       # I2 읽기: 소비자 model-lab 하나(ADR 0032). 쓰기 토큰으로도 읽을 수 있어 synthetic-data 는 읽기 토큰이 필요 없다
DS_W="synthetic-data=$(tok dataset-store-write-synthetic-data)"   # I2 쓰기: synthetic-data 하나(HTTP.md ## I2)
QA_AUTHOR=$(tok qa-author-e2e)
QA_REVIEWER=$(tok qa-reviewer-e2e)   # clinical-reviewer 역할(임상 근거 승인, QA_REQUIRE_TWO_PERSON=true(2인 승인)일 때만 쓰인다: 저자와 다른 주체여야 한다. 기본 false(L13)에서는 검수 경로가 이 역할에 열리지 않는다)
# survey-result-reader / survey-risk-source: survey-service 의 결과 조회(result-reader)·위험 신호 입력(risk-source) 역할 토큰(내부 호출용, 게이트웨이에 열지 않음)
# 개별 토큰(compose.yaml 의 secrets 와 같은 이름). 클라이언트(역할)와 서버가 같은 파일 값을 쓴다
for t in gate-read-survey-service ops-ingest-survey-service survey-api-kiosk survey-api-staff inference-survey-service qa-read-release-gate \
         model-registry-read-release-gate deid-salt gate-read-ops-feedback gate-write-ops-feedback ops-read-question-authoring gate-read-model-serving \
         gate-write-release-approver gate-read-release-approver ops-read-reviewer ops-review-reviewer \
         survey-result-reader survey-risk-source \
         gateway-inference-token gateway-registry-publish-token; do   # gateway-registry-publish-token: 학습 서버가 패키지를 게시할 때 게이트웨이에 내는 기계 토큰(U69)   # gateway-inference-token: 다른 호스트의 추론 서버가 게이트웨이에 내는 기계 토큰(Caddyfile @inferencemachine, ADR 0049). 서버 호스트로 옮기는 파일이다
  tok "$t" >/dev/null
done
# 목록 값 파일: 서비스가 받는 형식 그대로 한 줄. 토큰이 이미 있으면 내용이 같아서 다시 써도 같다(다르면 갱신한다).
putlist gate-read-tokens "$GATE_R"
putlist gate-write-tokens "$GATE_W"
putlist qa-read-tokens "$QA_R"
putlist ops-read-tokens "$OPS_R"
putlist model-registry-read-tokens "$MR_R"
putlist model-registry-write-tokens "$MR_W"
putlist dataset-store-read-tokens "$DS_R"
putlist dataset-store-write-tokens "$DS_W"
putlist ops-review-tokens "reviewer=$(tok ops-review-reviewer)"
tok qa-gateway-token >/dev/null   # gateway 가 저작 서비스에 쓰는 서비스 토큰(저자 경로, D88/U9). 이 토큰의 요청에서만 서비스가 X-Openit-User 를 사용자로 쓴다
putlist qa-gateway-tokens "$(tok qa-gateway-token)"
putlist qa-author-tokens "$QA_AUTHOR:author-e2e:question-author,$QA_REVIEWER:clinical-e2e:clinical-reviewer"
putlist model-runtime-tokens "survey-service=$(tok inference-survey-service)"

# 게이트웨이(Caddy): 개별 계정 인증(D85 E절)과 키오스크 기기 토큰(F절). 서비스 토큰은 위의 개별 토큰 파일을 {file./run/secrets/<이름>} 으로 읽는다(환경 변수 없음).
#   사람 계정(U82, ADR 0057): 비밀 파일이 아니라 Keycloak(realm openit)에 있다. 여기서 만드는 것은 Keycloak·oauth2-proxy 의 비밀(위 gen_idp)뿐이다.
#   기기: tokens/kiosk-device-<id> -> secrets/gateway-devices.caddy. 기본은 기기 0대(--test-fixtures 에서만 시험 기기 e2e 등). 더하려면 scripts/kiosk-add-device.sh add <id>
source "$(dirname "$0")/gateway-lib.sh"
if [ $TEST_FIX = 1 ]; then ( umask 077; : > "$D/.test-fixtures" ); fi
[ -e "$D/.test-fixtures" ] && TEST_FIX=1   # 표시가 있는 폴더는 시험 폴더로 계속 취급한다
[ $TEST_FIX = 0 ] || tok kiosk-device-e2e >/dev/null
# 시험 사용자(test/gateway-oidc/accounts.test.conf)의 로그인 암호: 호스트 전용(600). E2E·데모가 Keycloak 에 사용자를 만들 때(scripts/idp-test-users.sh)와 로그인할 때 읽는다. 운영 realm 에는 들어가지 않는다
[ $TEST_FIX = 0 ] || while read -r _acc _; do case "$_acc" in ""|\#*) continue;; esac; tok "idp-test-$_acc-password" >/dev/null; done < "$DEPLOY_ROOT/test/gateway-oidc/accounts.test.conf"
# E2E 단계 5d(기기 사이 세션 격리, 폐기): 시험 기기 a·b 와 폐기 시험용 c. 운영에서는 kiosk-add-device.sh 로 실제 기기만 만든다(이 시험 기기는 운영 비밀 폴더에서 remove 한다)
[ $TEST_FIX = 0 ] || for _d in e2e-a e2e-b e2e-c; do tok "kiosk-device-$_d" >/dev/null; done
gw_write_devices "$D"
old=$(cd "$D" && ls *.env 2>/dev/null | tr '\n' ' ') || true
[ -z "$old" ] || echo "알림: 예전 방식의 비밀 env 파일이 남아 있다($old). 더는 쓰지 않는다(환경 변수로 평문이 노출됐다). 지워도 된다: (cd $D && rm -f $old)" >&2
echo "비밀 값 위치: $D (리포지토리에 커밋하지 않는다)"
