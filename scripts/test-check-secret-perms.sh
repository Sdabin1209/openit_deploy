#!/usr/bin/env bash
# check-secret-perms.sh 자기 점검(Docker 불필요, 비밀 값은 만들지 않는다 -- 빈 파일만): 제품 배치(폴더 700, 컨테이너가 읽는 파일 640+SECRETS_GID, 호스트 전용 600)는 통과하고,
# 범위를 넓힌 곳(db-accounts·db-urls, device-ca.key·device-certs 키, idp-users-secrets)의 어긋남은 변이마다 실패한다.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; DEPLOY_NO_DOCKER=1; source "$HERE/lib.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; rc=0
S="$T/s"; I="$T/idp"; G=$(id -g)
mkdir -p "$S/tokens" "$S/db-accounts/survey-db" "$S/db-urls/survey-db/app" "$S/device-certs" "$I"; chmod 700 "$S" "$S/tokens"
: > "$S/db-accounts/survey-db/app"; : > "$S/db-urls/survey-db/app/SURVEY_DATABASE_URL"
: > "$S/device-ca.key"; : > "$S/device-ca.pem"; : > "$S/device-certs/e2e.key"; : > "$S/device-certs/e2e.crt"; : > "$I/op"
chmod 750 "$S/db-accounts" "$S/db-accounts/survey-db" "$S/db-urls" "$S/db-urls/survey-db" "$S/db-urls/survey-db/app"
chmod 640 "$S/db-accounts/survey-db/app" "$S/db-urls/survey-db/app/SURVEY_DATABASE_URL" "$I/op"; chmod 600 "$S/device-ca.key" "$S/device-certs/e2e.key"; chmod 644 "$S/device-ca.pem" "$S/device-certs/e2e.crt"
run() { SECRETS_GID=$G IDP_USERS_SECRETS="$I" bash "$HERE/check-secret-perms.sh" "$S" 2>&1; }
ok() { echo "  ok: $1"; }; no() { echo "  FAIL: $1"; rc=1; }
out=$(run); r=$?; [ $r = 0 ] && ok "제품 배치는 통과한다" || no "제품 배치가 실패한다: $out"
mut() { # mut <설명> <대상> <바꿀 모드> <출력에 있어야 할 말>
  local was; was=$(stat -c %a "$2"); chmod "$3" "$2"; out=$(run); r=$?; chmod "$was" "$2"
  { [ $r = 1 ] && grep -q "$4" <<<"$out"; } && ok "변이: $1 -> 실패" || no "변이: $1 가 잡히지 않았다(rc=$r): $(tail -2 <<<"$out")"; }
mut "db-accounts 파일 644" "$S/db-accounts/survey-db/app" 644 "db-accounts/survey-db/app"
mut "db-urls 파일 600(서비스가 못 읽는다)" "$S/db-urls/survey-db/app/SURVEY_DATABASE_URL" 600 "db-urls/survey-db/app/SURVEY_DATABASE_URL"
mut "db-urls 폴더(루트) 700(그룹이 못 들어간다)" "$S/db-urls" 700 "db-urls/ 폴더"
mut "db-accounts 폴더(루트) 770(그룹 쓰기)" "$S/db-accounts" 770 "db-accounts/ 폴더"
mut "db-accounts/survey-db 폴더 700" "$S/db-accounts/survey-db" 700 "db-accounts/survey-db/ 폴더"
mut "db-urls 폴더 755" "$S/db-urls/survey-db" 755 "db-urls/survey-db/ 폴더"
mut "device-ca.key 644" "$S/device-ca.key" 644 "device-ca.key"
mut "기기 키 640" "$S/device-certs/e2e.key" 640 "device-certs/e2e.key"
mut "device-ca.pem 666" "$S/device-ca.pem" 666 "device-ca.pem"
mut "idp 시험 암호 600" "$I/op" 600 "idp-users-secrets/op"
out=$(SECRETS_GID=$((G+7777)) IDP_USERS_SECRETS="$I" bash "$HERE/check-secret-perms.sh" "$S" 2>&1); r=$?
{ [ $r = 1 ] && grep -q "db-urls/ 폴더 그룹" <<<"$out" && grep -q "db-accounts/survey-db/ 폴더 그룹" <<<"$out"; } && ok "변이: SECRETS_GID 와 다른 그룹(DB 폴더, 루트 포함) -> 실패" || no "폴더 그룹 어긋남이 잡히지 않았다"
out=$(SECRETS_GID=$((G+7777)) IDP_USERS_SECRETS="$I" bash "$HERE/check-secret-perms.sh" "$S" 2>&1); r=$?
{ [ $r = 1 ] && grep -q "db-accounts/survey-db/app 그룹" <<<"$out" && grep -q "idp-users-secrets/op 그룹" <<<"$out"; } && ok "변이: SECRETS_GID 와 다른 그룹(DB 비밀·idp 암호) -> 실패" || no "그룹 어긋남이 잡히지 않았다"
exit $rc
