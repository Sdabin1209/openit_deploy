#!/usr/bin/env bash
# check-secrets-hidden.sh 자기 점검: 비밀을 환경 변수로 가진 컨테이너는 실패시키고(컨테이너·변수 이름만 출력, 값은 출력하지 않음),
# 비밀을 파일로만 가진 컨테이너는 통과시키는지 본다. 임시 비밀 폴더와 임시 컨테이너(프로젝트 라벨 deploy-selftest-<pid>)를 쓰고 끝에 지운다.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/lib.sh"
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}"); [ -n "$UTIL" ] || die "UTIL_IMAGE 가 잠금에 없다"
P="deploy-selftest-$$"; T=$(mktemp -d); rc=0
cleanup() { "$DOCKER" rm -f "$P-leak" "$P-clean" >/dev/null 2>&1; rm -rf "$T"; }; trap cleanup EXIT
mkdir -p "$T/s/tokens"; python3 -c 'import secrets;print(secrets.token_hex(24))' > "$T/s/tokens/sample-token"; chmod 644 "$T/s/tokens/sample-token"
printf 'some-role=%s,other-role-with-long-name=%s\n' "$(cat "$T/s/tokens/sample-token")" "$(cat "$T/s/tokens/sample-token")" > "$T/s/tokens/sample-list"
run() { local n=$1; shift; "$DOCKER" run -d --name "$n" --label "com.docker.compose.project=$P" "$@" "$UTIL" python -c "import time;time.sleep(120)" >/dev/null; }
run "$P-clean" -e SAMPLE_TOKEN_FILE=/run/secrets/sample-token -v "$T/s/tokens/sample-token:/run/secrets/sample-token:ro"
run "$P-leak" -e LEAKY_NAME="$(cat "$T/s/tokens/sample-token")"
export CHECK_SECRETS_SKIP_STATIC=1 SECRETS_DIR="$T/s"
out=$(bash "$HERE/check-secrets-hidden.sh" "$P" 2>&1); r=$?
{ [ $r = 1 ] && grep -q "$P-leak" <<<"$out" && grep -q 'LEAKY_NAME' <<<"$out" && ! grep -q "$P-clean.*실패\|실패.*$P-clean" <<<"$out"; } && echo "ok: 환경 변수 노출을 잡고 컨테이너·변수 이름을 말한다" || { echo "FAIL: 노출을 못 잡았다(rc=$r)"; rc=1; }
grep -q "$(cat "$T/s/tokens/sample-token")" <<<"$out" && { echo "FAIL: 출력에 비밀 값이 있다"; rc=1; } || echo "ok: 출력에 비밀 값이 없다"
"$DOCKER" rm -f "$P-leak" >/dev/null
out=$(bash "$HERE/check-secrets-hidden.sh" "$P" 2>&1); r=$?
{ [ $r = 0 ] && grep -q '통과' <<<"$out"; } && echo "ok: 비밀을 파일로만 가진 컨테이너는 통과" || { echo "FAIL: 깨끗한 컨테이너가 실패했다(rc=$r)"; rc=1; }
exit $rc
