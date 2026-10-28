#!/usr/bin/env bash
# 조직이 준 직원 계정 파일(secrets/staff-accounts.conf)을 검사하고 게이트웨이 계정 조각(secrets/gateway-accounts.caddy)을 다시 쓴다(ADR 0039).
# 사용: apply-accounts.sh [--apply]     환경: SECRETS_DIR(기본 secrets/), GATEWAY_ACCOUNTS_CONF(파일 경로), DEPLOY_PROJECT(기본 deploy)
#   --apply : 게이트웨이를 다시 시작해 반영한다(Caddy 는 시작할 때 계정 파일을 읽는다). 없으면 파일만 바꾸고 안내한다.
# 이 프로젝트는 계정을 발급하지 않고 암호를 만들지 않는다. 해시는 출력하지 않는다(계정 ID와 역할만). 형식: config/staff-accounts.conf.example
set -euo pipefail
DEPLOY_NO_DOCKER=1; source "$(dirname "$0")/lib.sh"; source "$(dirname "$0")/gateway-lib.sh"
APPLY=0; for a in "$@"; do case "$a" in --apply) APPLY=1;; -h|--help) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0;; *) die "알 수 없는 인자: $a (사용: apply-accounts.sh [--apply])";; esac; done
D=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}
[ -d "$D/tokens" ] || die "비밀 폴더가 없다: $D/tokens (먼저 scripts/gen-secrets.sh)"
[ -e "$D/.test-fixtures" ] && GW_TEST_FIXTURES=1
F=$(gw_accounts_conf)
[ -f "$F" ] || echo "알림: 조직이 준 계정 파일이 없다($F). 계정이 0개라 사람 인증 경로는 모두 401 이다. 형식: config/staff-accounts.conf.example" >&2
list=$(gw_parse_accounts) || exit 1   # 형식·역할·해시 검사. 실패하면 기존 gateway-accounts.caddy 를 바꾸지 않는다
gw_write_accounts "$D"
n=$(grep -c . <<<"$list" || true)
echo "계정 조각을 다시 썼다: $D/gateway-accounts.caddy (계정 ${n}개)"; awk 'NF{print "  - " $1 " [" $2 "]"}' <<<"$list"
if [ $APPLY = 1 ]; then DEPLOY_NO_DOCKER=0; detect_docker; dc "${DEPLOY_PROJECT:-deploy}" restart gateway >/dev/null && echo "게이트웨이를 다시 시작했다"
else echo "반영하려면 게이트웨이를 다시 시작한다: docker compose -p ${DEPLOY_PROJECT:-deploy} restart gateway (또는 --apply)"; fi
