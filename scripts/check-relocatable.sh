#!/usr/bin/env bash
# 이 워크스페이스가 다른 서버·다른 PC·다른 루트 폴더 이름에서도 도는지 확인한다. 유일한 전제는 "형제 폴더 배치"(deploy 의 상위 폴더에 리포들이 나란히 있음,
# 폴더 이름은 head/workspace.yaml 과 같아야 한다)다.
#  (a) 정적 검사: 형제 리포 전부의 git 추적 파일에 절대 경로(/home/, /Users/, 드라이브 문자, /mnt/<드라이브>/, \\wsl), 이 워크스페이스 이름(sdabin, healthKiosk),
#      이 PC의 호스트 이름이 박혀 있지 않은지. 허용 목록은 scripts/relocatable-allow.txt (이유 주석 필수).
#      (GitHub 원격 주소의 계정 이름은 경로가 아니라 저장소 주소라 검사하지 않는다. OS 사용자 이름 자체는 흔한 낱말이라 `/home/<이름>` 경로 꼴로만 잡는다.)
#  (b) 이동 시험: 임시 폴더 ws-relocate-XXXX/ 에 각 리포를 로컬 경로 git clone(원격·키 불필요) 한 뒤, 그 안의 deploy 에서 scripts/e2e.sh --fast 가 통과하는가.
#      이미지는 새로 만든다(네트워크 필요, docker 층 캐시가 있으면 빠르다). 다른 이미지를 지우지 않도록 --keep-images 로 돌린다. 끝나면 임시 폴더를 지운다.
# 사용: scripts/check-relocatable.sh [--static-only | --relocate-only]
set -uo pipefail
DEPLOY_NO_DOCKER=1   # 정적 검사에는 docker 가 필요 없다. 이동 시험에서만 detect_docker 를 부른다
source "$(dirname "$0")/lib.sh"
[ -z "${CHECK_RELOCATABLE_WORKSPACE:-}" ] || WORKSPACE=$CHECK_RELOCATABLE_WORKSPACE   # 시험용(test-check-relocatable.sh): 임시 워크스페이스를 검사한다
MODE=${1:-all}
FAILS=0; ok() { echo "  [PASS] $1"; }; ng() { echo "  [FAIL] $1"; FAILS=$((FAILS+1)); }
REPOS=(); for d in "$WORKSPACE"/*/; do d=${d%/}; [ -e "$d/.git" ] && REPOS+=("$(basename "$d")"); done
echo "워크스페이스 리포 ${#REPOS[@]}개: ${REPOS[*]}"

static_check() {
  echo "== (a) 정적 검사: 추적 파일에 절대 경로·워크스페이스 이름·호스트 이름"
  local HN; HN=$(hostname 2>/dev/null || true)
  # 드라이브 경로는 `X:\\` 뒤에 또 `\\`(이스케이프된 경로) 또는 대문자·숫자(Users, Windows, 2024)가 오는 꼴만 잡는다.
  # 왜: `X:\\n`(printf 의 YAML 문자열 'j:\\n')은 개행 이스케이프라 경로가 아니다. 소문자로 시작하는 폴더(`C:\\users`)는 이스케이프와 구분되지 않아 놓친다(감수).
  local pat='/home/[A-Za-z]|/Users/[A-Za-z]|(^|[^A-Za-z])[A-Za-z]:\\(\\|[A-Z0-9])|/mnt/[a-z]/|\\\\wsl|sdabin|healthKiosk'
  [ "${#HN}" -ge 4 ] && pat="$pat|(^|[^A-Za-z0-9])$HN([^A-Za-z0-9]|\$)"
  local allow; allow=$(grep -v '^#' "$DEPLOY_ROOT/scripts/relocatable-allow.txt" | sed 's/[[:space:]]*#.*$//' | grep -v '^$')
  local total=0 bad=0
  for r in "${REPOS[@]}"; do
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      total=$((total+1))
      f=${line%%:*}; skip=0
      while IFS= read -r a; do [ -n "$a" ] || continue; rr=${a%%:*}; rx=${a#*:}; [ "$rr" = "$r" ] && echo "$f" | grep -Eq "$rx" && skip=1; done <<< "$allow"
      [ $skip = 1 ] && continue
      bad=$((bad+1)); echo "    $r/$line" | cut -c1-200
    done < <(git -C "$WORKSPACE/$r" grep -I -n -E "$pat" 2>/dev/null | head -50)
  done
  [ $bad = 0 ] && ok "형제 리포 ${#REPOS[@]}개의 추적 파일에 박힌 절대 경로·이름이 없다 (허용 목록 밖 0건)" || ng "허용 목록 밖 $bad건 (위)"
}

relocate_check() {
  detect_docker   # 데몬에 못 닿으면 여기서 명확한 오류로 멈춘다
  echo "== (b) 이동 시험: 다른 루트 이름(ws-relocate-XXXX)에 clone 해 deploy 의 e2e --fast"
  local T; T=$(mktemp -d "${TMPDIR:-/tmp}/ws-relocate-XXXX")
  # shellcheck disable=SC2064
  trap "rm -rf '$T'" RETURN
  for r in "${REPOS[@]}"; do git clone -q --no-hardlinks "$WORKSPACE/$r" "$T/$r" 2>/dev/null || { ng "clone $r"; return; }; done
  ok "리포 ${#REPOS[@]}개를 $T 로 clone (로컬 경로, 원격 아님)"
  [ -f "$T/deploy/scripts/e2e.sh" ] || { ng "clone 안에 deploy/scripts/e2e.sh 가 없다"; return; }
  # 새 clone 에는 영역 .venv/node_modules 가 없어 check-all --strict 가 SKIP 으로 E2E 를 시작하지 못한다 -> 먼저 영역 환경을 준비한다(prepare-areas.sh: 각 영역 setup-env.sh)
  ( cd "$T/deploy" && bash scripts/prepare-areas.sh > "$T/prepare.log" 2>&1 ); local prc=$?
  if [ $prc != 0 ]; then ng "이동한 워크스페이스에서 prepare-areas.sh 실패(종료 코드 $prc): 영역 환경을 준비하지 못해 e2e 를 시작하지 않는다"; tail -25 "$T/prepare.log" | cut -c1-250; return; fi
  ok "이동한 워크스페이스에서 영역 환경 준비(prepare-areas.sh)"
  ( cd "$T/deploy" && bash scripts/e2e.sh --fast --keep-images > "$T/e2e.log" 2>&1 ); local rc=$?
  grep -a -E "PASS [0-9]+ / FAIL|E2E 결과" "$T/e2e.log" | cut -c1-200
  if [ $rc = 0 ]; then ok "이동한 워크스페이스에서 e2e.sh --fast 통과"; else ng "이동한 워크스페이스에서 e2e.sh --fast 실패(종료 코드 $rc)"; grep -a "FAIL\]" "$T/e2e.log" | head -5 | cut -c1-250; echo "  --- e2e.log 마지막 40줄 ---"; tail -40 "$T/e2e.log" | cut -c1-250; fi
}

[ "$MODE" = --relocate-only ] || static_check
[ "$MODE" = --static-only ] || relocate_check
echo; [ "$FAILS" = 0 ] && echo "check-relocatable: 전부 통과" || echo "check-relocatable: 실패 $FAILS건"
exit $([ "$FAILS" = 0 ] && echo 0 || echo 1)
