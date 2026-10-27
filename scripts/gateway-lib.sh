#!/usr/bin/env bash
# 게이트웨이 인증 비밀 만들기(gen-secrets.sh, kiosk-add-device.sh 가 source 한다). 암호·해시·토큰 값은 출력하지 않는다.
#  gw_write_accounts <비밀 폴더>  : config/gateway-accounts.conf 의 계정마다 암호(account-<id>-password)와 bcrypt 해시(account-<id>-hash)를 보장하고
#                                   secrets/gateway-accounts.caddy 를 쓴다. (authenticate) = 인증 블록, (role_matchers) = 계정 -> 역할.
#                                   OIDC 로 바꿀 때 교체하는 것은 이 파일의 (authenticate) 블록(그리고 역할을 IdP 클레임에서 얻으면 (role_matchers))뿐이다.
#  gw_write_devices <비밀 폴더>   : tokens/kiosk-device-<id> 파일마다 한 기기. secrets/gateway-devices.caddy 의 (kiosk_devices) 가 @device_ok 를 정의한다.
#                                   기기 토큰 파일을 지우고 다시 쓰면 그 기기는 폐기된다(게이트웨이를 다시 시작해야 반영: Caddy 는 설정을 읽을 때 한 번 치환한다).
# 파일은 같은 inode 로 덮어쓴다(compose configs 가 파일을 바인드 마운트하므로 새 파일로 바꾸면 컨테이너가 못 본다).
GW_ROLES="staff operator release-approver reviewer"
gw_rnd() { python3 -c 'import secrets;print(secrets.token_hex(24))'; }
gw_accounts_conf() { echo "${GATEWAY_ACCOUNTS_CONF:-$DEPLOY_ROOT/config/gateway-accounts.conf}"; }
gw_parse_accounts() { # 줄마다 "<id> <역할,역할>" 을 낸다. 규칙 위반이면 실패
  local conf; conf=$(gw_accounts_conf); [ -f "$conf" ] || die "계정 설정이 없다: $conf"
  python3 -I - "$conf" "$GW_ROLES" <<'PY'
import re, sys
roles = set(sys.argv[2].split()); seen = set(); n = 0
for i, line in enumerate(open(sys.argv[1], encoding="utf-8"), 1):
    s = line.split("#", 1)[0].split()
    if not s: continue
    if len(s) != 2: sys.exit(f"{sys.argv[1]}:{i}: '<계정> <역할[,역할]>' 형식이 아니다")
    acc, rs = s[0], s[1].split(",")
    if not re.fullmatch(r"[a-z][a-z0-9._-]{1,31}", acc): sys.exit(f"{sys.argv[1]}:{i}: 계정 ID 규칙 위반 '{acc}'")
    if acc in seen: sys.exit(f"{sys.argv[1]}:{i}: 계정이 겹친다 '{acc}'")
    bad = [r for r in rs if r not in roles]
    if bad: sys.exit(f"{sys.argv[1]}:{i}: 모르는 역할 {bad} (가능: {sorted(roles)})")
    seen.add(acc); n += 1; print(acc, ",".join(rs))
if n == 0: sys.exit("계정이 하나도 없다")
PY
}
gw_write_accounts() {
  local D=$1 acc rs f GW_IMG list; list=$(gw_parse_accounts) || exit 1
  local body="" roles_body="" r ids
  while read -r acc rs; do
    [ -s "$D/tokens/account-$acc-password" ] || gw_rnd > "$D/tokens/account-$acc-password"; chmod 644 "$D/tokens/account-$acc-password"
    if [ ! -s "$D/tokens/account-$acc-hash" ]; then
      GW_IMG=${GW_IMG:-$(sed -n 's/^GATEWAY_IMAGE=//p' "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}")}
      "$DOCKER" run --rm "$GW_IMG" caddy hash-password --plaintext "$(cat "$D/tokens/account-$acc-password")" | tr -d '\r\n' > "$D/tokens/account-$acc-hash"
      [ -s "$D/tokens/account-$acc-hash" ] || { rm -f "$D/tokens/account-$acc-hash"; die "caddy hash-password 실패($acc)"; }
      chmod 644 "$D/tokens/account-$acc-hash"
    fi
    body+=$'\t\t'"$acc $(cat "$D/tokens/account-$acc-hash")"$'\n'
  done <<<"$list"
  for r in $GW_ROLES; do
    ids=$(awk -v r="$r" '{n=split($2,a,","); for(i=1;i<=n;i++) if(a[i]==r) printf "%s\"%s\"", (c++?",":""), $1}' <<<"$list")
    roles_body+=$'\t@role_'"${r//release-/}"' expression `{http.auth.user.id} in ['"$ids"']`'$'\n'
  done
  [ -e "$D/gateway-accounts.caddy" ] || : > "$D/gateway-accounts.caddy"
  { printf '# 생성됨(scripts/gen-secrets.sh, 계정 목록은 config/gateway-accounts.conf). 직접 고치지 않는다. 해시만 있고 암호는 없다.\n'
    printf '(authenticate) {\n\tbasic_auth {\n%s\t}\n}\n' "$body"
    printf '(role_matchers) {\n%s}\n' "$roles_body"; } > "$D/gateway-accounts.caddy"
  chmod 644 "$D/gateway-accounts.caddy"
}
gw_devices() { ls "$1/tokens" 2>/dev/null | sed -n 's/^kiosk-device-\(.*\)$/\1/p'; }
gw_write_devices() {
  local D=$1 id vals=""
  for id in $(gw_devices "$D"); do [ -s "$D/tokens/kiosk-device-$id" ] && vals+=" \"Bearer $(tr -d '\r\n' < "$D/tokens/kiosk-device-$id")\""; done
  [ -e "$D/gateway-devices.caddy" ] || : > "$D/gateway-devices.caddy"
  { printf '# 생성됨(scripts/gen-secrets.sh, scripts/kiosk-add-device.sh). 기기 토큰 목록이라 비밀이다. 직접 고치지 않는다.\n'
    if [ -n "$vals" ]; then printf '(kiosk_devices) {\n\t@device_ok header Authorization%s\n}\n' "$vals"
    else printf '(kiosk_devices) {\n\t@device_ok expression false\n}\n'; fi; } > "$D/gateway-devices.caddy"
  chmod 644 "$D/gateway-devices.caddy"
}
