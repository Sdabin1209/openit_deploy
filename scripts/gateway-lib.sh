#!/usr/bin/env bash
# 게이트웨이 인증 비밀 만들기(gen-secrets.sh, kiosk-add-device.sh 가 source 한다). 암호·해시·토큰 값은 출력하지 않는다.
#  gw_write_devices <비밀 폴더>   : tokens/kiosk-device-<id> 파일마다 한 기기. secrets/gateway-devices.caddy 의 (kiosk_devices) 가 @device_ok 를 정의한다.
#                                   기기 토큰 파일을 지우고 다시 쓰면 그 기기는 폐기된다(게이트웨이를 다시 시작해야 반영: Caddy 는 설정을 읽을 때 한 번 치환한다).
# 파일은 같은 inode 로 덮어쓴다(compose configs 가 파일을 바인드 마운트하므로 새 파일로 바꾸면 컨테이너가 못 본다).
gw_rnd() { python3 -c 'import secrets;print(secrets.token_hex(24))'; }
gw_devices() { ls "$1/tokens" 2>/dev/null | sed -n 's/^kiosk-device-\(.*\)$/\1/p'; }
gw_write_devices() {
  local D=$1 id vals=""
  for id in $(gw_devices "$D"); do [ -s "$D/tokens/kiosk-device-$id" ] && vals+="${vals:+, }\"Bearer $(tr -d '\r\n' < "$D/tokens/kiosk-device-$id")\""; done
  [ -e "$D/gateway-devices.caddy" ] || : > "$D/gateway-devices.caddy"
  { printf '# 생성됨(scripts/gen-secrets.sh, scripts/kiosk-add-device.sh). 기기 토큰 목록이라 비밀이다. 직접 고치지 않는다.\n'
    if [ -n "$vals" ]; then printf '(kiosk_devices) {\n\t@device_ok expression {http.request.header.Authorization} in [%s]\n}\n' "$vals"
    else printf '(kiosk_devices) {\n\t@device_ok expression false\n}\n'; fi; } > "$D/gateway-devices.caddy"
  chmod 640 "$D/gateway-devices.caddy"; chgrp "${SECRETS_GID:-$(id -g)}" "$D/gateway-devices.caddy" 2>/dev/null || true
  # survey-service 의 기기별 토큰 표(SURVEY_KIOSK_DEVICE_TOKENS, 줄마다 device_id=토큰, D88/U8): gateway 는 검증한 기기 토큰을 그대로 survey 에 넘기고(Authorization 을 바꾸지 않는다)
  # survey 가 같은 표로 검증해 세션을 만든 기기만 그 세션에 접근하게 한다. 비밀이고 기존 secrets 규칙(폴더 700, 파일 644)을 따른다. 기기를 바꾸면 survey-service 도 다시 시작해야 표가 바뀐다.
  : > "$D/tokens/survey-kiosk-device-tokens"
  for id in $(gw_devices "$D"); do [ -s "$D/tokens/kiosk-device-$id" ] && printf '%s=%s\n' "$id" "$(tr -d '\r\n' < "$D/tokens/kiosk-device-$id")" >> "$D/tokens/survey-kiosk-device-tokens"; done
  chmod 640 "$D/tokens/survey-kiosk-device-tokens"; chgrp "${SECRETS_GID:-$(id -g)}" "$D/tokens/survey-kiosk-device-tokens" 2>/dev/null || true
}
