#!/usr/bin/env bash
# 계정 암호가 호스트 프로세스 목록(docker 인자)에 보이는가: 가짜 docker 가 받은 인자·표준 입력을 기록해 확인하고, 문서가 그 사실과 같은지 본다.
# 기대값의 출처: 결정표 2절 deploy 2행(코드를 확인해 문서를 사실로 고친다, D89) + 코드의 점검 L6 주석(암호는 표준 입력). 사용: bash scripts/test-hash-password-argv.sh   (Docker 불필요)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(dirname "$HERE")"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; N=0; F=0
ok() { local name=$1; shift; N=$((N+1)); if "$@" >/dev/null 2>&1; then echo "  PASS $name"; else echo "  FAIL $name"; F=$((F+1)); fi; }
cat > "$T/fakedocker" <<'FD'
#!/usr/bin/env bash
# 가짜 docker: info 는 성공. run 은 받은 인자와 표준 입력을 기록하고 bcrypt 꼴 가짜 해시 한 줄을 낸다.
[ "${1:-}" = info ] && exit 0
printf '%s\n' "$*" >> "$FAKE_LOG/argv"; cat >> "$FAKE_LOG/stdin"; echo '$2a$14$FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE'
FD
chmod +x "$T/fakedocker"; mkdir -p "$T/log" "$T/s/tokens"; chmod 700 "$T/s" "$T/s/tokens"
export FAKE_LOG=$T/log DOCKER=$T/fakedocker SECRETS_DIR=$T/s DEPLOY_LOCK=$T/lock GATEWAY_ACCOUNTS_CONF=$T/acc.conf
echo "GATEWAY_IMAGE=fake/caddy@sha256:0" > "$T/lock"; echo "acct-a staff" > "$T/acc.conf"
# 1) 생성 경로(gateway-lib.sh gw_write_accounts)
( source "$ROOT/scripts/lib.sh"; source "$ROOT/scripts/gateway-lib.sh"; gw_write_accounts "$T/s" ) >/dev/null 2>&1
PW1=$(cat "$T/s/tokens/account-acct-a-password" 2>/dev/null)
ok "생성 경로: 암호가 만들어졌다" test -n "$PW1"
ok "생성 경로: docker 인자에 암호가 없다" bash -c '! grep -qF -- "$1" "$2/argv"' _ "$PW1" "$T/log"
ok "생성 경로: 표준 입력으로 암호를 받았다(확인 입력 포함 2줄)" bash -c '[ "$(grep -cxF -- "$1" "$2/stdin")" = 2 ]' _ "$PW1" "$T/log"
# 2) 회전 경로(rotate-account.sh): 새 암호는 표준 출력으로만 나온다
: > "$T/log/argv"; : > "$T/log/stdin"
PW2=$(bash "$ROOT/scripts/rotate-account.sh" acct-a 2>/dev/null | tail -1)
ok "회전 경로: 새 암호가 나왔고 이전과 다르다" bash -c '[ -n "$1" ] && [ "$1" != "$2" ]' _ "$PW2" "$PW1"
ok "회전 경로: docker 인자에 암호가 없다" bash -c '! grep -qF -- "$1" "$2/argv"' _ "$PW2" "$T/log"
ok "회전 경로: 표준 입력으로 암호를 받았다" bash -c '[ "$(grep -cxF -- "$1" "$2/stdin")" = 2 ]' _ "$PW2" "$T/log"
# 3) 문서가 사실과 같다: 암호가 docker 인자로 보인다는 문장이 남아 있으면 안 된다
for f in scripts/rotate-account.sh docs/adr/0022-secret-file-permissions.md docs/runbook.md; do
  ok "$f 에 '암호가 docker run 인자로 보인다'는 낡은 문장이 없다" bash -c '! grep -q "암호가 .docker run. 인자로\|암호가 docker run 인자로" "$1/$2"' _ "$ROOT" "$f"
done
echo; [ $F = 0 ] && echo "통과: 암호 인자 노출 자체 시험 $N건" || { echo "실패: $F건 ($N건)"; exit 1; }
