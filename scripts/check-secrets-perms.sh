#!/usr/bin/env bash
# 비밀 폴더의 권한을 확인한다(읽기 전용, 값은 읽지 않는다). 사용: check-secrets-perms.sh [비밀 폴더]  (기본 secrets/). 종료 코드 0 통과, 1 위반, 2 폴더 없음.
# 규칙: 폴더(secrets, tokens, handout)는 700, 소유자는 실행 사용자, 파일은 다른 사용자에게 쓰기 불가이며 심볼릭 링크가 아니다. handout/ 의 파일은 0600.
# 파일이 644 인 것은 허용한다(알려진 한계): compose 의 파일 secrets 는 호스트 모드를 그대로 바인드 마운트하고 컨테이너 사용자(uid 10001, postgres 999 등)가 호스트 소유자와 달라 600 이면 읽지 못한다. 폴더 700 이 호스트 다른 사용자를 막는다.
set -uo pipefail
D=${1:-$(cd "$(dirname "$0")/.." && pwd)/secrets}
[ -d "$D" ] || { echo "비밀 폴더가 없다: $D"; exit 2; }
me=$(id -u); BAD=()
for d in "$D" "$D/tokens" "$D/handout"; do
  [ -d "$d" ] || continue
  [ "$(stat -c %a "$d")" = 700 ] || BAD+=("$d: 폴더 모드 $(stat -c %a "$d") (700 이어야 한다)")
  [ "$(stat -c %u "$d")" = "$me" ] || BAD+=("$d: 소유자가 실행 사용자가 아니다")
done
while IFS= read -r f; do
  [ -L "$f" ] && { BAD+=("$f: 심볼릭 링크"); continue; }
  m=$(stat -c %a "$f"); case "$m" in *[2367]) BAD+=("$f: 다른 사용자 쓰기 가능($m)");; esac; case "$m" in ?[2367]?) BAD+=("$f: 그룹 쓰기 가능($m)");; esac
  case "$f" in "$D/handout/"*) [ "$m" = 600 ] || BAD+=("$f: handout 파일은 600 이어야 한다($m)");; esac
done < <(find "$D" -mindepth 1 \( -type f -o -type l \))
n=$(find "$D" -type f | wc -l)
if [ ${#BAD[@]} = 0 ]; then echo "비밀 파일 $n개 권한 통과 (폴더 700; 파일 644 허용: compose 파일 secrets 한계)"; exit 0; fi
printf '권한 위반 %s건:\n' "${#BAD[@]}"; printf '  %s\n' "${BAD[@]}"; exit 1
