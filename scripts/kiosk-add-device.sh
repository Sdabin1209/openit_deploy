#!/usr/bin/env bash
# 키오스크 기기 토큰 관리(D85 F절). 사용: kiosk-add-device.sh add <기기 ID> | remove <기기 ID> | list | sync   [--apply]
#   add    : secrets/tokens/kiosk-device-<ID> 에 기기 토큰을 만들고(이미 있으면 그대로) 게이트웨이 목록을 다시 쓴다. 값은 출력하지 않고 파일 경로만 알린다.
#            기기에는 그 파일의 값을 기기 설정이나 시작 URL 조각(#)으로 한 번 전하고, 앱은 Authorization: Bearer 로 보낸다(URL 쿼리 금지).
#   remove : 토큰 파일을 지워 폐기하고 목록을 다시 쓴다.      sync : 파일을 직접 지웠을 때 목록만 다시 쓴다.      list : 기기 ID 목록.
#   --apply: 목록을 쓴 뒤 게이트웨이를 다시 시작해 반영한다(DEPLOY_PROJECT, 기본 deploy). Caddy 가 설정을 읽을 때 한 번 치환해 다시 시작해야 반영된다.
#   환경: SECRETS_DIR(기본 secrets/)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/gateway-lib.sh"
D=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}; [ -d "$D/tokens" ] || die "비밀 폴더가 없다: $D/tokens (먼저 scripts/gen-secrets.sh)"
CMD=${1:-}; ID=${2:-}; APPLY=0; for x in "$@"; do [ "$x" = --apply ] && APPLY=1; done
case "$CMD" in
  add|remove) [[ "$ID" =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]] || die "기기 ID 규칙: 소문자·숫자·- (1~32자): '$ID'";;
  list|sync) ;;
  *) die "사용: kiosk-add-device.sh add|remove <기기 ID> | list | sync [--apply]";;
esac
case "$CMD" in
  add) f="$D/tokens/kiosk-device-$ID"; [ -s "$f" ] && echo "이미 있다: $ID (토큰은 그대로)" >&2 || { gw_rnd > "$f"; echo "기기 토큰을 만들었다: $ID" >&2; }; chmod 644 "$f"; echo "토큰 파일: $f (값은 출력하지 않는다)" >&2;;
  remove) rm -f "$D/tokens/kiosk-device-$ID"; echo "폐기: $ID" >&2;;
  list) gw_devices "$D"; exit 0;;
esac
gw_write_devices "$D"
echo "게이트웨이 기기 목록을 다시 썼다($(gw_devices "$D" | wc -l)대)" >&2
if [ $APPLY = 1 ]; then dc "${DEPLOY_PROJECT:-deploy}" restart gateway >/dev/null && echo "게이트웨이를 다시 시작했다" >&2
else echo "반영하려면 게이트웨이를 다시 시작한다: dc ... restart gateway (또는 --apply)" >&2; fi
