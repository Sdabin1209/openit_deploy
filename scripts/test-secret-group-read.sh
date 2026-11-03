#!/usr/bin/env bash
# L02(ADR 0054): 컨테이너가 읽는 비밀 파일(640 + 그룹 SECRETS_GID)을 uid 10001 컨테이너가 group_add 로 읽는지 실제로 본다. 대조군: group_add 가 없으면 못 읽는다(640 이 기타를 막는다).
# 그리고 합쳐진 compose 설정에서 비밀을 쓰는 모든 서비스·잡에 group_add 가 있는지 정적으로 본다. Docker 필요, 값은 출력하지 않는다. 사용: bash scripts/test-secret-group-read.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/lib.sh"; source "$HERE/testlib.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; N=0; F=0
ok() { N=$((N+1)); local n=$1; shift; if "$@" >"$T/out" 2>&1; then echo "  PASS $n"; else echo "  FAIL $n"; tail -3 "$T/out" | sed 's/^/     /'; F=$((F+1)); fi; }
no() { N=$((N+1)); local n=$1; shift; if "$@" >"$T/out" 2>&1; then echo "  FAIL $n (성공했다)"; F=$((F+1)); else echo "  PASS $n"; fi; }
export SECRETS_DIR=$T/sec DEPLOY_LOCK=$T/lock DEPLOY_REGISTRY_ENV=$T/reg.env; echo "DEPLOY_REGISTRY=127.0.0.1:5000" > "$T/reg.env"; test_lock_copy "$DEPLOY_LOCK"
bash "$HERE/gen-secrets.sh" --test-fixtures "$SECRETS_DIR" >/dev/null 2>&1
IMG=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_LOCK"); [ -n "$IMG" ] || { echo "UTIL_IMAGE 가 잠금 파일에 없다"; exit 1; }
F1=$SECRETS_DIR/tokens/survey-api-staff
ok "컨테이너가 읽는 비밀은 640 이고 그룹이 SECRETS_GID" bash -c "[ \"\$(stat -c %a '$F1')\" = 640 ] && [ \"\$(stat -c %g '$F1')\" = '$SECRETS_GID' ]"
rd() { "$DOCKER" run --rm --user 10001:10001 "$@" -v "$F1:/run/secrets/x:ro" --entrypoint cat "$IMG" /run/secrets/x; }
ok "uid 10001 + group_add 로 읽는다" rd --group-add "$SECRETS_GID"
no "대조군: group_add 없이는 읽지 못한다(기타 접근 없음)" rd
ok "호스트 전용 파일은 600 이다(계정 암호 등)" bash -c "for f in '$SECRETS_DIR'/tokens/account-*-password; do [ -f \"\$f\" ] || continue; [ \"\$(stat -c %a \"\$f\")\" = 600 ] || exit 1; done"
dc t config --format json > "$T/cfg.json" 2>"$T/cfg.err"
ok "비밀·설정을 쓰는 모든 서비스와 잡에 group_add 가 있다" python3 -I -c '
import json,sys
s=json.load(open(sys.argv[1]))["services"]; sg=sys.argv[2]
bad=[k for k,v in s.items() if (v.get("secrets") or v.get("configs")) and sg not in [str(x) for x in v.get("group_add",[])]]
assert not bad, bad' "$T/cfg.json" "$SECRETS_GID"
echo; [ $F = 0 ] && echo "통과: 비밀 그룹 읽기 시험 ${N}건" || { echo "실패: $F건 ($N건)"; exit 1; }
