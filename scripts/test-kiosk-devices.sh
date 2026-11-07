#!/usr/bin/env bash
# 기기 인증서 허용 목록(계약 DeviceAllowlist, PUBLIC_API F절, D136)의 생성·등록·회전·폐기 시험: gen-secrets.sh --test-fixtures 와 kiosk-add-device.sh.
# 왜: 허용 목록과 개발용 인증서는 deploy 가 만드는 산출물이라 입구 구현과 무관하게 deploy 가 시험한다. Docker 불필요(openssl·python 만).
# 기대값의 출처: 계약 DeviceAllowlist(일련번호 형식·유일성), RFC 5280 4.1.2.2(일련번호), POSIX rename 원자 교체, 동시 등록에서 일련번호를 잃지 않음(배타 잠금).
set -u
DEPLOY_NO_DOCKER=1
DEPLOY_ROOT=$(cd "$(dirname "$0")/.." && pwd); source "$DEPLOY_ROOT/scripts/lib.sh"
T=$(mktemp -d); export SECRETS_DIR=$T/secrets DEVICE_ALLOWLIST_DIR=$T/allow; trap 'rm -rf "$T"' EXIT
FAILS=0; ok() { local n=$1; shift; if "$@" >/dev/null 2>&1; then echo "  PASS $n"; else echo "  FAIL $n"; FAILS=$((FAILS+1)); fi; }
no() { local n=$1; shift; if "$@" >/dev/null 2>&1; then echo "  FAIL $n (성공했다)"; FAILS=$((FAILS+1)); else echo "  PASS $n"; fi; }
K="$DEPLOY_ROOT/scripts/kiosk-add-device.sh"; L="$DEPLOY_ROOT/scripts/device_allowlist.py"; AL=$DEVICE_ALLOWLIST_DIR/allowlist.json
OUT=$(bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --test-fixtures "$SECRETS_DIR" 2>&1)
ser() { "$DEPLOY_PY" -W ignore -I "$L" "$AL" serials "$1"; }
ids() { "$DEPLOY_PY" -W ignore -I "$L" "$AL" list | tr '\n' ' '; }
chk() { "$DEPLOY_PY" -W ignore -I -c 'import json,sys;from boundary_contracts import validator;d=json.load(open(sys.argv[1]));sys.exit(1 if list(validator("DeviceAllowlist").iter_errors(d)) else 0)' "$AL"; }
ok "gen-secrets.sh --test-fixtures: 시험 기기 4대(e2e, e2e-a, e2e-b, e2e-c)가 목록에 있다" bash -c '[ "$1" = "e2e e2e-a e2e-b e2e-c " ]' _ "$(ids)"
ok "목록이 계약 DeviceAllowlist 를 통과한다" chk
ok "목록 폴더에는 allowlist.json 하나뿐이다(비밀 없음, 잠금 파일은 폴더 밖)" bash -c '[ "$(ls -A "$1")" = allowlist.json ] && [ -f "$1.lock" ]' _ "$DEVICE_ALLOWLIST_DIR"
ok "권한: 폴더 755, 파일 644(입구 컨테이너 uid 10001 / gid 0 이 읽는다)" bash -c '[ "$(stat -c %a "$1")" = 755 ] && [ "$(stat -c %a "$2")" = 644 ]' _ "$DEVICE_ALLOWLIST_DIR" "$AL"
ok "기기 CA 개인 키는 비밀 폴더에만 있고(600) 허용 목록 폴더에는 없다" bash -c '[ "$(stat -c %a "$1/device-ca.key")" = 600 ] && [ ! -e "$2/device-ca.key" ] && [ "$(stat -c %a "$1/device-ca.pem")" = 644 ]' _ "$SECRETS_DIR" "$DEVICE_ALLOWLIST_DIR"
ok "기기 인증서가 개발용 CA 로 검증되고 clientAuth 이며 CN = 기기 ID" bash -c 'd=$1/device-certs; openssl verify -CAfile $1/device-ca.pem -purpose sslclient $d/e2e-a.crt >/dev/null && openssl x509 -in $d/e2e-a.crt -noout -subject | grep -q "CN *= *e2e-a"' _ "$SECRETS_DIR"
ok "목록의 일련번호가 인증서의 일련번호다(소문자 16진수, 앞자리 0 없음)" bash -c 's=$(openssl x509 -in $1/device-certs/e2e-a.crt -noout -serial | sed "s/^serial=//" | tr A-F a-f | sed "s/^0*//"); [ "$s" = "$2" ] && [[ "$s" =~ ^[1-9a-f][0-9a-f]*$ ]]' _ "$SECRETS_DIR" "$(ser e2e-a)"
ok "기기 키는 600" bash -c '[ "$(stat -c %a "$1/device-certs/e2e-a.key")" = 600 ]' _ "$SECRETS_DIR"
ok "출력에 키·일련번호 같은 긴 16진수 값이 없다" bash -c '! grep -qE "[0-9a-f]{30}" <<<"$1"' _ "$OUT"
bash "$K" add lobby-2 >/dev/null 2>&1
ok "add: 기기 5대, 새 기기에 인증서와 일련번호 하나" bash -c '[ "$(echo $1 | wc -w)" = 5 ] && [ "$(echo "$2" | wc -l)" = 1 ] && [ -s $3/device-certs/lobby-2.crt ]' _ "$(ids)" "$(ser lobby-2)" "$SECRETS_DIR"
S1=$(ser lobby-2)
ok "add 를 다시 하면 그대로(일련번호·인증서 변하지 않음)" bash -c 'bash $1 add lobby-2 && [ "$(bash -c "$2" _)" = "$3" ]' _ "$K" "\"$DEPLOY_PY\" -W ignore -I \"$L\" \"$AL\" serials lobby-2" "$S1"
bash "$K" rotate lobby-2 >/dev/null 2>&1
ok "rotate: 일련번호가 둘(옛 것 + 새 것), 인증서 파일은 새 것" bash -c '[ "$(echo "$1" | wc -l)" = 2 ] && echo "$1" | grep -qx "$2"' _ "$(ser lobby-2)" "$S1"
bash "$K" revoke-serial lobby-2 "$S1" >/dev/null 2>&1
ok "revoke-serial: 옛 일련번호만 빠지고 새 것은 남는다" bash -c '[ "$(echo "$1" | wc -l)" = 1 ] && ! echo "$1" | grep -qx "$2"' _ "$(ser lobby-2)" "$S1"
ok "revoke-serial 은 다른 기기의 항목을 건드리지 않는다" bash -c '[ "$(echo $1 | wc -w)" = 5 ]' _ "$(ids)"
no "없는 일련번호는 빼지 못한다" bash "$K" revoke-serial lobby-2 abc123
ok "register: 외부 PKI 가 발급한 일련번호(대문자·앞자리 0)를 정규화해 더한다" bash -c 'bash $1 register ext-1 00ABC123 && [ "$(bash -c "$2" _)" = abc123 ]' _ "$K" "\"$DEPLOY_PY\" -W ignore -I \"$L\" \"$AL\" serials ext-1"
no "register: 0 은 거부(RFC 5280: 양의 정수)" bash "$K" register ext-2 000
no "register: 16진수가 아니면 거부" bash "$K" register ext-2 xyz
no "register: 41자리는 거부(계약: 최대 20옥텟)" bash "$K" register ext-2 "$(printf '1%.0s' $(seq 41))"
ok "거부된 등록은 목록을 바꾸지 않는다(ext-2 없음, 계약 통과)" bash -c '! "$1" -W ignore -I "$2" "$3" has ext-2' _ "$DEPLOY_PY" "$L" "$AL"
ok "잘못된 기기 ID 는 거부" bash -c '! bash $1 add "Bad ID"' _ "$K"
# 동시 등록: 배타 잠금이 읽기부터 rename 까지 쥐고 있으면 서로의 일련번호를 잃지 않는다
for i in $(seq 1 12); do bash "$K" register race "$(printf '%x' $((4096 + i)))" >/dev/null 2>&1 & done; wait
ok "동시 register 12건: 일련번호 12개가 모두 남는다(갱신 손실 없음)" bash -c '[ "$(echo "$1" | wc -l)" = 12 ]' _ "$(ser race)"
for i in $(seq 1 8); do bash "$K" register "par-$i" "$(printf '%x' $((8192 + i)))" >/dev/null 2>&1 & done; wait
ok "동시 register 서로 다른 기기 8대: 모두 남고 다른 항목도 그대로" bash -c '[ "$(echo $1 | wc -w)" = 15 ]' _ "$(ids)"
ok "동시 갱신 뒤에도 목록이 계약을 통과하고 폴더에는 allowlist.json 하나뿐이다(임시 파일이 남지 않음)" bash -c '[ "$(ls -A "$1")" = allowlist.json ]' _ "$DEVICE_ALLOWLIST_DIR"
chk || FAILS=$((FAILS+1))
bash "$K" remove lobby-2 >/dev/null 2>&1
ok "remove: 기기 항목과 인증서 파일이 사라진다(다른 기기는 그대로)" bash -c '! "$1" -W ignore -I "$2" "$3" has lobby-2 && [ ! -e $4/device-certs/lobby-2.crt ] && [ "$("$1" -W ignore -I "$2" "$3" list | wc -l)" = 14 ]' _ "$DEPLOY_PY" "$L" "$AL" "$SECRETS_DIR"
ok "인증서 파일만 지워도 목록은 그대로다(폐기는 목록을 바꾸는 것)" bash -c 'rm $1/device-certs/e2e-a.crt; "$2" -W ignore -I "$3" "$4" has e2e-a' _ "$SECRETS_DIR" "$DEPLOY_PY" "$L" "$AL"
ok "기기 0대여도 유효(빈 목록이 계약을 통과)" bash -c 'for d in $("$1" -W ignore -I "$2" "$3" list); do bash "$4" remove $d; done; [ -z "$("$1" -W ignore -I "$2" "$3" list)" ]' _ "$DEPLOY_PY" "$L" "$AL" "$K"
chk || FAILS=$((FAILS+1))
H0=$(sha256sum "$AL" | cut -d" " -f1)
no "device_id 규칙(앞 글자 영숫자)을 어기면 add 가 실패한다" "$DEPLOY_PY" -W ignore -I "$L" "$AL" add "-bad" abc
ok "거부된 갱신은 파일을 바꾸지 않는다" bash -c '[ "$(sha256sum "$1" | cut -d" " -f1)" = "$2" ]' _ "$AL" "$H0"
chk || FAILS=$((FAILS+1))
[ "$FAILS" = 0 ] && echo "OK" || { echo "FAIL $FAILS"; exit 1; }
