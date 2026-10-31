#!/usr/bin/env bash
# 새 머신에서 영역 시험 환경을 한 번에 준비한다: 각 영역이 소유한 scripts/setup-env.sh 를 차례로 실행하고 요약표를 낸다.
# 사용: scripts/prepare-areas.sh [--list] [--ws DIR] [--no-self] [영역 이름...]
#   (인자 없음)  head/shared/areas.json 의 python/node/library 영역 전부 + deploy 자신의 .venv(prepare-host.sh venv)
#   --list       실행하지 않고 대상과 각 setup-env.sh 의 유무만 보인다
#   --ws DIR     워크스페이스 위치(시험용. 기본: 이 리포의 상위 폴더)
#   --no-self    deploy 자신의 .venv 준비를 건너뛴다(시험용)
#   이름을 주면 그 영역만 한다(deploy 는 자기 .venv). 종료 코드: 0=전부 성공, 1=하나라도 실패·스크립트 없음, 2=사용 오류
# 왜 순차인가: 병렬이면 출력이 섞이고 pip 캐시가 경합한다. 하나 실패해도 나머지는 계속한다(새 머신에서 고칠 것을 한 번에 보려고).
# 영역 설치 명령은 여기에 적지 않는다: 각 영역의 setup-env.sh 가 정본이다(영역 목록 정본: head/shared/areas.json). 비밀 값을 다루지 않는다.
set -uo pipefail
DEPLOY_NO_DOCKER=1
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
LIST=0; SELF=1; ONLY=()
while [ $# -gt 0 ]; do case "$1" in
  --list) LIST=1; shift;;
  --no-self) SELF=0; shift;;
  --ws) [ $# -ge 2 ] || { echo "--ws 에는 폴더가 필요하다" >&2; exit 2; }; WORKSPACE=$2; shift 2;;
  -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  -*) echo "알 수 없는 인자: $1 (사용: prepare-areas.sh [--list] [--ws DIR] [--no-self] [영역...])" >&2; exit 2;;
  *) ONLY+=("$1"); shift;; esac; done
AF="${AREAS_FILE:-$WORKSPACE/head/shared/areas.json}"
if ! ALL=$("$DEPLOY_PY" "$DEPLOY_ROOT/scripts/areas.py" --file "$AF" --kind python,node,library); then
  echo "prepare-areas: 영역 목록을 읽지 못했다($AF). 먼저 head 를 clone 하고 head/setup.sh 를 실행한다(docs/SETUP.md 1단계)" >&2; exit 1; fi
if [ ${#ONLY[@]} -gt 0 ]; then
  TARGETS=(); WANT_SELF=0
  for n in "${ONLY[@]}"; do
    if [ "$n" = deploy ]; then WANT_SELF=1; continue; fi
    case " $ALL " in *" $n "*) TARGETS+=("$n");; *) echo "prepare-areas: 대상 영역이 아니다: $n (대상: $ALL deploy)" >&2; exit 2;; esac
  done
  SELF=$WANT_SELF
else read -r -a TARGETS <<< "$ALL"; fi

# 영역의 setup-env.sh 를 돌리고 표준 출력 마지막 줄(SetupEnvReport)을 계약 validator 로 검증해 state/setup-env/ 에 모은다(U43: doctor·check-all 은 이 보고만 쓴다).
# 왜 한 번만 검증하나: 영역이 낸 값은 받는 쪽이 다시 검증하지 않는다(R7). 보고가 계약을 어기면 그 영역은 실패로 센다.
setup_one() {
  local a=$1 out rc py=${SETUP_PY:-$DEPLOY_ROOT/.venv/bin/python}   # deploy 자신의 .venv 는 위에서 먼저 준비한다(계약 패키지가 거기 있다)
  [ -x "$py" ] || py=python3
  rc=0; out=$(cd "$WORKSPACE/$a" && bash scripts/setup-env.sh) || rc=$?
  printf '%s\n' "$out" | sed '$d'
  printf '%s\n' "$out" | "$py" "$DEPLOY_ROOT/scripts/setup_env_report.py" record "$a" || { [ $rc = 0 ] && rc=70; }
  return $rc
}
NAMES=(); STATUS=(); SECS=(); FAILS=0
run_one() { # run_one <이름> <명령...>: 로그는 그대로 보이고 결과만 기록한다
  local name=$1; shift; local t0=$SECONDS rc st
  echo "== $name"
  "$@"; rc=$?
  [ $rc = 0 ] && st="성공" || { st="실패(종료 $rc)"; FAILS=$((FAILS+1)); }
  NAMES+=("$name"); STATUS+=("$st"); SECS+=("$((SECONDS-t0))")
}
missing() { echo "  준비 스크립트 없음: $1 (영역이 scripts/setup-env.sh 를 아직 갖지 않았다)"; NAMES+=("$2"); STATUS+=("스크립트없음"); SECS+=(0); FAILS=$((FAILS+1)); }

if [ $LIST = 1 ]; then
  [ $SELF = 1 ] && echo "deploy  (자기 .venv: scripts/prepare-host.sh venv)"
  for a in "${TARGETS[@]}"; do
    if [ -f "$WORKSPACE/$a/scripts/setup-env.sh" ]; then echo "$a  scripts/setup-env.sh 있음"; else echo "$a  준비 스크립트 없음"; fi
  done; exit 0; fi

if [ $SELF = 1 ]; then run_one deploy bash "$DEPLOY_ROOT/scripts/prepare-host.sh" venv; fi
for a in "${TARGETS[@]}"; do
  s="$WORKSPACE/$a/scripts/setup-env.sh"
  if [ ! -d "$WORKSPACE/$a" ]; then echo "== $a"; echo "  영역 폴더가 없다: $WORKSPACE/$a (head/setup.sh 로 받는다)"; NAMES+=("$a"); STATUS+=("폴더없음"); SECS+=(0); FAILS=$((FAILS+1))
  elif [ ! -f "$s" ]; then echo "== $a"; missing "$a/scripts/setup-env.sh" "$a"
  else run_one "$a" setup_one "$a"; fi
done

echo; echo "== 요약"
printf '  %-22s %-16s %s\n' 영역 결과 "소요(초)"
for i in "${!NAMES[@]}"; do printf '  %-22s %-16s %s\n' "${NAMES[$i]}" "${STATUS[$i]}" "${SECS[$i]}"; done
if [ $FAILS = 0 ]; then echo "prepare-areas: 전부 성공 (${#NAMES[@]}개). 다음: bash scripts/doctor.sh"; exit 0; fi
echo "prepare-areas: 성공하지 못한 것 ${FAILS}개 (위 표). 실패한 영역의 로그를 보고 고친 뒤 다시 실행한다(멱등)"; exit 1
