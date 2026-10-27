#!/usr/bin/env bash
# E2E 결과 한 줄을 docs/E2E_RESULTS.md 의 "실행 기록" 표에 더한다. 숫자는 e2e.sh 로그에서 파싱한다(손으로 적지 않는다).
# 사용: scripts/record-e2e.sh [옵션] <로그 파일>...        (e2e.sh 가 끝에서 부른다. 파일은 이어 붙여 읽는다)
#   로그에 있어야 하는 것: 'PASS n / FAIL m' 줄, 'E2E 결과' 줄(모드·종료), '== 요약 (단계 1~8)' 표, check-all 의 '-- 결과: FAIL a, SKIP b, PASS c' 줄.
#   하나라도 파싱하지 못하면 아무것도 더하지 않고 종료 코드 2 로 실패한다.
#   --when 'YYYY-MM-DD HH:MM'  기본은 지금.   --env 텍스트  기본은 WSL2 또는 Linux(E2E_ENV 로도 지정).   --source 텍스트  기본 'e2e.sh 로그 자동 기록'.
#   --manual  로그 없이 값을 직접 준다(헤드가 직접 돌린 기록처럼 로그 파일이 이 리포에 없을 때). 필수: --source --commit --mode 전체|--fast --pass --fail --exit
#             --ca-fail --ca-skip --ca-pass.  --blocked --test-sub 는 모르면 생략('미기록').
#   --file PATH   기본 docs/E2E_RESULTS.md (시험용).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
FILE="$ROOT/docs/E2E_RESULTS.md"; WHEN=""; ENVT="${E2E_ENV:-}"; SRC=""; MANUAL=0
COMMIT=""; MODE=""; P=""; F=""; EX=""; CAF=""; CAS=""; CAP=""; BL=""; TS=""; LOGS=()
die() { echo "record-e2e.sh: $*" >&2; exit 2; }
while [ $# -gt 0 ]; do case "$1" in
  --when) WHEN=${2:?}; shift 2;; --env) ENVT=${2:?}; shift 2;; --source) SRC=${2:?}; shift 2;; --file) FILE=${2:?}; shift 2;;
  --manual) MANUAL=1; shift;; --commit) COMMIT=${2:?}; shift 2;; --mode) MODE=${2:?}; shift 2;;
  --pass) P=${2:?}; shift 2;; --fail) F=${2:?}; shift 2;; --exit) EX=${2:?}; shift 2;;
  --ca-fail) CAF=${2:?}; shift 2;; --ca-skip) CAS=${2:?}; shift 2;; --ca-pass) CAP=${2:?}; shift 2;;
  --blocked) BL=${2:?}; shift 2;; --test-sub) TS=${2:?}; shift 2;;
  -*) die "모르는 옵션 $1";; *) LOGS+=("$1"); shift;; esac; done
[ -f "$FILE" ] || die "$FILE 이 없다"
grep -q '^<!-- E2E-ROWS-END -->$' "$FILE" || die "$FILE 에 '<!-- E2E-ROWS-END -->' 표식이 없다"
isnum() { [[ "${1:-}" =~ ^[0-9]+$ ]]; }
if [ $MANUAL = 1 ]; then
  [ -n "$SRC" ] || die "--manual 은 --source 가 필수다"
  [ -n "$COMMIT" ] && [ -n "$MODE" ] || die "--manual 은 --commit 과 --mode 가 필수다"
  SRC="수동 입력: $SRC"; BL=${BL:-미기록}; TS=${TS:-미기록}
else
  [ ${#LOGS[@]} -gt 0 ] || die "로그 파일이 없다"
  TXT=""; for l in "${LOGS[@]}"; do [ -r "$l" ] || die "로그를 읽을 수 없다: $l"; TXT+="$(cat "$l")"$'\n'; done
  line=$(grep -E '^ +PASS [0-9]+ / FAIL [0-9]+$' <<<"$TXT" | tail -1) || true
  [ -n "$line" ] || die "로그에서 'PASS n / FAIL m' 줄을 찾지 못했다"
  P=$(sed -E 's/^ +PASS ([0-9]+) \/ FAIL ([0-9]+)$/\1/' <<<"$line"); F=$(sed -E 's/^ +PASS ([0-9]+) \/ FAIL ([0-9]+)$/\2/' <<<"$line")
  ca=$(grep -E '^-- 결과: FAIL [0-9]+, SKIP [0-9]+, PASS [0-9]+ / 규칙' <<<"$TXT" | tail -1) || true
  [ -n "$ca" ] || die "로그에서 check-all 의 '-- 결과: FAIL a, SKIP b, PASS c' 줄을 찾지 못했다 (check-all 출력을 함께 준다)"
  re='^-- 결과: FAIL ([0-9]+), SKIP ([0-9]+), PASS ([0-9]+) /'
  [[ "$ca" =~ $re ]]; CAF=${BASH_REMATCH[1]}; CAS=${BASH_REMATCH[2]}; CAP=${BASH_REMATCH[3]}
  if grep -qE '^E2E 결과\(--fast\)|^-- FAST 모드' <<<"$TXT"; then MODE="--fast"
  elif grep -qE '^E2E 결과: ' <<<"$TXT"; then MODE="전체"
  else die "로그에서 'E2E 결과' 줄(모드)을 찾지 못했다"; fi
  if grep -qE '^E2E 결과: 실패 있음' <<<"$TXT"; then EX=1; else EX=0; fi
  grep -qE '^== 요약 \(단계 1~8\)' <<<"$TXT" || die "로그에서 '== 요약 (단계 1~8)' 표를 찾지 못했다"
  sect=$(awk '/^== 요약 \(단계 1~8\)/{on=1;next} on&&/^== /{exit} on&&/^$/{exit} on{print}' <<<"$TXT")
  BL=$(grep -cE '^ +[0-9A-Za-z_]+ +BLOCKED ' <<<"$sect" || true); TS=$(grep -cE '^ +[0-9A-Za-z_]+ +TEST-SUB ' <<<"$sect" || true)
  [ -n "$sect" ] || die "'== 요약 (단계 1~8)' 표가 비었다"
  COMMIT=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null) || die "git 커밋 해시를 읽지 못했다"
  if [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no -- . ':!docs/E2E_RESULTS.md' 2>/dev/null)" ]; then COMMIT="$COMMIT+dirty"; fi
  [ -n "$SRC" ] || SRC="e2e.sh 로그 자동 기록"
  if [ -z "$ENVT" ]; then if grep -qi microsoft /proc/version 2>/dev/null; then ENVT="이 PC (WSL2)"; else ENVT="Linux"; fi; fi
fi
for v in "$P" "$F" "$EX" "$CAF" "$CAS" "$CAP"; do isnum "$v" || die "숫자가 아닌 값: '$v'"; done
[ "$MODE" = "전체" ] || [ "$MODE" = "--fast" ] || die "모드는 전체 또는 --fast"
[ -n "$ENVT" ] || ENVT="이 PC"
[ -n "$WHEN" ] || WHEN=$(date '+%F %H:%M')
ROW="| $WHEN | $COMMIT | $ENVT | $MODE | $P | $F | $EX | $CAF/$CAS/$CAP | $BL | $TS | $SRC |"
if grep -qxF -- "$ROW" "$FILE"; then echo "이미 같은 줄이 있다: 더하지 않음"; exit 0; fi
TMP=$(mktemp); awk -v row="$ROW" '/^<!-- E2E-ROWS-END -->$/{print row} {print}' "$FILE" > "$TMP" && cat "$TMP" > "$FILE"; rm -f "$TMP"
echo "E2E_RESULTS.md 에 기록: $ROW"
