#!/usr/bin/env bash
# 시험 사용자를 Keycloak(realm openit)에 만든다(E2E·데모·IdP 자체 시험 전용, 멱등). 사용: idp-test-users.sh [프로젝트]   환경: SECRETS_DIR, DEPLOY_PROJECT(기본 deploy)
# 사용자 목록: test/gateway-oidc/accounts.test.conf (`<사용자> <그룹,그룹|->`), 암호: $SECRETS_DIR/tokens/idp-test-<사용자>-password (gen-secrets.sh --test-fixtures).
# 운영 입구로만 만든다(head ADR 0014 9번): 제품 컨테이너 안의 표준 관리 도구 kcadm.sh 로 Keycloak 관리 API 를 부른다. 관리자는 master realm 의 부트스트랩 관리자(비밀 파일)다.
# 제품 구성(compose.yaml)과 realm 가져오기 파일에는 시험 사용자가 없다. 암호는 kcadm 의 인자로 keycloak 컨테이너 안 프로세스 목록에 잠깐 보인다(시험 전용 무작위 값, 컨테이너 밖에는 나오지 않는다).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
P=${1:-${DEPLOY_PROJECT:-deploy}}; D=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}; ACC=$DEPLOY_ROOT/test/gateway-oidc/accounts.test.conf
KC() { dc "$P" exec -T keycloak /opt/keycloak/bin/kcadm.sh "$@" --config /tmp/kcadm.config </dev/null; }   # </dev/null: exec 이 아래 while read 의 표준 입력(사용자 목록)을 먹지 않게 한다
kc_pw=$(tr -d '\r\n' < "$D/tokens/keycloak-bootstrap-admin-password")
KC config credentials --server http://127.0.0.1:8080/auth --realm master --user kcadmin --password "$kc_pw" >/dev/null 2>&1 || die "Keycloak 관리 로그인 실패(keycloak 컨테이너가 healthy 인지 확인)"
unset kc_pw
n=0
while read -r user groups _; do case "$user" in ""|\#*) continue;; esac
  pw=$(tr -d '\r\n' < "$D/tokens/idp-test-$user-password") || die "시험 사용자 암호 파일이 없다: idp-test-$user-password (gen-secrets.sh --test-fixtures)"
  if [ -z "$(KC get users -r openit -q "username=$user" -q exact=true --fields id --format csv --noquotes | tr -d '\r\n')" ]; then
    KC create users -r openit -s "username=$user" -s enabled=true -s "email=$user@test.invalid" -s emailVerified=true -s firstName=Test -s "lastName=$user" >/dev/null || die "사용자 생성 실패: $user"
  fi
  KC set-password -r openit --username "$user" --new-password "$pw" >/dev/null || die "암호 설정 실패: $user"
  uid=$(KC get users -r openit -q "username=$user" -q exact=true --fields id --format csv --noquotes | tr -d '\r\n')
  if [ "$groups" != "-" ]; then
    for g in ${groups//,/ }; do
      gid=$(KC get groups -r openit -q "search=$g" -q exact=true --fields id,name --format csv --noquotes | tr -d '\r' | awk -F, -v g="$g" '$2==g{print $1; exit}')
      [ -n "$gid" ] || die "그룹이 없다: $g"
      KC update "users/$uid/groups/$gid" -r openit -s "realm=openit" -s "userId=$uid" -s "groupId=$gid" -n >/dev/null || die "그룹 지정 실패: $user -> $g"
    done
  fi
  unset pw; n=$((n+1))
done < "$ACC"
echo "시험 사용자 ${n}명을 Keycloak(realm openit)에 만들었다" >&2
