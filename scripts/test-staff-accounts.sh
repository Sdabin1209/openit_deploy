#!/usr/bin/env bash
# 조직이 주는 직원 계정 파일(secrets/staff-accounts.conf) 처리 자체 시험(Docker 불필요, ADR 0039). 사용: bash scripts/test-staff-accounts.sh
# 확인: 형식·역할·bcrypt 해시 검사, 평문 암호 거부, 해시 그대로 반영, 이 프로젝트가 암호·해시 파일을 만들지 않음, 실패하면 기존 조각을 바꾸지 않음, 출력에 해시가 없음.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; T=$(mktemp -d); chmod 700 "$T"; trap 'rm -rf "$T"' EXIT
N=0; F=0
t() { local name=$1 want=$2; shift 2; N=$((N+1)); out=$("$@" 2>&1); local rc=$?; if [ $rc = "$want" ]; then echo "  PASS $name"; else echo "  FAIL $name (종료 $rc, 기대 $want) $(echo "$out" | tail -1 | cut -c1-200)"; F=$((F+1)); fi; }
ck() { N=$((N+1)); local name=$1; shift; if "$@" >/dev/null 2>&1; then echo "  PASS $name"; else echo "  FAIL $name"; F=$((F+1)); fi; }
H1='$2a$14$ThFaB0RPIv4Ii/aJyV6gh.W8lng/OIREUbKeN9IcdNx5hY6xdg5Im'; H2='$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ01234'   # 형식만 맞는 자리표시 해시(어떤 암호의 해시도 아니다)
S="$T/s"; mkdir -p "$S/tokens"; chmod 700 "$S" "$S/tokens"; export SECRETS_DIR="$S"
CONF="$S/staff-accounts.conf"
mk() { ( umask 077; printf '%s\n' "$@" > "$CONF" ); }
t "계정 파일이 없어도 성공하고 계정은 0개다" 0 bash "$HERE/apply-accounts.sh"
ck "계정 0개: 아무도 통과할 수 없는 자리표시 계정 하나만 있다" bash -c "grep -q 'no-accounts' '$S/gateway-accounts.caddy' && ! grep -q 'kim' '$S/gateway-accounts.caddy'"
mk "# 조직이 준 파일" "kim.staff  staff,operator  $H1" "lee.approver release-approver $H2"
t "올바른 파일은 반영된다" 0 bash "$HERE/apply-accounts.sh"
ck "조각에 조직이 준 해시가 그대로 들어간다" bash -c "grep -qF 'kim.staff $H1' '$S/gateway-accounts.caddy' && grep -qF 'lee.approver $H2' '$S/gateway-accounts.caddy'"
ck "역할 매핑: operator 는 kim.staff 만, release-approver 는 lee.approver 만" bash -c "grep -q '@role_operator .*\"kim.staff\"' '$S/gateway-accounts.caddy' && grep -q '@role_approver .*\"lee.approver\"' '$S/gateway-accounts.caddy' && ! grep '@role_approver' '$S/gateway-accounts.caddy' | grep -q kim"
ck "이 프로젝트는 암호·해시 파일을 만들지 않는다(tokens/account-*)" bash -c "[ -z \"\$(ls '$S'/tokens/account-* 2>/dev/null)\" ]"
t "출력에 해시가 없다(계정 ID와 역할만)" 1 bash -c "bash '$HERE/apply-accounts.sh' | grep -F -e '$H1' -e '$H2'"
cp "$S/gateway-accounts.caddy" "$T/good.caddy"
echo "== 잘못된 파일은 거부하고 기존 조각을 바꾸지 않는다"
mk "kim.staff staff 평문암호1234"; t "평문 암호는 해시가 아니라 거부" 1 bash "$HERE/apply-accounts.sh"
mk "kim.staff staff $H1" "kim.staff staff $H2"; t "계정 ID 중복 거부" 1 bash "$HERE/apply-accounts.sh"
mk "kim.staff superuser $H1"; t "모르는 역할 거부" 1 bash "$HERE/apply-accounts.sh"
mk "Kim.Staff staff $H1"; t "계정 ID 규칙 위반(대문자) 거부" 1 bash "$HERE/apply-accounts.sh"
mk "kim.staff staff"; t "열이 모자라면 거부" 1 bash "$HERE/apply-accounts.sh"
mk "kim.staff staff ${H1}x"; t "해시 길이가 다르면 거부" 1 bash "$HERE/apply-accounts.sh"
mk "kim.staff staff $H1"; chmod 666 "$CONF"; t "다른 사용자가 쓸 수 있는 파일은 거부" 1 bash "$HERE/apply-accounts.sh"
ck "거부된 뒤에도 기존 조각이 그대로다" bash -c "cmp -s '$T/good.caddy' '$S/gateway-accounts.caddy'"
ck "옛 발급·회전 스크립트가 없다(rotate-account.sh)" test ! -e "$HERE/rotate-account.sh"
ck "예시 파일의 주석 해시는 형식 검사를 통과한다" bash -c "grep -m1 '^# kim.staff' '$HERE/../config/staff-accounts.conf.example' | sed 's/^# //' > '$T/ex.conf' && chmod 600 '$T/ex.conf' && GATEWAY_ACCOUNTS_CONF='$T/ex.conf' bash -c 'DEPLOY_NO_DOCKER=1; source \"$HERE/lib.sh\"; source \"$HERE/gateway-lib.sh\"; gw_parse_accounts' >/dev/null"
echo; [ $F = 0 ] && echo "통과: 직원 계정 파일 자체 시험 $N건" || { echo "실패: $F건 ($N건)"; exit 1; }
