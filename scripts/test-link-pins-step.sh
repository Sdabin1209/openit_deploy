#!/usr/bin/env bash
# e2e.sh 시작 점검의 link 핀 대조 단계 자체 시험(빠름, Docker·E2E 실행 없음). 선택 단계가 한 번도 안 돌아 깨진 줄 모르던 일(VENV 미정으로 "/bin/python: No such file")을 막는다.
# 확인: (1) e2e.sh 에서 이 단계가 lib.sh 를 source 한 뒤에 있고 그 앞에서 VENV·DEPLOY_PY 를 쓰지 않는다 (2) 기본값이 켜짐(1) (3) e2e.sh 의 그 블록을 그대로 꺼내 lib.sh 를 source 한 셸에서 실제로 실행: 핀이 맞으면 통과, 어긋나면 멈춘다
#   (4) 단독 스크립트 check-link-pins.sh 가 VENV 를 미리 정하지 않은 환경·다른 작업 폴더에서도 돈다. 가짜 워크스페이스(git 리포 + main)를 쓰고 이웃의 실제 파일을 읽지 않는다.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; E="$HERE/e2e.sh"; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; N=0; F=0
ok()  { N=$((N+1)); local name=$1; shift; if "$@" >"$T/out" 2>&1; then echo "  PASS $name"; else echo "  FAIL $name"; sed 's/^/     /' "$T/out" | tail -4; F=$((F+1)); fi; }
no()  { N=$((N+1)); local name=$1; shift; if "$@" >"$T/out" 2>&1; then echo "  FAIL $name (성공했다)"; F=$((F+1)); else echo "  PASS $name"; fi; }
DEPLOY_NO_DOCKER=1; source "$HERE/lib.sh"; TAG=$DEPLOY_LINK_TAG
pin_line=$(grep -n 'check-link-pins.sh' "$E" | head -1 | cut -d: -f1); src_line=$(grep -n '^source "\$(dirname "\$0")/lib.sh"' "$E" | head -1 | cut -d: -f1)
ok "e2e.sh: 핀 대조 단계가 lib.sh 를 source 한 뒤에 있다(줄 $pin_line > $src_line)" bash -c "[ -n '$pin_line' ] && [ -n '$src_line' ] && [ '$pin_line' -gt '$src_line' ]"
no "e2e.sh: lib.sh 를 source 하기 전에 \$VENV·\$DEPLOY_PY 를 쓰지 않는다" bash -c "head -n $((src_line-1)) '$E' | grep -v '^\\s*#' | grep -E '\\\$\\{?(VENV|DEPLOY_PY)\\b'"
ok "e2e.sh: 기본값이 켜짐(DEPLOY_CHECK_LINK_PINS:-1)" grep -q 'DEPLOY_CHECK_LINK_PINS:-1' "$E"
# 가짜 워크스페이스
g=(git -c user.name=t -c user.email=t@t)
mkws() { local d=$1 tag=$2; mkdir -p "$d/head/shared" "$d/area-a"; printf '{"areas":[{"name":"area-a","kind":"python","version_train":false}]}' > "$d/head/shared/areas.json"
  git init -q -b main "$d/area-a"; printf 'openit-link @ git+ssh://git@github.com/Sdabin1209/openit_link.git@%s\n' "$tag" > "$d/area-a/requirements.lock"; printf x > "$d/area-a/README.md"; "${g[@]}" -C "$d/area-a" add -A; "${g[@]}" -C "$d/area-a" commit -qm x; }
mkws "$T/good" "$TAG"; mkws "$T/bad" v0.0.1
# e2e.sh 의 블록을 그대로 꺼내 실행한다(lib.sh source 뒤, VENV 는 lib.sh 가 정한 것만)
sed -n '/^# link 핀 대조(U59/,/^fi$/p' "$E" > "$T/block.sh"
run_block() { ( cd /; unset VENV DEPLOY_PY; export LINK_PINS_WS="$1" DEPLOY_ROOT="$HERE/.."; DEPLOY_NO_DOCKER=1; source "$HERE/lib.sh"; source "$T/block.sh" ); }
ok "e2e.sh 블록: 핀이 맞으면 통과한다" run_block "$T/good"
no "e2e.sh 블록: 핀이 어긋나면 멈춘다(종료 1)" run_block "$T/bad"
ok "e2e.sh 블록: DEPLOY_CHECK_LINK_PINS=0 이면 건너뛴다(어긋나도 통과)" env DEPLOY_CHECK_LINK_PINS=0 bash -c "$(declare -f run_block); HERE='$HERE'; T='$T'; run_block '$T/bad'"
ok "check-link-pins.sh: 다른 작업 폴더·VENV 없는 환경에서도 돈다" bash -c "cd /; env -u VENV -u DEPLOY_PY LINK_PINS_WS='$T/good' bash '$HERE/check-link-pins.sh'"
echo; [ $F = 0 ] && echo "통과: link 핀 대조 단계 자체 시험 ${N}건" || { echo "실패: $F건 ($N건)"; exit 1; }
