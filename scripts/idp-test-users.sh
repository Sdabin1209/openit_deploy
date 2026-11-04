#!/usr/bin/env bash
# 시험 사용자를 Keycloak(realm openit)에 만든다(E2E·데모·IdP 자체 시험 전용, 멱등). 사용: idp-test-users.sh [프로젝트]   환경: SECRETS_DIR, DEPLOY_PROJECT(기본 deploy), IDP_READY_S(기본 120)
# 사용자 목록: test/gateway-oidc/accounts.test.conf (`<사용자> <그룹,그룹|->`), 암호: $SECRETS_DIR/tokens/idp-test-<사용자>-password (gen-secrets.sh --test-fixtures).
# 왜 잡인가(구조 규칙 1·6, 계약 3.4.16): deploy 는 Keycloak 의 도구(kcadm)·관리 계정을 모른다. platform identity 이미지가 선언한 사용자 등록 잡(register-users)에 설정 파일(IdentityUsersConfig)을 주고 compose 잡으로 돌릴 뿐이다.
#   암호는 파일로만 간다(D84): 시험 암호 파일을 state/idp-users-secrets/<사용자>(모드 640)로 복사해 잡에 읽기 전용으로 마운트하고, 설정의 password_file 이 그 경로를 가리킨다.
# 같은 잡이 운영의 직원 등록 입구다(시험용 문이 아니다). 사용자 하나의 그룹을 바꿔 다시 돌리면 승인이 된다(멱등).
# 준비 대기: Keycloak 이 아직 준비 전이면 잡이 실패하므로 IDP_READY_S 초 동안 3초 간격으로 다시 돌린다. 상한 120초는 측정하지 않은 시작값이다(D125).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
P=${1:-${DEPLOY_PROJECT:-deploy}}; D=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}; ACC=${IDP_ACCOUNTS:-$DEPLOY_ROOT/test/gateway-oidc/accounts.test.conf}
SD="${IDP_USERS_SECRETS:-$DEPLOY_ROOT/state/idp-users-secrets}"; CFG="${IDENTITY_USERS_CONFIG:-$DEPLOY_ROOT/state/identity-users.json}"
mkdir -p "$SD"; chmod 750 "$SD"
"$DEPLOY_PY" -I "$DEPLOY_ROOT/scripts/idp_users_config.py" --accounts "$ACC" --passwords "$D/tokens" --secrets-out "$SD" --out "$CFG" >&2 || die "사용자 등록 설정(IdentityUsersConfig)을 만들지 못했다 (gen-secrets.sh --test-fixtures 를 했는가)"
n=$(grep -c . "$CFG" >/dev/null; "$DEPLOY_PY" -I -c 'import json,sys;print(len(json.load(open(sys.argv[1]))["users"]))' "$CFG")
export IDP_USERS_SECRETS="$SD" IDENTITY_USERS_CONFIG="$CFG"
IDP_READY_S=${IDP_READY_S:-120}; log=$(mktemp); trap 'rm -f "$log"' EXIT; ok=0
for _i in $(seq 1 $((IDP_READY_S/3))); do
  if DEPLOY_PROJECT="$P" bash "$DEPLOY_ROOT/scripts/run-job.sh" job-identity-register-users >"$log" 2>&1; then ok=1; break; fi
  sleep 3
done
[ $ok = 1 ] || { tail -3 "$log" >&2; die "사용자 등록 잡이 ${IDP_READY_S}초 안에 성공하지 않았다(identity 컨테이너 로그를 확인)"; }
echo "시험 사용자 ${n}명을 Keycloak(realm openit)에 만들었다(사용자 등록 잡)" >&2
