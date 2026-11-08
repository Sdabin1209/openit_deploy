#!/usr/bin/env bash
# gen-secrets.sh 가 비밀 목록 파일을 쓰기 전에 계약 secret_format_problems 로 검사하는지(D84, D117, 계약 5.0.1). Docker 불필요.
# 함수만 gen-secrets.sh 에서 꺼내 실행한다: 올바른 값은 통과(파일이 써진다), 어긋난 값은 종료 코드 비0 이고 출력에 값이 없고 파일이 없다(변이).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; DEPLOY_NO_DOCKER=1; source "$HERE/lib.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; D=$T; mkdir -p "$T/tokens"; rc=0
eval "$(sed -n '/^secret_check() {/,/^putlist() {/p' "$HERE/gen-secrets.sh")"
ok() { echo "  ok: $1"; }; no() { echo "  FAIL: $1"; rc=1; }
SECRET_VAL="r1=tok-abc,r2=tok-def"
( putlist t-good "$SECRET_VAL" role_token_list ) >/dev/null 2>&1 && [ -s "$T/tokens/t-good" ] && ok "올바른 role_token_list 는 써진다" || no "올바른 값이 거부됐다"
for case in "role_token_list|r1=tok bad,r2=x" "role_token_list|r1tok" "token_list|a, b" "token_actor_role_list|tok:actor" "credentials_line|nocolon" "role_token_list|r1=ab$(printf '\001')cd"; do
  k=${case%%|*}; v=${case#*|}; n="t-bad-$RANDOM"
  out=$( ( putlist "$n" "$v" "$k" ) 2>&1 ); r=$?
  if [ $r != 0 ] && [ ! -e "$T/tokens/$n" ] && ! grep -qF -- "$v" <<<"$out" && grep -q "$k" <<<"$out"; then ok "변이 거부($k), 값 출력 없음, 파일 없음"; else no "변이가 거부되지 않았다 또는 값이 출력됐다($k, rc=$r)"; fi
done
grep -q 'secret_check credentials_line' "$HERE/gen-secrets.sh" && ok "백업 자격 한 줄도 검사한다" || no "백업 자격 검사가 없다"
exit $rc
