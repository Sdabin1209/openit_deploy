#!/usr/bin/env bash
# 게이트웨이 인증 비밀 만들기(gen-secrets.sh, kiosk-add-device.sh 가 source 한다). 암호·해시·토큰 값은 출력하지 않는다.
#  gw_write_accounts <비밀 폴더>  : 조직이 주는 직원 계정 파일(secrets/staff-accounts.conf: `<계정> <역할[,역할]> <bcrypt 해시>`, 이 프로젝트는 계정을 발급하지 않는다, ADR 0039)로
#                                   secrets/gateway-accounts.caddy 를 쓴다. (authenticate) = 인증 블록(조직이 준 해시 그대로), (role_matchers) = 계정 -> 역할.
#                                   시험 폴더(GW_TEST_FIXTURES=1)에서만 gateway-accounts.test.conf 의 시험 계정(*-e2e)에 무작위 암호와 해시를 만들어 더한다(E2E 로그인용, 운영 아님).
#                                   OIDC 로 바꿀 때 교체하는 것은 이 파일의 (authenticate) 블록(그리고 역할을 IdP 클레임에서 얻으면 (role_matchers))뿐이다.
#  gw_write_devices <비밀 폴더>   : tokens/kiosk-device-<id> 파일마다 한 기기. secrets/gateway-devices.caddy 의 (kiosk_devices) 가 @device_ok 를 정의한다.
#                                   기기 토큰 파일을 지우고 다시 쓰면 그 기기는 폐기된다(게이트웨이를 다시 시작해야 반영: Caddy 는 설정을 읽을 때 한 번 치환한다).
# 파일은 같은 inode 로 덮어쓴다(compose configs 가 파일을 바인드 마운트하므로 새 파일로 바꾸면 컨테이너가 못 본다).
GW_ROLES="staff operator release-approver reviewer author clinical-reviewer"
gw_rnd() { python3 -c 'import secrets;print(secrets.token_hex(24))'; }
gw_accounts_conf() { echo "${GATEWAY_ACCOUNTS_CONF:-${GW_SECRETS_DIR:-${SECRETS_DIR:-$DEPLOY_ROOT/secrets}}/staff-accounts.conf}"; }   # 조직이 주는 직원 계정 파일(해시가 있어 secrets/ 에 둔다, 커밋하지 않는다)
gw_test_accounts_conf() { echo "${GATEWAY_TEST_ACCOUNTS_CONF:-$DEPLOY_ROOT/config/gateway-accounts.test.conf}"; }   # 시험 계정: GW_TEST_FIXTURES=1 일 때만 더해 읽는다
gw_parse_accounts() { # 줄마다 "<id> <역할,역할> <bcrypt 해시|->" 를 낸다(시험 계정은 해시 자리에 -). 규칙 위반이면 실패
  # 운영 파일(조직이 줌)은 없어도 오류가 아니다: 계정이 하나도 없으면 (authenticate)는 모두 거부한다(gw_write_accounts). 시험 계정 파일은 GW_TEST_FIXTURES=1 일 때만 더한다
  local conf test=""; conf=$(gw_accounts_conf)
  if [ "${GW_TEST_FIXTURES:-0}" = 1 ]; then test=$(gw_test_accounts_conf); [ -f "$test" ] || die "시험 계정 설정이 없다: $test"; fi
  python3 -I - "$GW_ROLES" "$conf" "$test" <<'PY'
import os, re, sys
roles = set(sys.argv[1].split()); seen = set()
BCRYPT = re.compile(r"\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}")   # bcrypt: 버전, 비용, 22자 salt + 31자 해시 (Caddy basic_auth 가 받는 형식, RFC 7617 Basic 의 암호 저장)
def read(path, with_hash):
  if not path or not os.path.exists(path): return
  if with_hash and os.stat(path).st_mode & 0o022: sys.exit(f"{path}: 그룹/다른 사용자가 쓸 수 있다(모드 {oct(os.stat(path).st_mode & 0o777)}). chmod go-w 로 고친다")
  for i, line in enumerate(open(path, encoding="utf-8"), 1):
    s = line.split("#", 1)[0].split()
    if not s: continue
    want = 3 if with_hash else 2
    if len(s) != want: sys.exit(f"{path}:{i}: '<계정> <역할[,역할]>" + (" <bcrypt 해시>" if with_hash else "") + "' 형식이 아니다")
    acc, rs = s[0], s[1].split(",")
    if not re.fullmatch(r"[a-z][a-z0-9._-]{1,31}", acc): sys.exit(f"{path}:{i}: 계정 ID 규칙 위반 '{acc}'")
    if acc in seen: sys.exit(f"{path}:{i}: 계정이 겹친다 '{acc}'")
    bad = [r for r in rs if r not in roles]
    if bad: sys.exit(f"{path}:{i}: 모르는 역할 {bad} (가능: {sorted(roles)})")
    if with_hash and not BCRYPT.fullmatch(s[2]): sys.exit(f"{path}:{i}: {acc} 의 해시가 bcrypt 형식($2a$/$2b$/$2y$ + 비용 + 53자)이 아니다. 평문 암호를 넣지 않는다: caddy hash-password 로 만든 해시를 받는다")
    seen.add(acc); print(acc, ",".join(rs), s[2] if with_hash else "-")
read(sys.argv[2], True); read(sys.argv[3], False)
PY
}
gw_write_accounts() {
  local D=$1 acc rs f GW_IMG list GW_SECRETS_DIR=$1; [ -e "$D/.test-fixtures" ] && GW_TEST_FIXTURES=1   # 시험 비밀 폴더(gen-secrets.sh --test-fixtures 가 표시)는 재실행·회전에서도 시험 계정을 유지한다
  list=$(gw_parse_accounts) || exit 1
  local body="" roles_body="" r ids
  while read -r acc rs given; do
    [ -n "$acc" ] || continue   # 계정이 없으면 빈 줄 하나가 들어온다
    if [ "$given" != "-" ]; then body+=$'\t\t'"$acc $given"$'\n'; continue; fi   # 조직이 준 bcrypt 해시를 그대로 쓴다(암호·해시 파일을 만들지 않는다)
    # 아래는 시험 계정(*-e2e)뿐이다. 평문 암호는 해시가 아직 없을 때만 만든다(이미 해시가 있고 평문을 지웠다면 되살리지 않는다: 평문이 디스크에 남는 것을 최소화). 호스트 전용이라 600
    [ -s "$D/tokens/account-$acc-hash" ] || { [ -s "$D/tokens/account-$acc-password" ] || ( umask 077; gw_rnd > "$D/tokens/account-$acc-password" ); chmod 600 "$D/tokens/account-$acc-password"; }
    if [ ! -s "$D/tokens/account-$acc-hash" ]; then
      GW_IMG=${GW_IMG:-$(sed -n 's/^GATEWAY_IMAGE=//p' "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}")}
      { pw=$(cat "$D/tokens/account-$acc-password"); printf '%s\n%s\n' "$pw" "$pw" | "$DOCKER" run --rm -i "$GW_IMG" caddy hash-password 2>/dev/null | tail -1 | tr -d '\r\n' > "$D/tokens/account-$acc-hash"; unset pw; }   # 암호는 docker run 인자(ps 에 보임)가 아니라 표준 입력으로 준다(점검 L6)
      [ -s "$D/tokens/account-$acc-hash" ] || { rm -f "$D/tokens/account-$acc-hash"; die "caddy hash-password 실패($acc)"; }
      chmod 600 "$D/tokens/account-$acc-hash"
    fi
    chmod 600 "$D/tokens/account-$acc-hash"; [ ! -e "$D/tokens/account-$acc-password" ] || chmod 600 "$D/tokens/account-$acc-password"   # 예전에 644 로 만든 것도 바로잡는다
    body+=$'\t\t'"$acc $(cat "$D/tokens/account-$acc-hash")"$'\n'
  done <<<"$list"
  for r in $GW_ROLES; do
    ids=$(awk -v r="$r" '{n=split($2,a,","); for(i=1;i<=n;i++) if(a[i]==r) printf "%s\"%s\"", (c++?",":""), $1}' <<<"$list")
    if [ -n "$ids" ]; then roles_body+=$'\t@role_'"${r//release-/}"' expression `{http.auth.user.id} in ['"$ids"']`'$'\n'
    else roles_body+=$'\t@role_'"${r//release-/}"' expression false'$'\n'; fi
  done
  [ -e "$D/gateway-accounts.caddy" ] || : > "$D/gateway-accounts.caddy"
  { printf '# 생성됨(scripts/gen-secrets.sh, scripts/apply-accounts.sh; 계정 목록은 조직이 주는 secrets/staff-accounts.conf). 직접 고치지 않는다. 해시만 있고 암호는 없다.\n'
    # 계정이 없으면 아무도 통과할 수 없는 자리표시 계정 하나로 basic_auth 를 만든다: 빈 basic_auth 블록은 Caddy 가 거부하고, `respond 401` 은 Caddy 지시어 순서상 안쪽 `handle` 보다 뒤라
    # 역할 부족 403 에 덮이고 WWW-Authenticate 도 없다(시험: test-gateway-auth.sh 계정 0개). 해시는 한 번 만든 뒤 버린 무작위 암호의 bcrypt 이다(`caddy hash-password`): 암호를 아는 사람이 없고 역할 매처도 모두 false.
    if [ -n "$body" ]; then printf '(authenticate) {\n\tbasic_auth {\n%s\t}\n}\n' "$body"
    else printf '(authenticate) {\n\tbasic_auth {\n\t\tno-accounts %s\n\t}\n}\n' '$2a$14$ThFaB0RPIv4Ii/aJyV6gh.W8lng/OIREUbKeN9IcdNx5hY6xdg5Im'; fi
    printf '(role_matchers) {\n%s}\n' "$roles_body"; } > "$D/gateway-accounts.caddy"
  chmod 644 "$D/gateway-accounts.caddy"
}
gw_devices() { ls "$1/tokens" 2>/dev/null | sed -n 's/^kiosk-device-\(.*\)$/\1/p'; }
gw_write_devices() {
  local D=$1 id vals=""
  for id in $(gw_devices "$D"); do [ -s "$D/tokens/kiosk-device-$id" ] && vals+="${vals:+, }\"Bearer $(tr -d '\r\n' < "$D/tokens/kiosk-device-$id")\""; done
  [ -e "$D/gateway-devices.caddy" ] || : > "$D/gateway-devices.caddy"
  { printf '# 생성됨(scripts/gen-secrets.sh, scripts/kiosk-add-device.sh). 기기 토큰 목록이라 비밀이다. 직접 고치지 않는다.\n'
    if [ -n "$vals" ]; then printf '(kiosk_devices) {\n\t@device_ok expression {http.request.header.Authorization} in [%s]\n}\n' "$vals"
    else printf '(kiosk_devices) {\n\t@device_ok expression false\n}\n'; fi; } > "$D/gateway-devices.caddy"
  chmod 644 "$D/gateway-devices.caddy"
  # survey-service 의 기기별 토큰 표(SURVEY_KIOSK_DEVICE_TOKENS, 줄마다 device_id=토큰, D88/U8): gateway 는 검증한 기기 토큰을 그대로 survey 에 넘기고(Authorization 을 바꾸지 않는다)
  # survey 가 같은 표로 검증해 세션을 만든 기기만 그 세션에 접근하게 한다. 비밀이고 기존 secrets 규칙(폴더 700, 파일 644)을 따른다. 기기를 바꾸면 survey-service 도 다시 시작해야 표가 바뀐다.
  : > "$D/tokens/survey-kiosk-device-tokens"
  for id in $(gw_devices "$D"); do [ -s "$D/tokens/kiosk-device-$id" ] && printf '%s=%s\n' "$id" "$(tr -d '\r\n' < "$D/tokens/kiosk-device-$id")" >> "$D/tokens/survey-kiosk-device-tokens"; done
  chmod 644 "$D/tokens/survey-kiosk-device-tokens"
}
