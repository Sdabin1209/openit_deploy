#!/usr/bin/env bash
# step_issue_token(lib.sh) 시험(가짜 docker): 계약 StepCaEnv 의 역할 입력(STEP_ROLE=token, STEP_TOKEN_NAMES, STEP_CA_URL, STEP_CA_PASSWORD_FILE, STEP_TOKENS_DIR)으로 이미지를 띄우고 출력 마운트의 <이름>.ott 를 가져온다.
# 이미지 부명령·step 도구를 부르는 코드(--entrypoint step)가 스크립트에 남지 않았는지도 본다. 변이: 가짜가 토큰 파일을 안 쓰면 실패한다. 사용: bash scripts/test-step-issue-token.sh
set -uo pipefail
DEPLOY_NO_DOCKER=1; source "$(dirname "$0")/lib.sh"
WD="$DEPLOY_ROOT/build/logs/stepok-$$"; mkdir -p "$WD"; trap 'rm -rf "$WD"' EXIT
cat > "$WD/docker" <<'DK'
#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
td=""; name=""
for a in "$@"; do case "$a" in STEP_TOKEN_NAMES=*) name=${a#*=};; esac; done
prev=""; for a in "$@"; do [ "$prev" = -v ] && case "$a" in *:/tokens) td=${a%%:*};; esac; prev=$a; done
[ -z "${FAKE_NO_WRITE:-}" ] && [ -n "$td" ] && echo "ott-for-$name" > "$td/$name.ott"
exit 0
DK
chmod +x "$WD/docker"; export FAKE_LOG="$WD/calls.txt"; DOCKER="$WD/docker"
F=0; ok() { echo "  PASS $1"; }; bad() { echo "  FAIL $1"; F=$((F+1)); }
mkdir -p "$WD/pki"; : > "$WD/pw"
step_issue_token step-img host.docker.internal https://host.docker.internal:9000 "$WD/pki" "$WD/pw" "$WD/out.ott" --add-host x:host-gateway && [ "$(cat "$WD/out.ott")" = "ott-for-host.docker.internal" ] && ok "토큰 파일을 가져온다" || bad "토큰 파일"
c=$(cat "$FAKE_LOG"); for k in STEP_ROLE=token STEP_TOKEN_NAMES=host.docker.internal STEP_CA_URL=https://host.docker.internal:9000 STEP_CA_PASSWORD_FILE=/run/secrets/step-ca-password STEP_TOKENS_DIR=/tokens; do grep -q -- "$k" <<<"$c" && ok "입력 $k" || bad "입력 $k"; done
grep -q -- "--group-add $SECRETS_GID" <<<"$c" && ok "비밀 파일 그룹을 받는다" || bad "비밀 파일 그룹이 없다"
[ "$(stat -c %a "$WD/out.ott")" = 640 ] && ok "출력 토큰은 비공개 파일이다" || bad "출력 토큰 모드"
[ "$(stat -c %g "$WD/out.ott")" = "$SECRETS_GID" ] && ok "출력 토큰 그룹이 소비자 그룹과 같다" || bad "출력 토큰 그룹"
grep -q -- '--entrypoint' <<<"$c" && bad "이미지 부명령 호출(--entrypoint)" || ok "--entrypoint 없음"
FAKE_NO_WRITE=1 step_issue_token step-img n https://x "$WD/pki" "$WD/pw" "$WD/out2.ott" >/dev/null 2>&1 && bad "변이(토큰을 안 쓰는 이미지)가 통과했다" || ok "변이: 토큰 파일이 없으면 실패"
step_issue_token step-img n https://x "$WD/pki" "$WD/pw" "$WD/no-such-parent/out.ott" >/dev/null 2>&1 && bad "복사 실패를 성공으로 반환했다" || ok "변이: 최종 토큰 복사 실패는 실패"
calls_before=$(wc -l < "$FAKE_LOG")
step_issue_token step-img 'bad_name' https://x "$WD/pki" "$WD/pw" "$WD/invalid.ott" >"$WD/invalid.log" 2>&1 && bad "스키마 위반 이름을 보냈다" || ok "스키마 위반은 Docker 실행 전에 거부"
[ "$(wc -l < "$FAKE_LOG")" = "$calls_before" ] && ok "거부한 입력으로 컨테이너를 실행하지 않는다" || bad "거부한 입력이 Docker에 도착했다"
grep -rn -e '--entrypoint step' -e 'ca token' "$DEPLOY_ROOT/scripts" --include='*.sh' --include='*.py' 2>/dev/null | grep -v 'test-step-issue-token.sh' | grep -v '^[^:]*:[0-9]*:\s*#' | grep -q . && bad "step 도구를 직접 부르는 코드가 남았다" || ok "step 도구 직접 호출 없음"
# E2E의 실제 발급 함수를 실행한다: 호출자가 올바른 토큰 권한을 다시 느슨하게 만들지 않아야 한다.
source <(sed -n '/^issue_tls_token() {/,/^}/p' "$DEPLOY_ROOT/scripts/e2e.sh")
PROJECT=fake; UTIL_REF=util; STEP_IMG=step-img; STEP_CA_PORT=9000; W=$WD; SECRETS_DIR="$WD/secrets"
mkdir -p "$SECRETS_DIR/tokens"; cp "$WD/pw" "$SECRETS_DIR/tokens/step-ca-password"; echo public-ca > "$W/gateway-ca.crt"
issue_tls_token >/dev/null 2>&1 && [ "$(stat -c %a "$W/tls.ott")" = 640 ] && [ "$(stat -c %g "$W/tls.ott")" = "$SECRETS_GID" ] && ok "E2E 발급 뒤에도 비밀 파일 권한을 지킨다" || bad "E2E가 토큰 권한을 바꿨다"
[ $F = 0 ] && echo "통과: step_issue_token 시험" || { echo "실패: $F건"; exit 1; }
