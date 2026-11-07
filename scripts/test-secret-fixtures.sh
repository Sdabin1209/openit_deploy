#!/usr/bin/env bash
# 시험 자격이 운영 구성에 들어가지 않는지 자체 시험(head 결정표 2절 deploy 1행: 시험 데이터와 운영 구성 분리, 12-factor 10항).
# 기대값의 출처: 결정표(기본은 운영 자격만, 시험 기기·*-e2e 계정은 --test-fixtures 에서만, 운영 기동 점검이 막는다). 사용: bash scripts/test-secret-fixtures.sh
# Docker 가 필요하다(계정 해시 caddy hash-password, caddy validate). 일회용 컨테이너만 돌리고 실행 중인 컨테이너·볼륨은 건드리지 않는다. 값은 출력하지 않는다.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/lib.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; cd "$T"   # 옛 gen-secrets 가 모르는 인자를 폴더 이름으로 만들어도 임시 폴더 안에서만
PKI=$T/pki; mkdir -p "$PKI"; gateway_test_pki "$PKI" x || exit 1   # ADR 0060: Caddyfile 검증에 루트 인증서 파일이 필요하다
N=0; F=0
ok() { local name=$1; shift; N=$((N+1)); if out=$("$@" 2>&1); then echo "  PASS $name"; else echo "  FAIL $name"; printf '%s\n' "$out" | tail -3 | cut -c1-220 | sed 's/^/       /'; F=$((F+1)); fi; }

P=$T/prod; F2=$T/fixt
DAP=$T/allow-prod; DAF=$T/allow-fixt   # 기기 허용 목록 폴더도 폴더마다 따로(기본 state/ 를 건드리지 않는다)
DEVICE_ALLOWLIST_DIR=$DAP bash "$HERE/gen-secrets.sh" "$P" >/dev/null 2>&1
echo "== 기본(운영) 생성"
ok "시험 기기 인증서(device-certs/e2e*)와 개발용 CA 가 없다" bash -c '! ls "$1"/device-certs/e2e* "$1"/device-ca.* >/dev/null 2>&1' _ "$P"
ok "비밀 폴더에 사람 계정 파일(account-*)이 없다(U82: 사람 계정은 Keycloak)" bash -c '! ls "$1"/tokens/account-* "$1"/gateway-accounts.caddy >/dev/null 2>&1' _ "$P"
ok "realm 가져오기 템플릿에 시험 사용자(-e2e)가 없다(시험 사용자는 E2E·데모가 Keycloak 에 만든다)" bash -c '! grep -q -- "-e2e" "$1/config/keycloak/openit-realm.template.json"' _ "$DEPLOY_ROOT"
ok "운영 기본은 기기 0대(허용 목록이 있고 비어 있다)" bash -c '[ -z "$(DEVICE_ALLOWLIST_DIR=$2 "$3" -W ignore -I "$1/scripts/device_allowlist.py" "$2/allowlist.json" list)" ] && [ -f "$2/allowlist.json" ]' _ "$DEPLOY_ROOT" "$DAP" "$DEPLOY_PY"
ok "기기 토큰 파일(devices/, survey-kiosk-device-tokens)은 더 만들지 않는다" bash -c '[ ! -e "$1/devices" ] && [ ! -e "$1/tokens/survey-kiosk-device-tokens" ]' _ "$P"
echo "== --test-fixtures"
DEVICE_ALLOWLIST_DIR=$DAF bash "$HERE/gen-secrets.sh" --test-fixtures "$F2" >/dev/null 2>&1
ok "시험 기기 4대(e2e, e2e-a, e2e-b, e2e-c)의 인증서가 있다" bash -c 'for d in e2e e2e-a e2e-b e2e-c; do [ -s "$1/device-certs/$d.crt" ] || exit 1; done' _ "$F2"
echo "== 운영 기동 점검(check-test-fixtures.sh)"
rc() { local want=$1; shift; DEVICE_ALLOWLIST_DIR=$DEV_AL "$@" >/dev/null 2>&1; [ $? = "$want" ]; }   # 스크립트가 없어서 나는 127 이 "거부"로 통과하지 않게 종료 코드를 정확히 본다
DEV_AL=$DAP; ok "운영 비밀은 통과(종료 0)" rc 0 bash "$HERE/check-test-fixtures.sh" "$P"
DEV_AL=$DAF; ok "시험 비밀은 거부(종료 1)" rc 1 bash "$HERE/check-test-fixtures.sh" "$F2"
ok "거부 메시지가 시험 기기를 이름으로 알린다" bash -c 'DEVICE_ALLOWLIST_DIR=$3 bash "$1/scripts/check-test-fixtures.sh" "$2" 2>&1 | grep -q "시험 기기 인증서 e2e"' _ "$DEPLOY_ROOT" "$F2" "$DAF"
# 허용 목록에만 시험 기기가 남은 경우(인증서 파일은 없음)도 잡는다
cp -a "$F2" "$T/certless"; rm -rf "$T/certless/device-certs" "$T/certless/.test-fixtures"
DEV_AL=$DAF; ok "인증서 파일이 없어도 허용 목록에 시험 기기가 있으면 거부(종료 1)" rc 1 bash "$HERE/check-test-fixtures.sh" "$T/certless"
# 옛 방식으로 이미 시험 자격이 섞인 운영 폴더(마커 없음)도 잡아야 한다: 시험 비밀 사본에서 마커만 지운다
cp -a "$F2" "$T/legacy"; rm -f "$T/legacy/.test-fixtures"
ok "마커가 없어도 시험 기기·계정이 있으면 거부(종료 1)" rc 1 bash "$HERE/check-test-fixtures.sh" "$T/legacy"
ok "doctor --up --production 이 시험 비밀을 FAIL 로 막는다" bash -c 'DEVICE_ALLOWLIST_DIR=$3 SECRETS_DIR="$2" bash "$1/scripts/doctor.sh" --up --production 2>&1 | grep -q "시험 자격"' _ "$DEPLOY_ROOT" "$F2" "$DAF"
echo; [ $F = 0 ] && echo "통과: 시험 자격 분리 자체 시험 $N건" || { echo "실패: $F건 ($N건)"; exit 1; }
