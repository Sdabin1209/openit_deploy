#!/usr/bin/env bash
# 게이트웨이 인증 비밀 만들기(gen-secrets.sh, kiosk-add-device.sh 가 source 한다). 암호·해시·토큰 값은 출력하지 않는다.
#  gw_write_devices <비밀 폴더>   : devices/<device_id> 파일마다 한 기기(내용 = 토큰 한 줄, 계약 INGRESS_DEVICE_TOKENS_DIR). 파일을 지우면 그 기기는 폐기된다. survey 기기 토큰 표를 같이 다시 쓴다.
# 파일은 같은 inode 로 덮어쓴다(compose configs 가 파일을 바인드 마운트하므로 새 파일로 바꾸면 컨테이너가 못 본다).
gw_rnd() { python3 -c 'import secrets;print(secrets.token_hex(24))'; }
gw_devices() { ls "$1/devices" 2>/dev/null; }
gw_write_devices() {
  local D=$1 id
  # 왜 기기마다 파일 하나인가: 계약 PublicIngressEnv.INGRESS_DEVICE_TOKENS_DIR(3.4.10) 의 형식이다: 파일 이름 = device_id, 내용 = 토큰 한 줄, 파일을 지우면 폐기, 0개도 유효.
  # 목록 파일(gateway-devices.caddy)은 더 만들지 않는다: 공개 입구는 폴더를 읽는다(구조 규칙 6: deploy 가 이웃 입력 모양을 정하지 않는다).
  mkdir -p "$D/devices"; chmod 750 "$D/devices"; chgrp "${SECRETS_GID:-$(id -g)}" "$D/devices" 2>/dev/null || true
  for id in $(gw_devices "$D"); do chmod 640 "$D/devices/$id"; chgrp "${SECRETS_GID:-$(id -g)}" "$D/devices/$id" 2>/dev/null || true; done
  # survey-service 의 기기별 토큰 표(SURVEY_KIOSK_DEVICE_TOKENS, 줄마다 device_id=토큰, D88/U8): 같은 기기 폴더에서 만든다. 기기를 바꾸면 survey-service 도 다시 시작해야 표가 바뀐다.
  : > "$D/tokens/survey-kiosk-device-tokens"
  for id in $(gw_devices "$D"); do [ -s "$D/devices/$id" ] && printf '%s=%s\n' "$id" "$(tr -d '\r\n' < "$D/devices/$id")" >> "$D/tokens/survey-kiosk-device-tokens"; done
  chmod 640 "$D/tokens/survey-kiosk-device-tokens"; chgrp "${SECRETS_GID:-$(id -g)}" "$D/tokens/survey-kiosk-device-tokens" 2>/dev/null || true
}
