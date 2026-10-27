#!/usr/bin/env bash
# check-secret-perms.sh 와 gen-secrets.sh 의 권한 자체 시험(Docker 불필요: --db-only 와 가짜 파일). 사용: bash scripts/test-secret-perms.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
N=0; F=0
t() { local name=$1 want=$2 txt=$3; shift 3; local out rc; out=$("$@" 2>&1); rc=$?; N=$((N+1))
  if [ $rc = "$want" ] && grep -qF -- "$txt" <<<"$out"; then echo "  PASS $name"; else echo "  FAIL $name (종료 $rc, 기대 $want, '$txt')"; echo "$out" | sed 's/^/       /'; F=$((F+1)); fi; }
bash "$HERE/gen-secrets.sh" --db-only "$T/s" >/dev/null 2>&1
t "생성 직후: 통과" 0 "OK 비밀 파일 권한" bash "$HERE/check-secret-perms.sh" "$T/s"
[ "$(stat -c %a "$T/s")" = 700 ] && [ "$(stat -c %a "$T/s/tokens")" = 700 ] && echo "  PASS 폴더 700" || { echo "  FAIL 폴더 700"; F=$((F+1)); }; N=$((N+1))
# 호스트 전용 이름(계정 암호)을 644 로 만들면 잡는다
echo x > "$T/s/tokens/account-foo-password"; chmod 644 "$T/s/tokens/account-foo-password"
t "계정 평문 암호가 644 이면 FAIL" 1 "account-foo-password 모드 644" bash "$HERE/check-secret-perms.sh" "$T/s"
chmod 600 "$T/s/tokens/account-foo-password"
t "600 으로 고치면 통과" 0 "OK" bash "$HERE/check-secret-perms.sh" "$T/s"
chmod 666 "$T/s/tokens/db-survey-dsn"
t "666(기타 쓰기)은 FAIL" 1 "쓰기 비트" bash "$HERE/check-secret-perms.sh" "$T/s"
chmod 600 "$T/s/tokens/db-survey-dsn"
t "컨테이너가 읽는 파일이 600 이면 FAIL(못 읽는다)" 1 "서비스가 못 읽는다" bash "$HERE/check-secret-perms.sh" "$T/s"
chmod 644 "$T/s/tokens/db-survey-dsn"; chmod 755 "$T/s/tokens"
t "폴더가 755 이면 FAIL" 1 "700 이어야" bash "$HERE/check-secret-perms.sh" "$T/s"
t "비밀 폴더가 없으면 2" 2 "비밀 폴더가 없다" bash "$HERE/check-secret-perms.sh" "$T/none"
# gen-secrets 는 이미 있는 잘못된 모드를 바로잡는다
chmod 700 "$T/s/tokens"; chmod 600 "$T/s/tokens/postgres-password"; bash "$HERE/gen-secrets.sh" --db-only "$T/s" >/dev/null 2>&1
t "gen-secrets 재실행이 모드를 바로잡는다" 0 "OK" bash "$HERE/check-secret-perms.sh" "$T/s"
# 값이 출력에 없다
t "출력에 비밀 값이 없다" 1 "" bash -c "bash '$HERE/check-secret-perms.sh' '$T/s' | grep -F \"\$(cat '$T/s/tokens/postgres-password')\""
echo; [ $F = 0 ] && echo "통과: 비밀 권한 자체 시험 $N건" || { echo "실패: $F건 ($N건)"; exit 1; }
