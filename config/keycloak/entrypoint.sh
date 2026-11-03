#!/bin/bash
# Keycloak 엔트리포인트 래퍼(deploy ADR 0057, D84). Keycloak 은 데이터베이스 암호·부트스트랩 관리자 비밀번호·가져오기 파일의 자리표시 값을 환경 변수로만 받는다.
# 비밀은 컨테이너 환경 변수(docker inspect 로 보인다)가 아니라 파일(/run/secrets)이므로, 이 래퍼가 파일을 읽어 **이 프로세스의 환경에만** 넘기고 Keycloak 을 exec 한다.
# 값은 출력하지 않는다. 환경: KC_*_FILE 이 가리키는 파일(아래 이름), 나머지 KC_* 는 비밀이 아닌 설정이다(compose.yaml).
set -euo pipefail
rd() { [ -s "$1" ] || { echo "keycloak-entrypoint: 비밀 파일이 없거나 비었다: $1" >&2; exit 1; }; tr -d '\r\n' < "$1"; }
export KC_DB_PASSWORD; KC_DB_PASSWORD=$(rd "${KC_DB_PASSWORD_FILE:?}")
export KC_BOOTSTRAP_ADMIN_PASSWORD; KC_BOOTSTRAP_ADMIN_PASSWORD=$(rd "${KC_BOOTSTRAP_ADMIN_PASSWORD_FILE:?}")
export OPENIT_GATEWAY_CLIENT_SECRET; OPENIT_GATEWAY_CLIENT_SECRET=$(rd "${OPENIT_GATEWAY_CLIENT_SECRET_FILE:?}")      # realm 가져오기 파일의 ${OPENIT_GATEWAY_CLIENT_SECRET}
export OPENIT_INITIAL_ADMIN_PASSWORD; OPENIT_INITIAL_ADMIN_PASSWORD=$(rd "${OPENIT_INITIAL_ADMIN_PASSWORD_FILE:?}")   # realm 가져오기 파일의 ${OPENIT_INITIAL_ADMIN_PASSWORD}
unset KC_DB_PASSWORD_FILE KC_BOOTSTRAP_ADMIN_PASSWORD_FILE OPENIT_GATEWAY_CLIENT_SECRET_FILE OPENIT_INITIAL_ADMIN_PASSWORD_FILE
exec /opt/keycloak/bin/kc.sh "$@"
