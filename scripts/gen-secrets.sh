#!/usr/bin/env bash
# 서비스 토큰과 salt를 만든다. 사용: gen-secrets.sh [디렉터리]  (기본 secrets/, gitignore). 이미 있는 파일은 건드리지 않는다.
# CONVENTIONS 9절: 서버는 토큰에 역할을 묶는다. 호출하는 영역마다 다른 읽기 토큰, 쓰기 토큰은 역할마다 하나.
# secrets/tokens/<이름> : 비밀 값 하나가 파일 하나(개별 토큰, 서버가 받는 목록 값 "역할=토큰,...", salt, 콘솔 암호).
#   compose.yaml 의 최상위 secrets 가 이 파일을 /run/secrets/<이름> 에 마운트하고, 서비스는 NAME_FILE 경로로만 읽는다(D84).
#   예전 방식 secrets/<서비스>.env(환경 변수로 토큰 주입)는 없앴다: 남아 있으면 지워도 된다(아래에서 알려 준다).
# PostgreSQL: tokens/postgres-password(슈퍼유저), tokens/db-<이름>-password(서비스 계정 암호), tokens/db-<이름>-dsn(접속 문자열 한 줄,
#   postgresql://<계정>:<암호>@postgres:5432/<데이터베이스>). 이름 규칙은 docs/RUN.md 4-1-1. DSN 은 암호가 바뀌면 같이 갱신된다.
#   --db-only : PostgreSQL 비밀만 만든다(caddy 이미지가 필요 없다. 시험·개발용).  사용: gen-secrets.sh [--db-only] [디렉터리]
# 권한: 디렉터리 700(호스트 다른 사용자 차단). 파일은 secret_mode(lib.sh): 컨테이너가 읽는 것은 644, 호스트에서만 쓰는 것(계정 암호·해시, 기기 토큰 원본)은 600.
#   컨테이너가 읽는 파일을 600 으로 만들지 못하는 이유: compose 의 파일 secrets 는 호스트 소유자·모드를 그대로 마운트하고 uid/gid/mode 옵션은 적용되지 않아(측정함),
#   uid 10001 인 컨테이너가 호스트 사용자 소유 600 파일을 읽지 못한다. docs/adr/0022-secret-file-permissions.md. 이미 있는 파일의 모드도 실행할 때마다 바로잡는다.
#   --drop-plaintext : 해시가 있는 계정의 평문 암호 파일(account-<id>-password)을 지운다(운영: 전달한 뒤 평문을 디스크에 남기지 않는다). 회전은 scripts/rotate-account.sh
set -euo pipefail
ONLY_DB=0; DROP_PLAIN=0
while [ "${1:-}" = "--db-only" ] || [ "${1:-}" = "--drop-plaintext" ]; do case "$1" in --db-only) ONLY_DB=1;; --drop-plaintext) DROP_PLAIN=1;; esac; shift; done
[ "$ONLY_DB" = 1 ] && DEPLOY_NO_DOCKER=1   # --db-only 는 docker 를 쓰지 않는다
source "$(dirname "$0")/lib.sh"
D=${1:-$DEPLOY_ROOT/secrets}; mkdir -p "$D/tokens"; chmod 700 "$D" "$D/tokens"
rnd() { python3 -c 'import secrets;print(secrets.token_hex(24))'; }
tok() { [ -s "$D/tokens/$1" ] || ( umask 077; rnd > "$D/tokens/$1" ); chmod "$(secret_mode "$1")" "$D/tokens/$1"; cat "$D/tokens/$1"; }
putlist() { local f="$D/tokens/$1"; [ "$(cat "$f" 2>/dev/null)" = "$2" ] || ( umask 077; printf '%s\n' "$2" > "$f" ); chmod "$(secret_mode "$1")" "$f"; }
roles() { local srv=$1 kind=$2; shift 2; local out=""; for r in "$@"; do out+="${out:+,}$r=$(tok "$srv-$kind-$r")"; done; echo "$out"; }

# PostgreSQL 계정: 이름 = 데이터베이스 = 계정. 환경 변수 이름은 docs/RUN.md 4-1-1 표(SURVEY_DATABASE_URL 등)
gen_db() {
  tok postgres-password >/dev/null
  local a n
  for a in survey qa ops_log ops_failure gate; do
    n=${a//_/-}; tok "db-$n-password" >/dev/null
    putlist "db-$n-dsn" "postgresql://$a:$(cat "$D/tokens/db-$n-password")@postgres:5432/$a"
  done
}
gen_db
[ "$ONLY_DB" = 0 ] || { echo "PostgreSQL 비밀 위치: $D/tokens (리포지토리에 커밋하지 않는다)"; exit 0; }

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
QA_REVIEWER=$(tok qa-reviewer-e2e)   # clinical-reviewer 역할(임상 근거 승인, 4-eyes: 저자와 다른 주체여야 한다, question-authoring D88/U9)
# survey-result-reader / survey-risk-source: survey-service 의 결과 조회(result-reader)·위험 신호 입력(risk-source) 역할 토큰(내부 호출용, 게이트웨이에 열지 않음)
# 개별 토큰(compose.yaml 의 secrets 와 같은 이름). 클라이언트(역할)와 서버가 같은 파일 값을 쓴다
for t in gate-read-survey-service ops-ingest-survey-service survey-api-kiosk survey-api-staff inference-survey-service qa-read-release-gate \
         model-registry-read-release-gate deid-salt gate-read-ops-feedback gate-write-ops-feedback ops-read-question-authoring gate-read-model-serving \
         gate-write-release-approver gate-read-release-approver ops-read-reviewer ops-review-reviewer \
         survey-result-reader survey-risk-source; do
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
#   계정/역할: config/gateway-accounts.conf -> secrets/gateway-accounts.caddy (암호·해시는 tokens/account-<id>-password / -hash). 개발/E2E용 시험 계정, 운영 방식(OIDC)은 병원 IdP 가 정해진 뒤 교체
#   기기: tokens/kiosk-device-<id> -> secrets/gateway-devices.caddy. 기본으로 시험 기기 e2e 하나. 더하려면 scripts/kiosk-add-device.sh add <id>
source "$(dirname "$0")/gateway-lib.sh"
gw_write_accounts "$D"
tok kiosk-device-e2e >/dev/null
# E2E 단계 5d(기기 사이 세션 격리, 폐기): 시험 기기 a·b 와 폐기 시험용 c. 운영에서는 kiosk-add-device.sh 로 실제 기기만 만든다(이 시험 기기는 운영 비밀 폴더에서 remove 한다)
for _d in e2e-a e2e-b e2e-c; do tok "kiosk-device-$_d" >/dev/null; done
gw_write_devices "$D"
old=$(cd "$D" && ls *.env 2>/dev/null | tr '\n' ' ') || true
[ -z "$old" ] || echo "알림: 예전 방식의 비밀 env 파일이 남아 있다($old). 더는 쓰지 않는다(환경 변수로 평문이 노출됐다). 지워도 된다: (cd $D && rm -f $old)" >&2
if [ $DROP_PLAIN = 1 ]; then
  for f in "$D"/tokens/account-*-password; do [ -e "$f" ] || continue; h="${f%-password}-hash"; [ -s "$h" ] && rm -f "$f" && echo "평문 암호 파일을 지웠다(해시만 남김): $(basename "$f")" >&2; done
fi
echo "비밀 값 위치: $D (리포지토리에 커밋하지 않는다)"
