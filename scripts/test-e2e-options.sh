#!/usr/bin/env bash
# e2e.sh 옵션 처리 자체 시험(빠름, Docker·E2E 실행 없음). 사용: bash scripts/test-e2e-options.sh
# 확인: --help/-h 는 사용법만 내고 0, 모르는 옵션·값 없는 옵션·잘못된 --sections·--only 와 --sections 조합은 사용법을 표준 오류로 내고 2. 모두 정적 점검(check-all)·doctor·빌드 앞에서 끝나야 한다(시험마다 20초 상한).
HERE="$(cd "$(dirname "$0")" && pwd)"; E="$HERE/e2e.sh"; N=0; F=0
t() { local name=$1 want=$2 grep_stream=$3 pat=$4; shift 4; N=$((N+1)); local o e rc; o=$(timeout 20 bash "$E" "$@" 2>"$HERE/.e2e-opt.err"); rc=$?; e=$(cat "$HERE/.e2e-opt.err"); rm -f "$HERE/.e2e-opt.err"
  local text=$o; [ "$grep_stream" = err ] && text=$e
  if [ $rc = "$want" ] && grep -q -- "$pat" <<<"$text" && ! grep -q "E2E 합격 시나리오 실행\|== 정적\|check-all" <<<"$o$e"; then echo "  PASS $name (종료 $rc)"; else echo "  FAIL $name (종료 $rc, 기대 $want, 패턴 '$pat')"; echo "$text" | head -3 | sed 's/^/       /'; F=$((F+1)); fi; }
t "--help 는 사용법만 내고 0" 0 out "사용:" --help
t "-h 도 같다" 0 out "사용:" -h
t "모르는 옵션은 사용법을 표준 오류로 내고 2" 2 err "알 수 없는 옵션" --bogus
t "--only 에 값이 없으면 2" 2 err "단계 목록" --only
t "--sections 에 값이 없으면 2" 2 err "jobs,backup,rollback" --sections
t "--sections 에 모르는 구간이 있으면 2" 2 err "알 수 없는 구간" --sections backup,foo
t "--only 와 --sections 를 함께 주면 2(뒷구간은 단계 1~8 의 상태를 전제한다)" 2 err "함께 쓸 수 없다" --only 5r --sections jobs,backup,rollback
t "옵션 뒤에 모르는 옵션이 섞여도 실행 전에 2" 2 err "알 수 없는 옵션" --fast --nope
echo; [ $F = 0 ] && echo "통과: e2e 옵션 처리 자체 시험 ${N}건" || { echo "실패: $F건 ($N건)"; exit 1; }
