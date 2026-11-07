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
chmod 666 "$T/s/tokens/pg-superuser-survey"
t "666(기타 쓰기)은 FAIL" 1 "쓰기 비트" bash "$HERE/check-secret-perms.sh" "$T/s"
chmod 600 "$T/s/tokens/pg-superuser-survey"
t "컨테이너가 읽는 파일이 600 이면 FAIL(못 읽는다)" 1 "서비스가 못 읽는다" bash "$HERE/check-secret-perms.sh" "$T/s"
chmod 644 "$T/s/tokens/pg-superuser-survey"
t "컨테이너가 읽는 파일이 644 이면 FAIL(L02: 기타 접근은 없어야 한다)" 1 "pg-superuser-survey 모드 644" bash "$HERE/check-secret-perms.sh" "$T/s"
chmod 640 "$T/s/tokens/pg-superuser-survey"
t "640 이고 그룹이 SECRETS_GID 면 통과" 0 "OK" bash "$HERE/check-secret-perms.sh" "$T/s"
t "그룹이 SECRETS_GID 와 다르면 FAIL(컨테이너 group_add 와 어긋난다)" 1 "group_add" env SECRETS_GID=64999 bash "$HERE/check-secret-perms.sh" "$T/s"
t "생성 직후 컨테이너가 읽는 파일은 640" 0 "640" bash -c "stat -c %a '$T/s/tokens/pg-superuser-survey'"
chmod 644 "$T/s/tokens/pg-superuser-survey"; chmod 755 "$T/s/tokens"
t "폴더가 755 이면 FAIL" 1 "700 이어야" bash "$HERE/check-secret-perms.sh" "$T/s"
t "비밀 폴더가 없으면 2" 2 "비밀 폴더가 없다" bash "$HERE/check-secret-perms.sh" "$T/none"
# gen-secrets 는 이미 있는 잘못된 모드를 바로잡는다
chmod 700 "$T/s/tokens"; chmod 600 "$T/s/tokens/pg-superuser-survey"; bash "$HERE/gen-secrets.sh" --db-only "$T/s" >/dev/null 2>&1
t "gen-secrets 재실행이 모드를 바로잡는다" 0 "OK" bash "$HERE/check-secret-perms.sh" "$T/s"
# 값이 출력에 없다
t "출력에 비밀 값이 없다" 1 "" bash -c "bash '$HERE/check-secret-perms.sh' '$T/s' | grep -F \"\$(cat '$T/s/tokens/pg-superuser-survey')\""
# 다른 호스트의 추론 서버가 읽는 토큰 파일도 640 + 그룹이다(RUNTIME.md R6.3): 644 로 누구나 읽게 하지 않는다
for nm in model-runtime-tokens gate-read-model-serving external-inference; do
  [ "$(DEPLOY_NO_DOCKER=1 bash -c 'source "$1/lib.sh"; secret_mode "$2"' _ "$HERE" "$nm")" = 640 ] && echo "  PASS secret_mode $nm = 640" || { echo "  FAIL secret_mode $nm 가 640 이 아니다"; F=$((F+1)); }; N=$((N+1))
  rm -rf "$T/s2"; mkdir -p "$T/s2/tokens"; chmod 700 "$T/s2" "$T/s2/tokens"; echo x > "$T/s2/tokens/$nm"; chmod 644 "$T/s2/tokens/$nm"
  t "$nm 가 644 이면 FAIL" 1 "$nm 모드 644" bash "$HERE/check-secret-perms.sh" "$T/s2"
  chmod 640 "$T/s2/tokens/$nm"; chgrp "${SECRETS_GID:-$(id -g)}" "$T/s2/tokens/$nm" 2>/dev/null
  t "$nm 가 640 + 그룹이면 통과" 0 "OK 비밀 파일 권한" bash "$HERE/check-secret-perms.sh" "$T/s2"
done
echo; [ $F = 0 ] && echo "통과: 비밀 권한 자체 시험 $N건" || { echo "실패: $F건 ($N건)"; exit 1; }
