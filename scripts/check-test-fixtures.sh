#!/usr/bin/env bash
# 운영 비밀 폴더에 시험 자격이 없는지 점검한다(읽기 전용, 값은 읽지도 출력하지도 않는다). 사용: check-test-fixtures.sh [비밀 폴더]  (기본 $SECRETS_DIR 또는 secrets/)
# 시험 자격 = 시험 기기 토큰(tokens/kiosk-device-e2e*), config/gateway-accounts.test.conf 의 계정 ID 가 gateway-accounts.caddy 에 있는 것, gen-secrets.sh --test-fixtures 의 .test-fixtures 표시.
# 왜: 시험 기기·*-e2e 계정은 이름이 알려진 시험용이라 운영 gateway 에서 유효하면 안 된다(시험 데이터와 운영 구성 분리: 12-factor 10항, 기본 자격 금지: OWASP). doctor.sh --up --production 이 부른다.
# 종료 코드 0 통과, 1 시험 자격 있음, 2 비밀 폴더 없음.
set -uo pipefail
DEPLOY_NO_DOCKER=1; source "$(dirname "$0")/lib.sh"
D=${1:-${SECRETS_DIR:-$DEPLOY_ROOT/secrets}}
[ -d "$D" ] || { echo "비밀 폴더가 없다: $D" >&2; exit 2; }
bad=0
[ ! -e "$D/.test-fixtures" ] || { echo "FAIL .test-fixtures 표시: 이 폴더는 gen-secrets.sh --test-fixtures 로 만들어졌다(시험 폴더)"; bad=$((bad+1)); }
for f in "$D"/tokens/kiosk-device-e2e*; do [ -e "$f" ] || continue; echo "FAIL 시험 기기 토큰 $(basename "$f")"; bad=$((bad+1)); done
source "$(dirname "$0")/gateway-lib.sh"; T=$(gw_test_accounts_conf)
if [ -f "$T" ] && [ -f "$D/gateway-accounts.caddy" ]; then
  while read -r acc _; do case "$acc" in ""|\#*) continue;; esac
    grep -qE "^[[:space:]]+${acc} " "$D/gateway-accounts.caddy" && { echo "FAIL 시험 계정 $acc 가 gateway-accounts.caddy 에 있다"; bad=$((bad+1)); }
  done < <(sed 's/#.*//' "$T")
fi
if [ $bad = 0 ]; then echo "OK 시험 자격 없음"; exit 0; fi
echo "FAIL 시험 자격 $bad건: 운영 구성에 들어 있으면 안 된다" ; exit 1
