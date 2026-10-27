#!/usr/bin/env bash
# 게이트웨이 계정 암호 회전. 사용: rotate-account.sh <계정 ID> [--apply]     환경: SECRETS_DIR(기본 secrets/), DEPLOY_PROJECT(기본 deploy)
# 새 무작위 암호를 만들어 bcrypt 해시만 디스크에 쓰고(account-<id>-hash 600, 평문 파일은 남기지 않는다), 게이트웨이 계정 파일을 다시 쓴다.
# 새 암호는 **표준 출력에 한 번만** 나온다: 사람이 터미널에서 실행해 해당 직원에게 전달한다(에이전트·로그·CI 에서 실행하지 않는다).
# 한계: 해시 생성 때 암호가 docker run 인자로 호스트 프로세스 목록에 아주 잠깐 보인다(같은 호스트 사용자만 볼 수 있다). 근거와 대안: docs/adr/0022-secret-file-permissions.md.
#   --apply : 게이트웨이를 다시 시작해 반영한다(Caddy 는 시작할 때 계정 파일을 읽는다). 없으면 파일만 바꾸고 안내한다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"; source "$(dirname "$0")/gateway-lib.sh"
D=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}; ID=${1:-}; APPLY=0; [ "${2:-}" = --apply ] && APPLY=1
[ -d "$D/tokens" ] || die "비밀 폴더가 없다: $D/tokens"
[[ "$ID" =~ ^[a-z][a-z0-9._-]{1,31}$ ]] || die "사용: rotate-account.sh <계정 ID> [--apply] (config/gateway-accounts.conf 의 계정)"
gw_parse_accounts | awk -v a="$ID" '$1==a{f=1} END{exit !f}' || die "config/gateway-accounts.conf 에 없는 계정: $ID"
GW_IMG=$(sed -n 's/^GATEWAY_IMAGE=//p' "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}")
PW=$(gw_rnd)
H=$(printf '%s\n%s\n' "$PW" "$PW" | "$DOCKER" run --rm -i "$GW_IMG" caddy hash-password 2>/dev/null | tail -1 | tr -d '\r\n')   # 표준 입력(점검 L6: 인자는 ps 에 보인다); [ -n "$H" ] || die "caddy hash-password 실패"
( umask 077; printf '%s' "$H" > "$D/tokens/account-$ID-hash.new" ); mv "$D/tokens/account-$ID-hash.new" "$D/tokens/account-$ID-hash"; chmod 600 "$D/tokens/account-$ID-hash"
rm -f "$D/tokens/account-$ID-password"
gw_write_accounts "$D"
echo "회전함: $ID (해시만 저장, 평문 파일 없음). 새 암호는 아래 한 줄이다. 전달하고 터미널 기록에서 지운다:" >&2
printf '%s\n' "$PW"
if [ $APPLY = 1 ]; then dc "${DEPLOY_PROJECT:-deploy}" restart gateway >/dev/null && echo "게이트웨이를 다시 시작했다" >&2
else echo "반영하려면 게이트웨이를 다시 시작한다: docker compose -p ${DEPLOY_PROJECT:-deploy} restart gateway (또는 --apply)" >&2; fi
