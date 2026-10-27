#!/usr/bin/env bash
# 비밀 파일 권한 점검(읽기 전용, 값은 읽지도 출력하지도 않는다). 사용: check-secret-perms.sh [비밀 폴더]   (기본 $SECRETS_DIR 또는 secrets/)
# 규칙(docs/adr/0003): 폴더 700. 호스트 전용 파일(lib.sh secret_mode 가 600)은 600/400. 컨테이너가 읽는 파일은 644(폴더 700 안)까지.
# 그룹·기타 쓰기 비트는 어디서든 FAIL. 호스트 전용인데 644 이면 FAIL(평문 계정 암호 등). 컨테이너가 읽는데 600 이면 FAIL(서비스가 못 읽는다).
# 종료 코드 0 통과, 1 어긋남 있음, 2 비밀 폴더 없음. doctor.sh 가 --up 에서 부른다.
set -uo pipefail
DEPLOY_NO_DOCKER=1; source "$(dirname "$0")/lib.sh"
D=${1:-${SECRETS_DIR:-$DEPLOY_ROOT/secrets}}
[ -d "$D" ] || { echo "비밀 폴더가 없다: $D" >&2; exit 2; }
bad=0
for d in "$D" "$D/tokens"; do [ -d "$d" ] || continue
  m=$(stat -c %a "$d"); [ "$m" = 700 ] || { echo "FAIL 폴더 모드 $m (700 이어야 한다): ${d#$D}/ (해결: chmod 700 $d)"; bad=$((bad+1)); }; done
for f in "$D"/tokens/* "$D"/gateway-accounts.caddy "$D"/gateway-devices.caddy; do [ -f "$f" ] || continue
  n=$(basename "$f"); m=$(stat -c %a "$f"); want=$(secret_mode "$n")
  case "$n" in gateway-*.caddy) want=644;; esac   # compose configs 로 컨테이너(caddy)가 읽는다
  if (( 8#$m & 8#022 )); then echo "FAIL $n 모드 $m: 그룹·기타 쓰기 비트가 있다"; bad=$((bad+1))
  elif [ "$want" = 600 ] && (( 8#$m & 8#077 )); then echo "FAIL $n 모드 $m: 호스트 전용 비밀은 600 이어야 한다 (chmod 600; gen-secrets.sh 를 다시 실행하면 바로잡는다)"; bad=$((bad+1))
  elif [ "$want" = 644 ] && ! (( 8#$m & 8#004 )); then echo "FAIL $n 모드 $m: 컨테이너(uid 10001)가 읽는 파일인데 기타 읽기가 없다 -> 서비스가 못 읽는다 (gen-secrets.sh 를 다시 실행)"; bad=$((bad+1)); fi
done
[ $bad = 0 ] && { echo "OK 비밀 파일 권한 ($(ls "$D/tokens" 2>/dev/null | wc -l)개 + 게이트웨이 설정 2개)"; exit 0; } || { echo "비밀 권한 어긋남 ${bad}건"; exit 1; }
