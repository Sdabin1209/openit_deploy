#!/usr/bin/env bash
# prepare-areas.sh 자기 점검: 임시 워크스페이스에서 (1) --list (2) 성공/실패/스크립트없음을 표로 보고하고 실패해도 나머지를 계속하며 종료 코드 1
# (3) 전부 성공이면 0 (4) 영역 지정 인자 (5) 영역 목록을 읽지 못하면 실패. deploy 자신의 .venv(--no-self)와 실제 영역은 건드리지 않는다.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/head/shared"
cat > "$T/head/shared/areas.json" <<'J'
{"areas": [{"name":"head","kind":"docs","version_train":false},{"name":"a-ok","kind":"python","version_train":false},{"name":"b-fail","kind":"python","version_train":false},
 {"name":"c-none","kind":"node","version_train":false},{"name":"d-ok","kind":"library","version_train":false},{"name":"deploy","kind":"compose","version_train":false}]}
J
export AREAS_FILE="$T/head/shared/areas.json"
for a in a-ok b-fail c-none d-ok; do mkdir -p "$T/$a/scripts"; done
# 영역 setup-env.sh 는 표준 출력 마지막 줄에 SetupEnvReport 를 낸다(계약 v2.6.0). 시험에서는 deploy .venv 의 계약 패키지로 검증한다.
# 계약 패키지가 있는 파이썬: 이 트리의 .venv, 없으면(worktree) 주 작업 트리의 .venv
[ -z "${SETUP_PY:-}" ] && for c in "$HERE/../.venv/bin/python" "$(git -C "$HERE" rev-parse --git-common-dir 2>/dev/null)/../.venv/bin/python"; do [ -x "$c" ] && SETUP_PY=$c && break; done; export SETUP_PY
export SETUP_ENV_DIR="$T/state-setup-env"
rep() { printf "echo ran-%s; echo '{\"area\":\"%s\",\"status\":\"%s\",\"exit_code\":%s,\"seconds\":1,\"environment\":{\"kind\":\"python-venv\",\"path\":\".venv\",\"test_command\":[\".venv/bin/python\",\"-m\",\"pytest\"]}}'; exit %s\n" "$1" "$1" "$2" "$3" "$3"; }
rep a-ok ok 0 > "$T/a-ok/scripts/setup-env.sh"
# 간섭 결함 시험(2026-11-04): setup-env 는 실행 위치에 .venv 를 쓴다. 실제 영역 리포(여기서는 $T/<영역>)에는 쓰이면 안 되고 사본(SETUP_ENV_WORK/<영역>)에만 쓰인다
sed -i '1i mkdir -p .venv; echo x > .venv/marker' "$T/a-ok/scripts/setup-env.sh"
rep b-fail fail 3 > "$T/b-fail/scripts/setup-env.sh"
rep d-ok ok 0 > "$T/d-ok/scripts/setup-env.sh"
for a in a-ok b-fail c-none d-ok; do ( cd "$T/$a" && git init -q && git add -A && git -c user.name=t -c user.email=t@t commit -qm init ); done   # 사본은 실제 리포의 HEAD 를 clone 한다
export SETUP_ENV_WORK="$T/work-areas"
rc=0; N=0
chk() { # chk <설명> <기대 종료코드> <기대 문자열|-> <인자...>
  local d=$1 want=$2 pat=$3; shift 3; N=$((N+1))
  out=$(bash "$HERE/prepare-areas.sh" --ws "$T" --no-self "$@" 2>&1); r=$?
  if [ "$r" = "$want" ] && { [ "$pat" = - ] || grep -qF -- "$pat" <<<"$out"; }; then echo "  ok   $d"; else echo "  FAIL $d (rc=$r)"; echo "$out" | head -12; rc=1; fi
}
chk "--list 는 대상과 스크립트 유무만 보이고 실행하지 않는다" 0 "c-none  준비 스크립트 없음" --list
out=$(bash "$HERE/prepare-areas.sh" --ws "$T" --no-self --list 2>&1); grep -q 'ran-' <<<"$out" && { echo "  FAIL --list 가 실행했다"; rc=1; } || echo "  ok   --list 는 실행하지 않는다"
out=$(bash "$HERE/prepare-areas.sh" --ws "$T" --no-self --list 2>&1); grep -q '^head\b' <<<"$out" && { echo "  FAIL docs 영역(head)이 대상에 들었다"; rc=1; } || echo "  ok   python/node/library 만 대상(head·deploy 제외)"
chk "실패가 있으면 종료 코드 1" 1 "성공하지 못한 것 2개"
chk "실패한 영역 뒤의 영역도 계속 실행한다(d-ok)" 1 "ran-d-ok"
chk "요약표에 성공·실패(종료 3)·스크립트없음을 구분한다" 1 "스크립트없음"
out=$(bash "$HERE/prepare-areas.sh" --ws "$T" --no-self 2>&1); grep -q '실패(종료 3)' <<<"$out" && grep -q 'a-ok  *성공' <<<"$out" && echo "  ok   표: a-ok 성공, b-fail 실패(종료 3)" || { echo "  FAIL 표 내용"; echo "$out"; rc=1; }
chk "성공하는 영역만 지정하면 종료 코드 0" 0 "전부 성공" a-ok d-ok
chk "지정하지 않은 영역은 실행하지 않는다" 0 - a-ok
out=$(bash "$HERE/prepare-areas.sh" --ws "$T" --no-self a-ok 2>&1); grep -q ran-d-ok <<<"$out" && { echo "  FAIL 지정 밖 실행"; rc=1; } || echo "  ok   지정 밖 영역은 실행하지 않았다"
chk "성공하는 영역의 보고를 검증해 state 에 모은다" 0 - a-ok
[ ! -e "$T/a-ok/.venv" ] && [ -z "$(git -C "$T/a-ok" status --porcelain)" ] && echo "  ok   실제 영역 리포에는 .venv 도 변경도 생기지 않았다" || { echo "  FAIL 실제 영역 리포가 바뀌었다(간섭 결함)"; rc=1; }
[ -f "$SETUP_ENV_WORK/a-ok/.venv/marker" ] && [ "$(git -C "$SETUP_ENV_WORK/a-ok" rev-parse HEAD)" = "$(git -C "$T/a-ok" rev-parse HEAD)" ] && echo "  ok   setup-env 는 사본(실제 HEAD 커밋)에서 돌았다" || { echo "  FAIL 사본에서 돌지 않았다"; rc=1; }
# 태그 시험(2026-11-05 E2E 사전 점검 실패): 사본을 다시 맞출 때 원본에 새로 생긴 태그도 가져와야 한다(URL 로 하는 git fetch 는 태그를 따라오지 않는다). 영역 시험이 계약 태그(vX.Y.Z)를 사본에서 읽는다
git -C "$T/a-ok" tag v9.9.9-prep-test
bash "$HERE/prepare-areas.sh" --ws "$T" --no-self a-ok >/dev/null 2>&1
[ "$(git -C "$T/a-ok" tag | sort)" = "$(git -C "$SETUP_ENV_WORK/a-ok" tag | sort)" ] && git -C "$SETUP_ENV_WORK/a-ok" tag | grep -qx v9.9.9-prep-test && echo "  ok   사본의 태그가 원본과 같다(새 태그를 가져온다)" || { echo "  FAIL 사본에 새 태그가 오지 않았다"; rc=1; }
git -C "$T/a-ok" tag v9.9.9-prep-test2
sed 's/fetch -q --tags --force/fetch -q/' "$HERE/prepare-areas.sh" | sed 's|^source "$(dirname "${BASH_SOURCE\[0\]}")/lib.sh"|source "'"$HERE"'/lib.sh"|' > "$T/prepare-areas.nofetchtags.sh"
grep -q 'fetch -q "\$WORKSPACE' "$T/prepare-areas.nofetchtags.sh" || { echo "  FAIL 태그 변이를 만들지 못했다"; rc=1; }
bash "$T/prepare-areas.nofetchtags.sh" --ws "$T" --no-self a-ok >/dev/null 2>&1
git -C "$SETUP_ENV_WORK/a-ok" tag | grep -qx v9.9.9-prep-test2 && { echo "  FAIL 변이(--tags 없음)에서도 태그가 왔다: 시험이 태그를 못 잡는다"; rc=1; } || echo "  ok   변이(--tags 를 뺌)에서는 새 태그가 오지 않아 위 단언이 실패한다"
# 왜 변이 사본을 $T(실행별 mktemp, 종료 때 지워진다)에 두나: 소스 폴더의 고정 이름 파일은 동시 실행끼리 서로 지우고 소스 트리를 더럽힌다
MUT="$T/prepare-areas.mut.sh"
# 변이: 사본 대신 실제 리포에서 돌리는 옛 방식이면 위 단언이 실패해야 한다
sed 's|rc=0; out=$(cd "$c" \&\& bash scripts/setup-env.sh)|rc=0; out=$(cd "$WORKSPACE/$a" \&\& bash scripts/setup-env.sh)|' "$HERE/prepare-areas.sh" | sed 's|^source "$(dirname "${BASH_SOURCE\[0\]}")/lib.sh"|source "'"$HERE"'/lib.sh"|' > "$MUT"
grep -q 'cd "$WORKSPACE/$a" && bash scripts/setup-env.sh' "$MUT" || { echo "  FAIL 변이를 만들지 못했다"; rc=1; }
bash "$MUT" --ws "$T" --no-self a-ok >/dev/null 2>&1
[ -e "$T/a-ok/.venv" ] && echo "  ok   변이(옛 방식)에서는 실제 리포에 .venv 가 생겨 위 단언이 실패한다" || { echo "  FAIL 변이가 실제 리포를 바꾸지 않았다(시험이 껍데기)"; rc=1; }
rm -rf "$T/a-ok/.venv"
[ "$(python3 -c "import json;print(json.load(open('$SETUP_ENV_DIR/a-ok.json'))['environment']['path'])")" = .venv ] && echo "  ok   a-ok 보고가 저장됐다" || { echo "  FAIL 보고 저장"; rc=1; }
printf 'echo not-a-report\n' > "$T/a-ok/scripts/setup-env.sh"; git -C "$T/a-ok" -c user.name=t -c user.email=t@t commit -qam bad;   # 사본은 커밋된 내용으로 돈다
 chk "마지막 줄이 SetupEnvReport 가 아니면 실패로 센다" 1 "계약 위반" a-ok
chk "대상이 아닌 이름은 사용 오류(2)" 2 "대상 영역이 아니다" nope
rm -rf "$T/d-ok"; chk "영역 폴더가 없으면 실패로 보고" 1 "폴더없음" d-ok
rm "$T/head/shared/areas.json"; chk "영역 목록을 읽지 못하면 실패(1)" 1 "영역 목록을 읽지 못했다"
[ $rc = 0 ] && echo "통과: prepare-areas 자체 시험" || exit 1
