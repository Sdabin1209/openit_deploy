#!/usr/bin/env bash
# 합격 시나리오(docs/E2E.md)를 사람 손 없이 순서대로 실행한다.
#  - 임시 레지스트리·프로젝트(deploy-e2e-*)를 만들고 끝나면 지운다. 컨테이너의 호스트 포트는 Docker가 배정한 것을 읽는다(레지스트리만 빈 포트를 고른다).
#  - 영역 사이 호출은 실제 서비스의 HTTP다(D49). 단계 상태: REAL / TEST-SUB(시험 대역으로 대신함) / BLOCKED(지금 구현으로는 이어지지 않음).
#  - 합격: 하나라도 FAIL이면 종료 코드 1. BLOCKED는 실패가 아니지만 요약에 그대로 보인다.
#  - E2E_GPU=1 이면 단계 3을 gpu-dev의 model-lab 파이프라인으로 돌리는 경로(scripts/e2e_gpu.sh)를 쓴다. 기본은 끔.
#  - --fast: 단계 1~8과 단계 9 앞부분(compose 기동 검사)까지만. 스케줄러, 백업·복구, 코드 축 롤백은 생략한다. 개발 중 빠른 확인용이며 **전체 합격이 아니다**.
#    옵션 없이 돌리는 전체 모드가 인도 전 필수다. 종료 코드는 돌린 검사 기준이다.
# 시작 전에 scripts/check-all.sh(정적 점검)를 돌리고 FAIL 이면 멈춘다.
# 끝에서 scripts/record-e2e.sh 가 결과 한 줄을 docs/E2E_RESULTS.md(E2E 통과 수의 정본)에 더한다(DEPLOY_NO_RECORD=1 이면 안 더함. 못 더하면 종료 코드 1).
#  - --only <단계,...>: 단계 일부만(예: --only 5p, PostgreSQL 컨테이너 재시작 시험). --fast 처럼 9단계 뒷구간을 생략하고 정본에 기록하지 않는다. 전체 합격이 아니다.
#  - 선행 항목이 FAIL 이면 그에 의존하는 항목은 FAIL 이 아니라 SKIP(선행 실패: 항목명)으로 센다(연쇄 잡음 제거, docs/adr/0030). 종료 코드는 FAIL 만 본다. SKIP 개수는 요약의 'SKIP n' 줄과 E2E_RESULTS.md 출처 칸에 나온다.
#  - --fail-fast: 첫 FAIL 에서 요약을 내고 중단한다(정본에 기록하지 않는다). --changed-only: 입력 해시가 마지막 PASS 와 달라진 단계(scripts/e2e_plan.py)와 그에 의존하는 단계만 e2e_steps.py 에서 돌린다
#    (준비·단계 9 구간은 항상 돈다. 정본에 기록하지 않는다. 전체 합격이 아니며 최종 관문은 옵션 없는 전체 1회다).
# 사용: scripts/e2e.sh [--fast] [--only <단계,...>] [--fail-fast] [--changed-only] [--keep] [--keep-images] [--reuse-build] [--sections jobs,backup,rollback]
#  --sections: 단계 1~8 을 모두 돌린 뒤 단계 9 뒷구간 일부만. 뒷구간이 단계 1~8 의 상태를 전제하므로 --only 와 함께 쓰면 사용 오류(종료 2, 맨 앞에서 거부한다). -h/--help 는 사용법만 내고 0.
#  --reuse-build: 이미지가 있고 소스 커밋·의존 태그가 라벨과 같으면 다시 빌드하지 않는다(낡은 것만 빌드). 끝나도 이미지를 지우지 않는다.
set -o pipefail
# 옵션 검사(아무것도 실행하기 전에): --help/-h 는 사용법만 내고 0, 모르는 옵션·값 없는 옵션·잘못된 값·못 쓰는 조합은 사용법을 표준 오류로 내고 2.
# 왜 맨 앞인가: 예전에는 모르는 옵션(--help 포함)이 무시되어 전체 E2E 가 시작됐다. 정적 점검·doctor·빌드는 분 단위라 사용 오류를 그 뒤에 알리면 안 된다.
e2e_usage() { cat <<'USAGE'
사용: scripts/e2e.sh [--fast] [--only <단계,...>] [--sections <jobs,backup,rollback>] [--fail-fast] [--changed-only] [--up-only] [--keep] [--keep-images] [--reuse-build] [-h|--help]
  (옵션 없음)   전체 합격 시나리오(인도 전 필수). 정본 docs/E2E_RESULTS.md 에 결과를 더한다.
  --fast        단계 1~8 과 단계 9 앞부분만(스케줄러·백업·롤백 생략). 전체 합격 아님.
  --only 단계   e2e_steps.py 의 단계 일부만(예: 5o 또는 1,2,3,4,5o). 단계 9 뒷구간은 생략. 전체 합격 아님.
  --sections 구간  단계 1~8 을 모두 돌린 뒤 단계 9 뒷구간 중 지정한 것만(jobs, backup, rollback 를 쉼표로). 뒷구간은 단계 1~8 이 만든 상태(수집기 실행, 문항 버전, 활성 릴리스)를 전제하므로 --only 와 함께 쓸 수 없다.
  --up-only     사전 점검과 제품·추론 서버 기동, 도달·격리 점검까지만 하고 단계(e2e_steps.py)는 돌리지 않는다. 전체 합격 아님(기록 안 함).
  --fail-fast / --changed-only / --keep / --keep-images / --reuse-build   docs/E2E.md 참고.
  -h, --help    이 사용법만 낸다(아무것도 실행하지 않는다).
USAGE
}
e2e_bad() { echo "오류: $*" >&2; e2e_usage >&2; exit 2; }
_only=0; _sec=0; _args=("$@"); _i=0
while [ $_i -lt ${#_args[@]} ]; do a_=${_args[$_i]}; case "$a_" in
  -h|--help) e2e_usage; exit 0;;
  --fast|--fail-fast|--changed-only|--up-only|--keep|--keep-images|--reuse-build) ;;
  --only) _i=$((_i+1)); [ $_i -lt ${#_args[@]} ] && [ -n "${_args[$_i]}" ] && [[ "${_args[$_i]}" != -* ]] || e2e_bad "--only 에는 단계 목록이 필요하다 (예: --only 5o)"; _only=1;;
  --only=*) [ -n "${a_#*=}" ] || e2e_bad "--only 에는 단계 목록이 필요하다"; _only=1;;
  --sections) _i=$((_i+1)); [ $_i -lt ${#_args[@]} ] && [[ "${_args[$_i]}" != -* ]] || e2e_bad "--sections 에는 jobs,backup,rollback 중 일부가 필요하다"; _v=${_args[$_i]}; _sec=1
    for _x in ${_v//,/ }; do case "$_x" in jobs|backup|rollback) ;; *) e2e_bad "알 수 없는 구간: $_x (가능: jobs, backup, rollback)";; esac; done; [ -n "${_v//,/}" ] || e2e_bad "--sections 가 비었다";;
  --sections=*) _sec=1; _v=${a_#*=}; [ -n "${_v//,/}" ] || e2e_bad "--sections 가 비었다"; for _x in ${_v//,/ }; do case "$_x" in jobs|backup|rollback) ;; *) e2e_bad "알 수 없는 구간: $_x (가능: jobs, backup, rollback)";; esac; done;;
  *) e2e_bad "알 수 없는 옵션: $a_";;
esac; _i=$((_i+1)); done
[ $_only = 0 ] || [ $_sec = 0 ] || e2e_bad "--only 와 --sections 는 함께 쓸 수 없다: 단계 9 뒷구간은 단계 1~8 이 만든 상태를 전제한다(--only 로 일부 단계만 돌리면 그 상태가 없어 뒷구간이 실패한다). 뒷구간만 보려면 --sections 만 준다(단계 1~8 을 모두 돌린다)"
unset _only _sec _args _i a_ _v _x
# 정적 일관성 점검(수 초): 영역 사이 어긋남을 6분짜리 E2E 앞에서 잡는다. FAIL 이면 E2E를 시작하지 않는다(건너뛰기 DEPLOY_SKIP_CHECK_ALL=1, 개발 중에만)
CA_TXT=""
if [ "${DEPLOY_SKIP_CHECK_ALL:-0}" != 1 ]; then
  bash -n "$0" || { echo "e2e.sh 문법 오류: E2E를 시작하지 않는다"; exit 1; }   # 긴 셸은 줄 휴리스틱이 아니라 문법 검사와 준비 단계의 실제 실행에 맡긴다(ADR 0033)
  CA_RC=0; CA_TXT=$(CHECK_ALL_IMAGES=defer bash "$(dirname "$0")/check-all.sh" --strict 2>&1) || CA_RC=$?; printf '%s\n' "$CA_TXT"
  [ $CA_RC = 0 ] || { echo "check-all.sh --strict 가 FAIL 또는 SKIP 이라 E2E를 시작하지 않는다 (위 FAIL 의 영역/파일:줄을 먼저 고친다)"; exit 1; }
  export E2E_PRECHECK_DONE=1   # 자체 점검 묶음(self-checks.list)의 check-all 항목이 같은 점검을 두 번 돌지 않게 한다
fi
# 사전 점검: 실패하면 바로 멈춘다(건너뛰기 DEPLOY_SKIP_DOCTOR=1). 하위 up.sh 가 다시 점검하지 않게 export 한다
[ "${DEPLOY_SKIP_DOCTOR:-0}" = 1 ] || bash "$(dirname "$0")/doctor.sh" || exit 1
export DEPLOY_SKIP_DOCTOR=1
source "$(dirname "$0")/lib.sh"
# link 핀 대조(U59, ADR 0046): 영역 main 잠금 파일의 openit-link 태그가 lib.sh 의 DEPLOY_LINK_TAG 와 같아야 한다. 기본 켜짐(영역이 모두 기준 태그로 올랐다). DEPLOY_CHECK_LINK_PINS=0 으로 끈다.
# 왜 lib.sh 를 source 한 뒤인가: 이전에는 VENV 가 정해지기 전에 불러 "/bin/python: No such file" 로 멈췄다(켜지 않은 선택 단계가 한 번도 안 돌아 깨진 줄 몰랐다). 단계 자체는 scripts/check-link-pins.sh 로 빼 단독으로 시험한다(scripts/test-link-pins-step.sh).
if [ "${DEPLOY_CHECK_LINK_PINS:-1}" = 1 ]; then
  bash "$DEPLOY_ROOT/scripts/check-link-pins.sh" || { echo "link 핀 대조가 실패해 E2E를 시작하지 않는다 (위 영역/파일의 태그를 표와 맞춘다)"; exit 1; }
fi
KEEP=0; REUSE=0; KEEPIMG=0; FAST=0; FAILFAST=0; CHANGED=0; UPONLY=0
ONLY=""; SECTIONS="jobs,backup,rollback"; SECTIONS_SET=0
while [ $# -gt 0 ]; do case "$1" in
  --fast) FAST=1;; --fail-fast) FAILFAST=1;; --changed-only) CHANGED=1;; --up-only) UPONLY=1; FAST=1; export DEPLOY_NO_RECORD=1;; --keep) KEEP=1;; --reuse-build) REUSE=1; KEEPIMG=1;; --keep-images) KEEPIMG=1;;
  --only) [ $# -ge 2 ] || { echo "--only 에는 단계 목록이 필요하다 (예: --only 5p)" >&2; exit 2; }; ONLY=$2; shift;;
  --only=*) ONLY=${1#*=};;
  --sections=*) SECTIONS=${1#*=}; SECTIONS_SET=1; export DEPLOY_NO_RECORD=1;;
  --sections) [ $# -ge 2 ] || { echo "--sections 에는 jobs,backup,rollback 중 일부가 필요하다" >&2; exit 2; }; SECTIONS=$2; SECTIONS_SET=1; export DEPLOY_NO_RECORD=1; shift;;   # 단계 9 뒷구간 중 일부만(단계 1~8 은 모두 돈다). 정본에 기록하지 않는다. 전체 합격이 아니다
esac; shift; done
# --only: e2e_steps.py 의 단계 일부만 돌린다(개발 중 한 단계 확인용). 스택 기동과 준비는 같이 하고, 스케줄러·백업·롤백 구간은 생략하며 결과를 정본에 기록하지 않는다. 전체 합격이 아니다
if [ -n "$ONLY" ]; then export DEPLOY_NO_RECORD=1; [ "$SECTIONS_SET" = 1 ] || FAST=1; fi   # --only 와 --sections 를 같이 주면 지정한 단계만 돌린 뒤 지정한 단계 9 뒷구간을 돈다(예: --only 1,2,3,4,6 --sections backup)
[ "$FAILFAST$CHANGED" = 00 ] || export DEPLOY_NO_RECORD=1   # 일부만 돌린 결과는 정본에 쓰지 않는다
ID=$$; PROJECT=deploy-e2e-$ID; RPROJ=deploy-e2e-reg-$ID; INF=$PROJECT-inf   # INF: 다른 호스트 역할인 추론 서버의 별도 프로젝트(샌드박스 접근 (c). e2e_sandbox.py 도 같은 이름 규칙 <P>-inf 를 쓴다)
W="$DEPLOY_ROOT/state/e2e-$ID"; mkdir -p "$W"
export DEPLOY_LOCK="$W/images.lock" DEPLOY_REGISTRY_ENV="$W/registry.env" DEPLOY_PROJECT=$PROJECT
export REGISTRY_PROJECT=$RPROJ REGISTRY_HOST_BIND=0.0.0.0 REGISTRY_HOST_PORT=
UTIL_REF=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
mkdir -p "$W/backup-tls"; gateway_test_pki "$W/backup-tls" backup-target || { echo "시험 PKI 실패"; exit 1; }   # 백업 저장소 서버는 TLS 만(ADR 0060)
export SECRETS_DIR="$W/secrets" DEVICE_ALLOWLIST_DIR="$W/device-allowlist" COMPOSE_EXTRA="$DEPLOY_ROOT/test/compose.sandbox.yaml $DEPLOY_ROOT/test/compose.risk-rules.yaml $DEPLOY_ROOT/compose.backup-target.yaml" BACKUP_TARGET_TLS_DIR="$W/backup-tls" BACKUP_TARGET_HTPASSWD="$W/backup-target.htpasswd" GATEWAY_PORT= GATEWAY_TLS_PORT=
export OPS_JOB_CONFIG="$DEPLOY_ROOT/test/ops-job/test-ops-job.yaml"
RESULT=(); FAILS=0
# 구간별 소요 시간: sect "제목" 이 이전 구간을 닫고(소요 시간 출력) 새 구간 제목을 낸다. 끝의 요약에 표로 모은다
SEC_NAMES=(); SEC_SECS=(); SEC_CUR=""; SEC_T0=$SECONDS
sect() { local now=$SECONDS; if [ -n "$SEC_CUR" ]; then SEC_NAMES+=("$SEC_CUR"); SEC_SECS+=($((now-SEC_T0))); printf '  (소요 %ds)\n' $((now-SEC_T0)); fi; SEC_CUR="$1"; SEC_T0=$now; if [ -n "$1" ]; then echo; echo "== $1"; fi; }
declare -A STAT ROOTF   # 항목명 -> PASS|FAIL|SKIP, SKIP 의 뿌리 항목명
SKIPS=0; STEP_SKIPS=0; NEED=()
res() { local n=$1 st=$2; STAT["$n"]=$st; RESULT+=("$n|$st|$3"); [ "$st" = FAIL ] && FAILS=$((FAILS+1)); [ "$st" = SKIP ] && SKIPS=$((SKIPS+1)); printf '  [%s] %s: %s\n' "$st" "$n" "$3"
  if [ "$st" = FAIL ] && [ "$FAILFAST" = 1 ]; then echo "--fail-fast: 첫 FAIL 에서 중단한다 (이후 항목은 돌리지 않았다)"; sect ""; finish; exit 1; fi; }
# 선행 항목(NEED 배열 + 인자 하나)이 FAIL/SKIP 이면 이 항목은 돌리지 않고 SKIP 으로 센다. 뿌리 항목명을 남긴다
blocked_by() { local d; for d in "${NEED[@]}" "$@"; do [ -n "$d" ] || continue; case "${STAT[$d]:-}" in FAIL) echo "$d"; return 0;; SKIP) echo "${ROOTF[$d]:-$d}"; return 0;; esac; done; return 1; }
chk_dep() { local dep=$1; shift; local root; if root=$(blocked_by "$dep"); then ROOTF["$1"]=$root; res "$1" SKIP "SKIP(선행 실패: $root)"; else chk "$@"; fi; }
chk() { local name=$1; local root; if root=$(blocked_by); then ROOTF["$name"]=$root; res "$name" SKIP "SKIP(선행 실패: $root)"; return 0; fi; shift; local out; if out=$("$@" 2>&1); then res "$name" PASS "$(echo "$out" | tail -1 | cut -c1-150)"; else mkdir -p "$W/diag"; { printf '## %s\n## 명령: %s\n' "$name" "$*"; printf '%s\n' "$out"; } > "$W/diag/chk-$(printf '%s' "$name" | tr -c 'A-Za-z0-9가-힣' '_' | cut -c1-80)-$RANDOM.txt" 2>/dev/null; res "$name" FAIL "$(echo "$out" | tail -3 | tr '\n' ' ' | cut -c1-300)"; fi; }   # 실패한 점검의 출력 전체를 진단 폴더(collect_diag 가 $W/diag 를 복사한다)에 남긴다: 한 줄 요약만으로는 원인을 못 찾는다(4차 E2E 분리 배치 플레이북)
# 준비 단계(chk 로 세지 않는 명령)의 실패는 조용히 지나가지 않고 그 자리에서 멈춘다: 예전에는 venv·wheel·비밀 생성·지문 생성의 실패가 버려져 복구 검증이 헛통과할 수 있었다(정적 점검 A8, 2026-11-05)
must() { "$@" || { echo "준비 단계 실패(종료 코드 $?): $*" >&2; exit 1; }; }
# 대기 상한(초). 아래 값은 모두 측정하지 않은 시작값이다(D125: 측정 최악 + 여유가 되려면 이 호스트에서 재야 한다. 값을 지어내지 않고 측정 안 함으로 적는다). 한 곳에서만 바꾼다.
E2E_UP_WAIT_S=340        # compose up --wait 한 번의 상한. 로그 기준(D125): 이전 E2E 진단 116건에서 시작부터 healthy 까지 최악 170초(state/e2e-diag-20261104-142243, ops-feedback-db; Health.Log 는 최근 5건만 남아 위쪽 추정이다) x 2 = 340 > 이전 120. 다른 상한은 로그에 측정 자료가 없어 지금 값을 둔다
export UP_WAIT_TIMEOUT=$E2E_UP_WAIT_S   # up.sh 가 같은 상한을 쓴다(한 값, 한 곳)
E2E_MON_POLL_S=120       # 감시 스택이 탐침 결과를 낼 때까지(60회 x 2초). 측정 안 함
E2E_ROLLBACK_READY_S=80  # 롤백 뒤 survey-service /readyz(40회 x 2초). 측정 안 함
REACH_T=10               # 서비스 사이 도달 확인 한 번의 상한. reachu 가 10초로 늘린 관찰(4차 실행: 호스트 경유는 3초 초과)을 따른다. 측정 안 함
TCP_T=3                  # 같은 호스트 내부 망의 TCP 연결(핸드셰이크 없음) 한 번의 상한. 측정 안 함
finish() {
{
echo; echo "============================ 요약 ============================"
if [ -f "$W/steps.log" ]; then sed -n '/== 요약 (단계 1~8)/,$p' "$W/steps.log"; fi
[ "$FAST" = 1 ] && echo "-- FAST 모드: 생략한 구간 = 단계 9 스케줄러(D39), 백업·복구, digest 잠금 코드 축 롤백. 전체 합격 아님"
echo "-- 9단계 및 준비 검사"
printf '   PASS %s / FAIL %s\n' "$(printf '%s\n' "${RESULT[@]}" | grep -c '|PASS|')" "$FAILS"
printf '   SKIP %s (선행 항목 실패로 돌리지 않은 것. FAIL 이 아니다)\n' "$((SKIPS+STEP_SKIPS))"
for r in "${RESULT[@]}"; do case "$r" in *"|SKIP|"*) echo "   SKIP: ${r%%|*} -> ${r##*|}";; esac; done
[ "$FAILFAST" = 1 ] && echo "-- FAIL-FAST 모드: 첫 FAIL 에서 중단했을 수 있다. 전체 합격 아님"
[ "$CHANGED" = 1 ] && echo "-- CHANGED-ONLY 모드: e2e_steps.py 는 입력이 바뀐 단계와 그 하위만 돌렸다. 전체 합격 아님"
for r in "${RESULT[@]}"; do case "$r" in *"|FAIL|"*) echo "   FAIL: ${r%%|*}";; esac; done
echo "-- 구간별 소요 시간"
TOTAL=0; for i in "${!SEC_NAMES[@]}"; do printf '   %5ds  %s\n' "${SEC_SECS[$i]}" "${SEC_NAMES[$i]}"; TOTAL=$((TOTAL+SEC_SECS[$i])); done
printf '   %5ds  합계 (정리 제외)\n' "$TOTAL"
echo "대신한 것(TEST-SUB): 단계 3 모델과 EvaluationReport(시험용), 단계 4 승인자(스크립트가 시험용 토큰으로 결정), 단계 5 가짜 백엔드, 단계 6 봉투, 단계 7 reviewed_input"
echo "막힌 것(BLOCKED): 위 요약의 BLOCKED 행. docs/change-requests/ 참고"
if [ "$FAILS" != 0 ]; then echo "E2E 결과: 실패 있음"
elif [ "$FAST" = 1 ]; then echo "E2E 결과(--fast): 실행한 검사 전부 통과. 생략한 구간이 있어 전체 합격이 아니다 -- 인도 전에는 옵션 없는 전체 모드를 돌릴 것"
else echo "E2E 결과: 실행한 검사 전부 통과 (BLOCKED/TEST-SUB 단계가 있어 시나리오 전체 합격은 아니다)"; fi
} | tee "$W/summary.txt"
# 결과 한 줄을 정본(docs/E2E_RESULTS.md)에 기록: 로그에서 숫자를 파싱하고, 못 하면 실패한다
REC_RC=0
if [ "${DEPLOY_NO_RECORD:-0}" = 1 ]; then echo "(DEPLOY_NO_RECORD=1: docs/E2E_RESULTS.md 에 기록하지 않음)"
elif [ -z "$CA_TXT" ]; then echo "(check-all 을 건너뛰어 docs/E2E_RESULTS.md 에 기록하지 않음)"
else
  printf '%s\n' "$CA_TXT" > "$W/check-all.out"
  bash "$DEPLOY_ROOT/scripts/record-e2e.sh" "$W/check-all.out" "$W/summary.txt" || { echo "record-e2e.sh 실패: 결과를 docs/E2E_RESULTS.md 에 적지 못했다"; REC_RC=1; }
fi
}
# 실패 진단 수집(사용자 지시: 검사가 실패하면 이유를 산출하고 이미지를 지운다): 정리 전에 서비스 컨테이너 로그 끝 300줄, 컨테이너 목록(docker ps -a, compose ps -a 와 같은 정보), 컨테이너 State, 단계의 진단 파일($W/diag)을
# state/e2e-diag-<날짜시각>/ 로 복사한다(작업 폴더가 지워져도 남는다). 비밀 금지: 환경 변수 목록(env, printenv, Config.Env)과 inspect 전체·compose config 는 쓰지 않는다
# (State 만 읽는다). 수집이 실패해도 정리를 막지 않는다.
DIAG_DIR=""
collect_diag() {
  DIAG_DIR="$DEPLOY_ROOT/state/e2e-diag-$(date +%Y%m%d-%H%M%S)"
  ( set +e
    mkdir -p "$DIAG_DIR/logs" "$DIAG_DIR/state" || exit 0
    # compose ps -a 와 같은 정보(이름·상태·이미지)를 docker ps 로 읽는다: compose 는 필수 변수(digest)를 해석해야 하는데 정리 중에는 그 환경이 없을 수 있다
    timeout 30 "$DOCKER" ps -a --filter "label=com.docker.compose.project=$PROJECT" --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}' > "$DIAG_DIR/compose-ps.txt" 2>&1
    for c in $(timeout 30 "$DOCKER" ps -a --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Names}}' 2>/dev/null | tr -d '\r'; timeout 30 "$DOCKER" ps -a --filter "label=com.docker.compose.project=$INF" --format '{{.Names}}' 2>/dev/null | tr -d '\r'); do
      timeout 60 "$DOCKER" logs --tail 300 "$c" > "$DIAG_DIR/logs/$c.log" 2>&1
      timeout 30 "$DOCKER" inspect --format '{{json .State}}' "$c" > "$DIAG_DIR/state/$c.json" 2>&1
    done
    [ -d "$W/diag" ] && cp -r "$W/diag/." "$DIAG_DIR/" 2>/dev/null
    for f in steps.log summary.txt check-all.out; do [ -f "$W/$f" ] && cp "$W/$f" "$DIAG_DIR/" 2>/dev/null; done
    exit 0 ) || true
  [ -d "$DIAG_DIR" ] || DIAG_DIR=""
}
cleanup() {
  local rc=$?
  if [ "${FAILS:-0}" != 0 ] || [ $rc != 0 ]; then collect_diag; fi
  [ $KEEP = 1 ] && { [ -z "$DIAG_DIR" ] || echo "진단 폴더: ${DIAG_DIR#$DEPLOY_ROOT/}"; echo "--keep: 프로젝트 $PROJECT, 레지스트리 $RPROJ, 작업 폴더 $W 를 남겼다"; return; }
  echo; echo "== 정리"
  # 감시 스택(compose.monitoring.yaml)의 서비스·네트워크(${PROJECT}_monitoring)는 그 파일을 읽어야 내려간다: 파일 없이 내리면 고아 컨테이너만 지워지고 네트워크가 남아 Docker 주소 풀을 쓴다
  COMPOSE_EXTRA="$COMPOSE_EXTRA $DEPLOY_ROOT/compose.monitoring.yaml" dc "$PROJECT" --profile jobs down -v --remove-orphans >/dev/null 2>&1
  # 추론 서버 프로젝트(<P>-inf): 필수 변수 없이도 지워지게 compose 파일이 아니라 프로젝트 라벨로 찾는다
  for c in $("$DOCKER" ps -aq --filter "label=com.docker.compose.project=$INF" 2>/dev/null | tr -d '\r'); do "$DOCKER" rm -f -v "$c" >/dev/null 2>&1; done
  for n in $("$DOCKER" network ls -q --filter "label=com.docker.compose.project=$INF" 2>/dev/null | tr -d '\r'); do "$DOCKER" network rm "$n" >/dev/null 2>&1; done
  for v in $("$DOCKER" volume ls -q --filter "label=com.docker.compose.project=$INF" 2>/dev/null | tr -d '\r'); do "$DOCKER" volume rm "$v" >/dev/null 2>&1; done
  bash "$DEPLOY_ROOT/scripts/registry.sh" down -v >/dev/null 2>&1
  # 이 실행의 레지스트리 주소(registry.env 의 DEPLOY_REGISTRY)로 태그된 이미지만 지운다. 왜: 모든 127.0.0.1:*/openit/* 를 지우면 같은 데몬에서 도는 다른 E2E·데모의 이미지가 사라진다(2026-11-02 최종 E2E 단계 7 'No such image')
  _reg=$(sed -n 's/^DEPLOY_REGISTRY=//p' "$W/registry.env" 2>/dev/null | tr -d '\r')
  [ -n "$_reg" ] && for img in $("$DOCKER" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | tr -d '\r' | grep -F "$_reg/openit/"); do "$DOCKER" rmi -f "$img" >/dev/null 2>&1; done
  if [ $KEEPIMG = 0 ]; then for img in $("$DOCKER" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | tr -d '\r' | grep -E '^deploy-build/' | grep -v '^deploy-build/model-serving-gpu:'); do "$DOCKER" rmi -f "$img" >/dev/null 2>&1; done; fi   # 사용자가 따로 빌드한 13GB GPU 이미지(데모용)는 지우지 않는다
  rm -rf "$W" 2>/dev/null || "$DOCKER" run --rm -v "$DEPLOY_ROOT/state:/s" "$UTIL_REF" rm -rf "/s/e2e-$ID"
  echo "정리 완료 (프로젝트 $PROJECT, 레지스트리 $RPROJ, 이미지, 임시 폴더)"
  [ -z "$DIAG_DIR" ] || echo "진단 폴더: ${DIAG_DIR#$DEPLOY_ROOT/} (컨테이너 로그 끝 300줄, compose ps, 컨테이너 State, 잡 stderr, 단계 traceback; 환경 변수는 담지 않는다)"
  return $rc
}
trap cleanup EXIT

[ -n "$ONLY" ] && echo "!!! --only $ONLY: 일부 단계만 돈다. 전체 합격이 아니다(기록 안 함) !!!"
[ "$FAST" = 1 ] && [ -z "$ONLY" ] && echo "!!! --fast 모드: 스케줄러, 백업·복구, 코드 축 롤백 구간을 생략한다. 전체 합격이 아니다(인도 전에는 옵션 없는 전체 모드 필수) !!!"
cat <<BANNER
=============================================================================
 E2E 합격 시나리오 실행 (프로젝트 $PROJECT)   경계 계약 $DEPLOY_BC_TAG (출고는 사람 승인, D53)
 !! 시험 대역 사용 표시 !!
   - 승인자: 사람 대신 이 스크립트가 시험용 승인자 토큰(release-approver)으로 POST /v1/approvals 를 호출한다. 시험용 정책·실행기는 없다(게이트에서 삭제됨)
   - 단계 3 모델: GPU 없이 시험용 어댑터(test/fixtures/e2e-test-adapter)와 시험용 EvaluationReport(고정 지표, 실제 평가 아님)를 model-registry에 HTTP로 게시한다(E2E_GPU=1이면 gpu-dev 경로, 기본 끔)
   - 단계 5 모델: 다른 호스트 역할의 추론 서버(compose.inference.yaml 을 별도 프로젝트 <P>-inf 로 띄운 컨테이너, CPU)의 가짜 백엔드. A 출력은 입력 문항 기준으로 유효한 ActionExtraction(NEXT, 다음 문항; 흐름 파일에 칸 정의가 있는 문항은 발화에서 첫 칸의 ANSWERED 값과 건너뛰기 적용, 단계 5g), B 출력은 문장 "(가짜 응답)"이다(표준 서버 + MODEL_RUNTIME_FAKE_FLOW_FILE=test/fake-model/question_flow.json, model-runtime ${DEPLOY_MR_TAG}). 시험용 번들의 serving_config는 서버 /v1/info 기대값으로 만든다(TEST-SUB)
   - 직원 콘솔 접근: OIDC 로그인(Keycloak, 시험 사용자는 idp-test-users.sh 가 만든다). 실제 브라우저·STT·웹 푸시 수신은 E2E에서 볼 수 없다(BLOCKED, VAPID 키 없이 SSE만)
   - 단계 6 TraceEnvelope와 단계 7 reviewed_input·검토 확인은 이 스크립트가 만든 시험 자료/행위다
   - 샌드박스(docs/adr/0050): 제품은 compose.yaml(+ 운영 overlay)이고 시험용 문이 없다. 드라이버는 호스트에서 게이트웨이(HTTPS)·compose exec/run/logs·추론 서버로만 들어간다
   - 시험 자료는 운영 설정(compose.yaml, config/)에 들어가지 않는다
=============================================================================
BANNER

sect "준비: 이미지 빌드, 임시 레지스트리, digest 잠금"
must bash "$DEPLOY_ROOT/scripts/prepare-host.sh" venv
have_images() { [ -f "$DEPLOY_ROOT/build/images.env" ] && [ "$(grep -vc '^model-serving-gpu ' "$DEPLOY_ROOT/build/images.env")" -ge 8 ] && while read -r n img _; do [ "$n" = model-serving-gpu ] && continue; "$DOCKER" image inspect "$img" >/dev/null 2>&1 || return 1; done < "$DEPLOY_ROOT/build/images.env"; }
if [ $REUSE = 1 ] && have_images; then
  # 재사용은 소스(커밋)와 의존 태그가 이미지 라벨과 같을 때만이다. 다른 이미지만 다시 빌드한다(판정 코드: verify_area.py stale_images). 판정이 안 되면 전부 다시 빌드한다
  if STALE=$("$VENV/bin/python" "$DEPLOY_ROOT/scripts/verify_area.py" --stale-images 2>/dev/null); then
    echo "  재사용: 낡은 이미지 = ${STALE:-없음}"
    [ -z "$STALE" ] || chk "빌드: 낡은 이미지만 ($STALE)" bash "$DEPLOY_ROOT/scripts/build-images.sh" $STALE
  else chk "빌드: 다섯 서비스 이미지 (낡은 이미지 판정 실패, 전부)" bash "$DEPLOY_ROOT/scripts/build-images.sh"; fi
else chk "빌드: 다섯 서비스 이미지 (현재 HEAD)" bash "$DEPLOY_ROOT/scripts/build-images.sh"; fi
# 호스트 wheel(계약·문진 스키마)을 이 실행 안에서 만든다: 도구 이미지 빌드와 prepare-host.sh wheels 가 쓴다. --reuse-build 로 이미지 빌드를 건너뛰어도 이전 실행이 남긴 폴더에 기대지 않는다
must bash "$DEPLOY_ROOT/scripts/build-hostwheels.sh" >/dev/null
# 시험 드라이버의 클라이언트 이미지(deploy 도구 이미지): 영역 컨테이너 안이 아니라 같은 망의 이 컨테이너에서 게이트웨이 HTTPS 로 부른다(e2e_sandbox.exec_py)
chk "빌드: deploy 도구 이미지(link $DEPLOY_LINK_TAG, 계약 $DEPLOY_BC_TAG)" bash -c "bash $DEPLOY_ROOT/scripts/build-tool-image.sh > $W/tool-image.txt"
DEPLOY_TOOL_IMAGE=$(tail -1 "$W/tool-image.txt" 2>/dev/null); export DEPLOY_TOOL_IMAGE
abort_if_failed() { [ "$FAILS" = 0 ] || { echo "준비 단계가 실패해 중단한다"; exit 1; }; }
abort_if_failed
must bash "$DEPLOY_ROOT/scripts/prepare-host.sh" wheels
grep -E '^[A-Z0-9_]+_IMAGE=' "$DEPLOY_ROOT/locks/images.lock" > "$DEPLOY_LOCK"   # 잠금의 외부 이미지 줄 전부(목록을 손으로 적으면 새 이미지가 빠진다: D9c KEYCLOAK, 4차 STEP_CA)
# 서버 밖 append-only 백업 저장소를 흉내 내는 컨테이너(compose.backup-target.yaml)의 인증 파일: 서버 자격(백업이 쓰는 것)을 만든다. 시험 폴더 안, 시험이 끝나면 지워진다
BKPW="e2e-backup-target-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"
BKHASH=$(printf '%s\n%s\n' "$BKPW" "$BKPW" | "$DOCKER" run --rm -i "$(sed -n 's/^GATEWAY_IMAGE=//p' "$DEPLOY_LOCK")" caddy hash-password) || { echo "백업 대상 저장소의 비밀번호 해시를 만들지 못했다" >&2; exit 1; }
BKHASH=$(printf '%s' "$BKHASH" | tail -1 | tr -d '\r\n'); case "$BKHASH" in '$2'*) ;; *) echo "백업 대상 저장소의 비밀번호 해시가 bcrypt 형식이 아니다" >&2; exit 1;; esac
printf 'srv:%s\n' "$BKHASH" > "$W/backup-target.htpasswd"; unset BKHASH; chmod 644 "$W/backup-target.htpasswd"
( umask 077; printf 'RESTIC_REST_USERNAME=srv\nRESTIC_REST_PASSWORD=%s\n' "$BKPW" > "$W/backup-target.cred" ); unset BKPW
chk "레지스트리 기동(빈 포트 선택)" bash "$DEPLOY_ROOT/scripts/registry.sh" up
chk "publish: push + digest 잠금" bash "$DEPLOY_ROOT/scripts/publish-images.sh"
chk "compose가 digest로만 이미지를 참조" bash "$DEPLOY_ROOT/scripts/check-compose.sh"
chk "버전 표 드리프트 없음 (check-versions: 빌드된 이미지 라벨 == lib.sh 표; 검증하지 못하면(종료 3) 실패)" bash "$DEPLOY_ROOT/scripts/check-versions.sh"
# (삭제) 게이트웨이 노출 대조(check-exposure: Caddyfile 대 영역 Exposure)는 두지 않는다: 공개 입구 경로 표는 platform public-ingress 이미지가 같은 Exposure 선언에서 만든다(S9). 대조할 deploy 쪽 손으로 쓴 경로가 없다.
# 자체 점검 묶음: scripts/self-checks.list 가 정본이다(scripts/run-self-checks.sh 도 같은 목록을 돈다).
export DEPLOY_ROOT VENV
# DOCKER_CONFIG 등은 deploy 전용 Docker 설정이다: lib.sh 를 source 하지 않는 시험(python 시험 등)도 사용자 ~/.docker 가 아니라 이 설정으로 docker 를 부르게 넘긴다.
# 왜 깨끗한 환경: 단독 시험은 E2E 가 내보낸 값(DEPLOY_LOCK 임시 잠금, SECRETS_DIR, COMPOSE_EXTRA, STEP_CA_PORT …)이 없는 상태를 전제로 자기 입력을 스스로 정한다. 새어 들어가면 단독으로는 통과하는 시험이 E2E 안에서만 실패했다(분리 배치 플레이북, DEPLOY_LOCK). 필요한 것만 이름으로 넘긴다.
_keep=(DEPLOY_TOOL_IMAGE PATH HOME LANG LC_ALL TMPDIR USER DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DEPLOY_DOCKER_CONFIG DEPLOY_DOCKER_CONFIG_SET GIT_CONFIG_COUNT GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM DEPLOY_ROOT VENV E2E_PRECHECK_DONE DEPLOY_SKIP_DOCTOR)
for _k in $(compgen -v | grep -E '^GIT_CONFIG_(KEY|VALUE)_[0-9]+$'); do _keep+=("$_k"); done
_cleanenv=(); for _k in "${_keep[@]}"; do [ -n "${!_k+x}" ] && _cleanenv+=("$_k=${!_k}"); done
while IFS=$'\t' read -r _d _c; do chk "$_d" env -i "${_cleanenv[@]}" bash -c "$_c"; done < <(bash "$DEPLOY_ROOT/scripts/run-self-checks.sh" --print)
abort_if_failed
source "$DEPLOY_LOCK"; source "$DEPLOY_REGISTRY_ENV"   # export 하지 않는다(compose 변수 우선순위)
must bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --test-fixtures "$SECRETS_DIR" >/dev/null

# ---- 샌드박스 기동(docs/adr/0050, 순서 고정). 제품은 compose.yaml 그대로이고 시험용 문이 없다. 추론 서버는 제품 밖(다른 호스트 역할)이다.
#  순서와 이유는 아래 "새 순서" 주석(U99, ADR 0060)이 정본이다. 추론 서버가 release-gate 를 읽는 길은 ADR 0070(계약 RUNTIME R1.5·R3.23): 공개 입구가 아니라
#  release-gate 영역 게이트웨이로 바로 간다(같은 호스트 배치 = compose.inference.samehost.yaml 의 external 망 inference-in, 자기 영역 게이트웨이 출구 R1.8). 공개 입구에는 기계 호출자 경로가 없다.
sect "단계 9 앞부분: Compose에서 이미지로 서비스가 뜬다 (샌드박스 기동: 제품 -> 추론 서버가 release-gate 영역 게이트웨이로 release-gate 를 읽는다)"
pick_bind() { # 컨테이너가 호스트의 127.0.0.1 게시 포트에 닿는지 한 번 본다(Docker Desktop 은 닿고 리눅스 엔진은 보통 못 닿는다). 닿으면 127.0.0.1, 아니면 0.0.0.0
  local p srv ok=1; mkdir -p "$W/probe"; p=$(free_port)
  python3 -m http.server "$p" --bind 127.0.0.1 --directory "$W/probe" >/dev/null 2>&1 & srv=$!
  for _j in $(seq 1 30); do curl -s -m 1 -o /dev/null "http://127.0.0.1:$p/" && break; sleep 0.3; done   # 부하가 높으면 탐침 서버가 늦게 뜬다(4차 실행에서 오판)
  ok=0; for _j in 1 2 3; do "$DOCKER" run --rm --add-host host.docker.internal:host-gateway "$UTIL_REF" python -c "import sys,urllib.request;urllib.request.urlopen(sys.argv[1],timeout=8)" "http://host.docker.internal:$p/" >/dev/null 2>&1 && { ok=1; break; }; sleep 1; done
  kill "$srv" 2>/dev/null; wait "$srv" 2>/dev/null
  [ $ok = 1 ] && echo 127.0.0.1 || echo 0.0.0.0
}
BIND=$(pick_bind); export GATEWAY_BIND=$BIND INFERENCE_BIND=$BIND
# 호스트 포트는 Docker 배정이 아니라 시작 때 고른 빈 포트로 **고정**한다(고정 포트 번호를 리포에 적지 않으므로 동시 실행 충돌 없음). 왜: 다른 호스트 역할의 추론 서버는
# RELEASE_URL 에 게이트웨이 포트를, 제품은 INFERENCE_URL 에 추론 서버 포트를 들고 있다. 배정 포트는 컨테이너를 restart 하면 바뀌어(5d 의 kiosk-add-device.sh --apply 가 gateway 를 restart) 그 주소가 죽는다(2026-11-01 4차 실행).
docker_free_port() { # WSL 안에서 비어 있어도 Docker Desktop(윈도 포트 프록시)이 못 여는 포트가 있다(2026-11-02 "ports are not available"). Docker 로 실제 바인드해 본 포트만 쓴다
  local p _t
  for _t in 1 2 3 4 5 6 7 8; do p=$(free_port)
    "$DOCKER" run --rm -p "127.0.0.1:$p:1" "$UTIL_REF" true >/dev/null 2>&1 && { echo "$p"; return 0; }
  done
  echo "Docker 가 바인드할 수 있는 빈 포트를 8번 안에 찾지 못했다" >&2; return 1
}
export GATEWAY_PORT=$(docker_free_port) GATEWAY_TLS_PORT=$(docker_free_port); INFERENCE_FIXED_PORT=$(docker_free_port)
[ -n "$GATEWAY_PORT" ] && [ -n "$GATEWAY_TLS_PORT" ] && [ -n "$INFERENCE_FIXED_PORT" ] || { echo "호스트 포트 배정 실패" >&2; exit 1; }
# 다른 호스트의 추론 서버가 인증서를 받으려면 step-ca 에 닿아야 한다(ADR 0060): 운영에서 서버를 나눌 때와 같은 overlay(compose.step-ca-publish.yaml)로 step-ca 를 게시한다.
# 안팎 포트가 같아야 토큰 audience 가 맞는다(호스트 포트를 Docker 가 배정하게 두지 않고 시작 때 Docker 로 바인드해 본 빈 포트를 쓴다)
export STEP_CA_PORT=$(docker_free_port) STEP_CA_BIND=$BIND STEP_CA_DNS_NAMES=host.docker.internal
[ -n "$STEP_CA_PORT" ] || { echo "step-ca 게시 포트 배정 실패" >&2; exit 1; }
export COMPOSE_EXTRA="$COMPOSE_EXTRA $DEPLOY_ROOT/compose.step-ca-publish.yaml"
# 추론 서버가 TLS 로 부르는 이름(host.docker.internal)이 게이트웨이 인증서에 있어야 한다: 운영 설정 변수 GATEWAY_HOSTS 에 호출자가 쓰는 이름을 적는 것과 같다(실제 배포는 병원 내부 도메인)
export GATEWAY_HOSTS="localhost:8443, host.docker.internal:8443"
# 사람 인증(U82, ADR 0057): Keycloak 의 발급자와 oauth2-proxy 의 콜백은 밖에서 보이는 주소(첫 호스트 이름 + 밖에 보이는 포트)로 정해진다. 호스트 포트가 Docker 배정이므로 그 포트를 밖에 보이는 포트로 알린다
export GATEWAY_PUBLIC_TLS_PORT=$GATEWAY_TLS_PORT
# 한 줄의 export 안에서는 $(...) 가 앞의 대입(GATEWAY_PUBLIC_TLS_PORT)보다 먼저 풀려 기본 포트 8443 이 들어갔다(3차 E2E: 사람 로그인 연결 거부 3건). 그래서 따로 쓴다
export GATEWAY_PUBLIC_URL="$(gateway_public_url)"
if [ "$BIND" = 127.0.0.1 ]; then echo "  컨테이너가 호스트의 127.0.0.1 게시 포트에 닿는다: 게이트웨이·추론 서버는 127.0.0.1 에 게시한다"
else echo "  이 Docker 에서는 컨테이너가 호스트의 127.0.0.1 게시 포트에 닿지 못한다: 시험 동안 게이트웨이·추론 서버를 0.0.0.0 에 게시한다(방화벽은 이 PC 밖에서 막는다. docs/RUN.md 7-1)"; fi
INF_IMAGE="$DEPLOY_REGISTRY/openit/model-serving@$MODEL_SERVING_DIGEST"
cp "$SECRETS_DIR/tokens/inference-survey-service" "$W/inference-token"; chmod 644 "$W/inference-token"   # 컨테이너(uid 10001)가 읽는다. 폴더 $W 는 700
: > "$W/placeholder-ca.crt"; chmod 644 "$W/placeholder-ca.crt"
# 새 순서(U99, ADR 0060): 추론 서버는 인증서를 step-ca 에서 받으므로 제품(step-ca 게시)이 먼저 뜬다.
#  (1) 제품: up.sh --external-inference <자리표시 주소>  (2) 제품 입구의 CA·포트, step-ca 루트를 꺼내고 이 서버 이름의 일회용 토큰(5분)을 발급
#  (3) OUT-FILE(R1.5: 루트·hosts 표·SHA256SUMS)을 내보내고 대조한 뒤 추론 서버를 별도 프로젝트로(release-gate 영역 게이트웨이로 바로, ADR 0070)  (4) 실제 추론 서버 주소를 제품(survey-service)에 알린다.
mkdir -p "$W/pki"; : > "$W/placeholder-ca.crt"; chmod 644 "$W/placeholder-ca.crt"
STEP_IMG="$DEPLOY_REGISTRY/openit/step-ca@$STEP_CA_DIGEST"; SC_IMG="$DEPLOY_REGISTRY/openit/area-gateway@$AREA_GATEWAY_DIGEST"; PAUSE_IMG=$PAUSE_IMAGE   # 추론 서버(다른 호스트 역할)도 platform 이미지(step-ca cert, area-gateway)를 쓴다
inf_up() { # inf_up <주 서버 프로젝트(inference-in 망의 주인)> <OUT-FILE 루트 인증서 파일>: 추론 서버(compose.inference.yaml + 가짜 백엔드 overlay)를 별도 프로젝트로 올린다/다시 만든다
  local e=(INFERENCE_IMAGE="$INF_IMAGE" INFERENCE_TOKENS_FILE="$SECRETS_DIR/tokens/model-runtime-tokens" INFERENCE_RELEASE_TOKEN_FILE="$SECRETS_DIR/tokens/gate-read-model-serving" INFERENCE_RELEASE_NETWORK="${1}_inference-in" INFERENCE_PORT="$INFERENCE_FIXED_PORT"
    INFERENCE_CA_FILE="$2" INFERENCE_PKI_ROOT_FILE="$W/pki/root_ca.crt" INFERENCE_STEP_CA_URL="https://host.docker.internal:$STEP_CA_PORT" INFERENCE_TLS_NAME=host.docker.internal
    INFERENCE_GATEWAY_IMAGE="$SC_IMG" INFERENCE_EXPOSURE_FILE="${GATEWAYS_DIR:-$DEPLOY_ROOT/state/gateways}/model-serving/exposure.json" INFERENCE_STEP_IMAGE="$STEP_IMG" INFERENCE_PAUSE_IMAGE="$PAUSE_IMG" INFERENCE_TLS_TOKEN_FILE="$W/tls.ott")
  # 주입 대조(계약 ContainerInputs 3.5.0): 추론 서버 스택도 기동 전에 이미지 주입 선언과 같은지 본다(up.sh 와 같은 검사)
  env "${e[@]}" "$DOCKER" compose -p "$INF" -f "$DEPLOY_ROOT/compose.inference.yaml" -f "$DEPLOY_ROOT/compose.inference.samehost.yaml" -f "$DEPLOY_ROOT/test/compose.fake-model.yaml" config --format json \
    | "$DEPLOY_PY" -W ignore "$DEPLOY_ROOT/scripts/check_container_inputs.py" --compose-json - || { echo "추론 서버 compose 주입이 이미지 주입 선언과 다르다" >&2; return 1; }
  env "${e[@]}" "$DOCKER" compose -p "$INF" -f "$DEPLOY_ROOT/compose.inference.yaml" -f "$DEPLOY_ROOT/compose.inference.samehost.yaml" -f "$DEPLOY_ROOT/test/compose.fake-model.yaml" up -d --wait --wait-timeout $E2E_UP_WAIT_S 2>&1 | tail -3
  [ "${PIPESTATUS[0]}" = 0 ]
}
export INFERENCE_TOKEN_FILE="$W/inference-token"
# 운영 모드 overlay(compose.external-inference.yaml)를 이 스크립트의 환경에 둔다: 이후 모든 dc/up.sh/rollback.sh 호출이 같은 제품 구성을 본다(INFERENCE_URL, COMPOSE_EXTRA 를 내보낸다)
external_inference_setup "https://host.docker.internal:1"   # 자리표시: 추론 서버가 뜬 뒤 실제 주소로 바꾼다
chk "compose up --wait (digest 이미지, 읽기 전용 루트, cap_drop ALL)" bash "$DEPLOY_ROOT/scripts/up.sh" "$PROJECT"
chk_dep "compose up --wait (digest 이미지, 읽기 전용 루트, cap_drop ALL)" "시험 사용자를 Keycloak(realm openit)에 만든다 (운영 입구 kcadm, 사람 계정은 OIDC 로그인)" bash "$DEPLOY_ROOT/scripts/idp-test-users.sh" "$PROJECT"
NEED=("compose up --wait (digest 이미지, 읽기 전용 루트, cap_drop ALL)")   # 이하 항목은 스택이 떠야 의미가 있다: 실패하면 SKIP
abort_if_failed
PGW=$(port_of "${PROJECT}-gateway-1" 8080); PGWS=$(port_of "${PROJECT}-gateway-1" 8443)   # PGW: 평문(/healthz, 나머지는 308), PGWS: HTTPS. 제품의 호스트 포트는 gateway 와 step-ca(추론 서버의 인증서 발급용)뿐이다
# gateway 의 내부 CA 루트(시험용 CA): 이 시험의 클라이언트(curl --cacert, e2e_sandbox)와 추론 서버가 이것만 신뢰한다. 컨테이너가 방금 떴으므로 인증서가 만들어질 때까지 잠깐 기다린다
# (컨테이너 안의 파일 경로는 scripts/export-gateway-ca.sh 한 곳만 안다)
bash "$DEPLOY_ROOT/scripts/export-gateway-ca.sh" --project "$PROJECT" "$W/gateway-ca.crt" >/dev/null || { echo "gateway 내부 CA 루트를 가져오지 못했다"; exit 1; }
chmod 644 "$W/gateway-ca.crt"   # 공개 인증서다. 추론 서버 컨테이너(uid 10001)가 읽는다
GWCURL="curl --cacert $W/gateway-ca.crt"
issue_tls_token() { # step-ca 루트(공개)를 꺼내고 이 서버 이름의 일회용 토큰을 지휘 쪽 자격(step-ca 비밀번호)으로 발급한다
  "$DOCKER" run --rm -v "${PROJECT}_pki-root:/r:ro" "$UTIL_REF" cat /r/root_ca.crt > "$W/pki/root_ca.crt" || return 1
  # 역할 기반 입력(계약 StepCaEnv, 3.4.17): 인증서 이름은 host.docker.internal 하나다(SAN localhost 는 없다: 호스트에서는 --resolve 로 이 이름을 부른다)
  step_issue_token "$STEP_IMG" host.docker.internal "https://host.docker.internal:$STEP_CA_PORT" "$W/pki" "$SECRETS_DIR/tokens/step-ca-password" "$W/tls.ott" --add-host host.docker.internal:host-gateway || return 1
  chmod 644 "$W/pki/root_ca.crt"
  # 시험 프로세스(호스트)의 신뢰 묶음: 게이트웨이 CA(제품 입구)와 step-ca 루트(추론 서버 사이드카). 두 곳을 부르므로 둘 다 믿는다(검증을 끄지 않는다)
  cat "$W/gateway-ca.crt" "$W/pki/root_ca.crt" > "$W/trust.crt"; chmod 644 "$W/trust.crt"
}
chk "추론 서버용 일회용 TLS 토큰 발급 (step-ca 게시 포트로, 지휘 쪽 자격)" issue_tls_token
abort_if_failed
# OUT-FILE(R1.5): compose 밖 호출자에게 주는 루트 인증서·hosts 표·SHA256SUMS 를 운영과 같은 도구(export-out-files.sh)로 내보내고, 받는 쪽처럼 SHA-256 을 대조한 뒤 그 루트만 추론 서버에 준다.
# hosts 표의 주소는 release-gate 영역 pod(release-gate-net)가 inference-in 망에서 가진 주소다(공개 정보). 같은 호스트 배치는 이름을 Docker DNS(망 별칭)로 풀어 이 표를 쓰지 않는다: 다른 서버 배치의 입력(compose.inference.remote.yaml)이다.
# 왜 같은 호스트 배치로 시험하나(ADR 0070): 다른 서버 배치는 release-gate 영역 게이트웨이의 443 을 호스트에 게시한다(placement_ports). 시험 PC 에서 443 을 고정 게시하면 고정 포트 금지 규칙과 동시 실행에 어긋나고,
# Docker 가 배정한 포트는 계약 URL https://release-gate(443)와 출구 허용 목록(release-gate:443)에 맞지 않는다. 다른 서버 경로(hosts 표 + 443 게시)의 실제 기동은 test-split-pki-playbook.sh 가 본다.
export_out_file() {
  local ip; ip=$("$DOCKER" inspect "${PROJECT}-release-gate-net-1" --format "{{with index .NetworkSettings.Networks \"${PROJECT}_inference-in\"}}{{.IPAddress}}{{end}}") || return 1
  [ -n "$ip" ] || { echo "release-gate-net 이 ${PROJECT}_inference-in 망에 없다" >&2; return 1; }
  mkdir -p "$W/out-file" && bash "$DEPLOY_ROOT/scripts/export-out-files.sh" --out "$W/out-file" --root "$W/pki/root_ca.crt" --host "$ip release-gate" >/dev/null || return 1
  ( cd "$W/out-file" && sha256sum -c --quiet SHA256SUMS )   # 받는 쪽 대조(R1.5): 어긋나면 그 파일을 쓰지 않는다
}
chk "OUT-FILE 내보내기와 대조 (R1.5: 루트 인증서·hosts 표 <주소> release-gate·SHA256SUMS)" export_out_file
abort_if_failed
chk "추론 서버 기동 (별도 프로젝트 $INF: compose.inference.yaml, release-gate 영역 게이트웨이로 바로 읽는다(R1.5 OUT-FILE 루트, inference-in 외부 망 별칭, 자기 영역 게이트웨이 출구 R1.8), https)" inf_up "$PROJECT" "$W/out-file/root_ca.crt"
abort_if_failed
IPORT=$(port_of "$INF-model-serving-net-1" 443)
external_inference_setup "https://host.docker.internal:$IPORT"
chk "survey-service 가 추론 서버 주소를 쓴다 (INFERENCE_URL 갱신, up.sh)" bash "$DEPLOY_ROOT/scripts/up.sh" "$PROJECT"
abort_if_failed
cn() { if [ "$1" = model-serving ]; then echo "$INF-model-serving-1"; else echo "${PROJECT}-$1-1"; fi; }   # 컨테이너 이름: model-serving 은 제품이 아니라 추론 서버 프로젝트의 것이다
echo "  Docker가 배정한 호스트 포트: gateway=$PGW(평문) gateway-tls=$PGWS 추론서버=$IPORT (제품의 다른 서비스는 호스트 포트가 없다)"
getj() { curl -fsS -m 5 "http://127.0.0.1:$1$2"; }
getinf() { local o; o=$(curl -fsS -m 5 --cacert "$W/pki/root_ca.crt" --resolve "host.docker.internal:$IPORT:127.0.0.1" "https://host.docker.internal:$IPORT$1") || return 1; [ -n "$o" ] || { echo "본문이 비었다(사이드카가 Host 를 못 맞췄다?)"; return 1; }; printf "%s" "$o"; }   # 호스트에서는 localhost 로 부른다: 인증서 SAN 에 host.docker.internal 과 localhost 가 함께 있다(토큰·인증서에 --san). 컨테이너 쪽 호출자는 host.docker.internal 그대로
# R2.2·R4.3·R5.1: 서비스 건강 확인은 앱 포트(127.0.0.1:8080)를 직접 부르지 않고 **중계(TLS 종단)를 거쳐** 자기 서비스 이름으로 부른다(앱 컨테이너 안에서 https://<서비스 이름>, 같은 공간이라 별칭이 자기에게 풀린다).
# 앱만 살아 있는 상태를 건강으로 오판하지 않으려는 것이다. 판정은 상태 코드 + 본문 status(없으면 서비스별 ready, HealthStatus 정의 부재: docs/change-requests/CR-HealthStatus-schema.md)다.
# 왜 클라이언트 컨테이너인가: deploy 는 실행 중인 영역 컨테이너 안으로 들어가지 않는다(구조 규칙 1·6, CONVENTIONS 13절). 출발 서비스와 같은 망의 클라이언트가 https://<서비스> 를 그 영역 게이트웨이로 부른다(scripts/client-probe.sh, 인증서 검증을 끄지 않는다).
client_probe() { bash "$DEPLOY_ROOT/scripts/client-probe.sh" "$(cn "$1")" "$W/pki/root_ca.crt" "${@:2}"; }   # client_probe <출발 서비스> <탐침 인자...>
inpy() { client_probe "$1" body "https://$1$2"; }
inpy_code() { client_probe "$1" code "https://$1$2"; }
health_body_ok() { python3 -c "import sys,json
b=sys.stdin.read()
try: d=json.loads(b)
except Exception: sys.exit('본문이 JSON 이 아니다: '+b[:60])
st=d.get('status')
ok = (st=='ok') if st is not None else (d.get('ready') is True)
sys.exit(0 if ok else 'status/ready 가 정상이 아니다: '+b[:80])"; }
health_check() { local o; o=$("$@") || return 1; printf '%s' "$o" | health_body_ok; }
# /readyz 본문(R5.1, 계약 개정): 그 서비스의 준비 확인 스키마가 계약에 있으면(SurveyReadyz·GateReadyz·OpsFeedbackReadyz) 통과해야 하고, 없으면 비어 있지 않은 JSON 객체여야 한다. ready 가 있으면 참이어야 한다
readyz_obj() { local o; o=$("$@") || return 1; printf '%s' "$o" | python3 -c "import sys,json
d=json.loads(sys.stdin.read())
if not isinstance(d,dict) or not d: sys.exit('본문이 비어 있지 않은 JSON 객체가 아니다')
if d.get('ready') is False or d.get('status') in ('not-ready','error','fail','failed'): sys.exit('준비되지 않았다: '+json.dumps(d)[:80])"; }   # 스키마가 없는 서비스(model-serving)의 /readyz: status 값은 서비스별이다
readyz_check() { local sch o; case "$1" in survey-service) sch=SurveyReadyz;; release-gate) sch=GateReadyz;; ops-feedback) sch=OpsFeedbackReadyz;; *) sch=-;; esac
  o=$(inpy "$1" /readyz) || return 1
  printf '%s' "$o" | "$VENV/bin/python" -W ignore -c "import sys,json
from boundary_contracts import validator
d=json.loads(sys.stdin.read()); sch=sys.argv[1]
if not isinstance(d,dict) or not d: sys.exit('본문이 비어 있지 않은 JSON 객체가 아니다')
if sch!='-':
    e=[x.message for x in validator(sch).iter_errors(d)]
    if e: sys.exit(sch+' 위반: '+e[0][:100])
if d.get('ready') is False or d.get('status') in ('not-ready','error','fail','failed'): sys.exit('준비되지 않았다: '+json.dumps(d)[:80])   # status 값은 서비스별이다(question-authoring 은 "ready"): 스키마가 없으면 비어 있지 않은 객체 + 명백한 비정상만 거른다" "$sch"; }   # health_check inpy <서비스> <경로>
no_doors() { local bad; bad=$("$DOCKER" ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Names}} {{.Ports}}' | tr -d '\r' | grep -- '->' | grep -v "^${PROJECT}-gateway-1 " | grep -v "^${PROJECT}-step-ca-1 "); [ -z "$bad" ] || { echo "gateway 밖에서 호스트 포트를 게시한 제품 컨테이너: $bad"; return 1; }; echo "호스트 포트를 게시한 제품 컨테이너는 gateway 뿐이다 (시험용 문 0)"; }
chk "샌드박스: 제품에 시험용 문이 없다 (호스트 포트는 gateway 뿐, 실행 중 컨테이너 기준)" no_doors
chk "샌드박스: 제품 compose 정적 점검 (시험용 포트·가짜 백엔드·compose.test.yaml 없음)" "$VENV/bin/python" -W ignore "$DEPLOY_ROOT/scripts/test_compose_no_test_doors.py"
for n in gateway question-authoring release-gate ops-feedback model-registry dataset-store survey-service; do
  if [ "$n" = gateway ]; then chk "/healthz $n (본문 status=ok)" health_check getj "$PGW" /healthz; else chk "/healthz $n (중계를 거쳐, 본문 status=ok)" health_check inpy "$n" /healthz; fi
  [ "$n" = survey-service ] && continue
  [ "$n" = gateway ] && continue   # gateway /readyz 는 survey-service 를 반영한다(아래에서 따로)
  chk "/readyz $n (중계를 거쳐, 계약 Readyz 스키마 또는 비어 있지 않은 JSON 객체)" readyz_check "$n"
done
chk "/healthz model-serving (추론 서버, 별도 프로젝트, https, 본문 status=ok)" health_check getinf /healthz
chk "/readyz model-serving (추론 서버, 별도 프로젝트, https, 비어 있지 않은 JSON 객체)" readyz_obj getinf /readyz
survey_noactive() { local o; o=$(inpy_code survey-service /readyz); case "$o" in 503*no_active_release*) echo "활성 릴리스가 없어 503 no_active_release (정상: 아직 게이트에 PASS 릴리스가 없다)";; *) echo "기대와 다름: $o" | cut -c1-200; return 1;; esac; }
chk "/readyz survey-service: 활성 릴리스 전에는 503 no_active_release" survey_noactive
gw_mirrors() { local o; o=$(curl -s -m 5 -w ' [%{http_code}]' --cacert "$W/gateway-ca.crt" "https://localhost:$PGWS/readyz"); echo "$o" | grep -q '\[503\]' && ! echo "$o" | grep -q 'survey' && echo "gateway /readyz 는 survey-service 를 반영한다: 활성 릴리스 전 503, 본문에 내부 정보 없음 ($o)"; }
chk "/readyz gateway: 정적 200 이 아니라 환자 경로 survey-service 를 반영(활성 릴리스 전 503, 내부 정보 없음)" gw_mirrors
chk "/healthz gateway: 상류와 무관하게 200" getj "$PGW" /healthz
tls_checks() { # HTTPS 필수(D88/U5): 평문은 /healthz 만 답하고 나머지는 308 로 https 로 보낸다. HTTPS 는 시험용 CA 로 검증되고 HSTS 가 있다
  local r; r=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' "http://127.0.0.1:$PGW/v1/sessions"); echo "$r" | grep -q '^308 https://' || { echo "평문 요청이 https 로 308 이동하지 않는다: $r"; return 1; }
  [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PGW/staff/")" = 308 ] || { echo "평문 /staff/ 가 308 이 아니다"; return 1; }
  curl -s "http://127.0.0.1:$PGW/healthz" | grep -Eq '"status": *"ok"' || { echo "평문 /healthz 본문이 HealthStatus(status=ok)가 아니다"; return 1; }
  curl -s -o /dev/null "https://localhost:$PGWS/healthz" 2>/dev/null && { echo "시험용 CA 없이 https 가 검증을 통과했다(자체 서명 인증서를 신뢰하는 환경?)"; return 1; }   # status-code-ok: TLS 신뢰 점검(검증 실패를 보는 시험이라 본문은 무관)
  local h; h=$($GWCURL -s -D - -o /dev/null "https://localhost:$PGWS/healthz") || { echo "시험용 CA 로 https 접속 실패"; return 1; }   # status-code-ok: TLS 신뢰 점검(응답 머리글만 본다)
  echo "$h" | grep -qi '^strict-transport-security: max-age=31536000' || { echo "HSTS 헤더가 없다"; return 1; }
  echo "$h" | grep -qi '^x-content-type-options: nosniff' || { echo "X-Content-Type-Options 가 없다"; return 1; }
  echo "$h" | grep -qi '^x-frame-options: DENY' || { echo "X-Frame-Options 가 없다"; return 1; }
  [ "$($GWCURL -s -o /dev/null -w '%{http_code}' "https://localhost:$PGWS/config.json")" = 404 ] || { echo "/config.json 이 막혀 있지 않다"; return 1; }
  echo "평문: /healthz 만 ok, 나머지 308 https; https: 시험용 CA 검증 통과, HSTS·nosniff·X-Frame-Options, /config.json 404"
}
chk "TLS(D88/U5): 평문은 308 https 로 이동, https 는 시험용 CA 로 검증되고 HSTS·보안 헤더가 있다" tls_checks
no_test_policy() { local out rc=0; out=$(grep -rEn --exclude=verify-areas.yaml 'test-gate|test_gate|smoke_fakes|GATE_POLICY_FILE|GATE_ALLOW_TEST|FAKE_RISK_PHRASE' "$DEPLOY_ROOT/compose.yaml" "$DEPLOY_ROOT/config/" 2>&1) || rc=$?
  [ $rc -le 1 ] || { echo "grep 가 실패했다(종료 코드 $rc): 점검 대상을 읽지 못했다"; return 1; }   # rc 1 = 일치 없음, 2 = 오류(파일 없음 등): 오류를 "없음"으로 세지 않는다
  ! printf '%s\n' "$out" | grep -v '^[^:]*:[0-9]*:[[:space:]]*#' | grep -q .; }
chk "운영 compose.yaml/config 에 시험용 정책·실행기·대역이 없다" no_test_policy
no_auto_pass() { inpy release-gate /readyz | python3 -c "import sys,json;d=json.load(sys.stdin);print('gate /readyz',{k:d.get(k) for k in ('judging','awaiting_approval','gate_policy_version')});sys.exit(0 if d.get('judging')=='enabled' else 1)"; }
chk "gate /readyz: 판정 켜짐(I1·I3 연결), 정책 파일 없이 기본 정책, 승인 대기 개수 항목" no_auto_pass
# 인증 없는 요청의 기대 응답은 계약(노출 선언의 auth, RUNTIME R3.13·R3.23, CONVENTIONS 9절)에서 만든다(scripts/check_unauth.py). 주소의 이름은 공개 입구가 받는 이름(GATEWAY_PROBE_SITE)이다
chk "gateway: 인증 없는 요청의 응답이 계약에서 만든 기대 행과 같다" bash "$DEPLOY_ROOT/scripts/check-unauth.sh" "$PROJECT" "https://${GATEWAY_PROBE_SITE:-gateway:8443}" "$W/gateway-ca.crt"
chk "사람 화면 주소(GATEWAY_PUBLIC_URL)가 게이트웨이 HTTPS 호스트 포트와 같다 (Keycloak 발급자·로그인 쿠키가 이 주소에 묶인다, U82)" bash -c "[ \"\$GATEWAY_PUBLIC_URL\" = \"https://localhost:$PGWS\" ]"
# 도달·차단 판정은 한 함수(probe_http / probe_tcp)가 세 값 중 하나를 낸다: ok(응답 확인) / unreachable(연결 실패·시간 초과·이름 안 풀림) / bad(응답은 왔으나 본문·상태가 다르다). 빈 값은 docker exec 자체가 실패한 것(컨테이너 없음 등)이라 판정할 수 없다.
# 왜: 차단(부정) 단언이 `! 명령` 이면 컨테이너가 없거나 exec 가 실패해도 "차단됨"으로 통과한다(정적 점검 A11). 차단은 unreachable 일 때만 통과한다.
probe_http() { # probe_http <출발 서비스> <URL> <초>: 본문이 ok 로 시작하거나 JSON status==ok 면 ok
  client_probe "$1" http "$2" "$3" 2>/dev/null | tail -1; }
probe_tcp() { # probe_tcp <출발 서비스> <호스트> <포트> <초>: ok(연결됨) / unreachable
  bash "$DEPLOY_ROOT/scripts/client-probe.sh" "${PROJECT}-$1-1" "$W/pki/root_ca.crt" tcp "$2" "$3" "$4" 2>/dev/null | tail -1; }
reach() { [ "$(probe_http "$1" "https://$2/healthz" "$REACH_T")" = ok ]; }   # 서비스는 TLS 사이드카(443)로만 받는다(ADR 0060). 컨테이너의 SSL_CERT_FILE 이 step-ca 루트를 가리킨다
reachu() { [ "$(probe_http "$1" "$2" "$REACH_T")" = ok ]; }   # reachu <출발 서비스> <URL>: 호스트를 거치는 경로(host.docker.internal)는 Docker Desktop 프록시라 부하 때 3초를 넘겼다(4차 실행)
blockedu() { [ "$(probe_http "$1" "$2" "$REACH_T")" = unreachable ]; }
blocked() { [ "$(probe_http "$1" "https://$2/healthz" "$REACH_T")" = unreachable ]; }   # body-judged: probe_http 가 본문 status 를 판정한다(차단은 unreachable 일 때만 통과)
net_is() { # net_is <네트워크> <컨테이너...>: 네트워크의 구성원이 정확히 그 컨테이너들이다
  local n=$1; shift; local got want
  got=$("$DOCKER" network inspect "${PROJECT}_$n" --format '{{range .Containers}}{{.Name}}{{"\n"}}{{end}}' | sed '/^$/d' | sort | tr '\n' ' ')
  want=$(printf '%s\n' "$@" | sort | tr '\n' ' ')
  [ "$got" = "$want" ] || { echo "구성원 불일치: $n (실제: $got/ 기대: $want)"; return 1; }   # 컨테이너 이름은 비밀이 아니다: 불일치의 원인을 진단 파일에서 바로 본다
}
chk "도달: survey-service -> ops-feedback (serving, I6)" reach survey-service ops-feedback
chk "도달: survey-service -> release-gate (serving, I4)" reach survey-service release-gate
chk "도달: release-gate -> question-authoring (release, I1)" reach release-gate question-authoring
chk "도달: release-gate -> model-registry (release, I3)" reach release-gate model-registry
chk "차단: survey-service -> question-authoring" blocked survey-service question-authoring
chk "차단: survey-service -> model-registry" blocked survey-service model-registry
chk "차단: survey-service -> dataset-store (I2 는 datasets 네트워크뿐, ADR 0032)" blocked survey-service dataset-store
chk "차단: release-gate -> dataset-store" blocked release-gate dataset-store
chk "차단: model-registry -> dataset-store" blocked model-registry dataset-store
# 망의 구성원은 영역 pod 의 네트워크 공간 컨테이너(<서비스>-net, pause)다: 앱·사이드카는 network_mode: service:<서비스>-net 으로 그 공간에 붙어 망 구성원 목록에 따로 나오지 않는다(ADR 0060, RUNTIME R3.2/DC-NET.1)
chk "네트워크 datasets 에는 dataset-store 영역 pod 만 있다(시험용 test-ds 는 별도)" net_is datasets "${PROJECT}-dataset-store-net-1"
no_dataset_route() { # 공개 입구가 내보내는 경로 = 영역 Exposure 의 routes 중 auth.kind 가 denied 가 아니고 /healthz·/readyz·/metrics 가 아닌 것(계약 CONVENTIONS "공개 입구의 경로 표" 3.4.9).
  # 그 경로에 dataset-store 의 것(서비스 dataset-store 의 경로, 또는 /v1/datasets 경로)이 하나도 없어야 한다(ADR 0032). egress(나가는 쪽 허용 목록)와 denied 경로는 공개 입구 경로가 아니다(R1.8, R3.23)
  local d="${GATEWAYS_DIR:-$DEPLOY_ROOT/state/gateways}/exposures"; [ -n "$(ls "$d" 2>/dev/null)" ] || { echo "Exposure 선언 폴더가 비었거나 없다: $d"; return 1; }   # 폴더가 비었으면 "경로 없음"으로 통과하지 않는다
  python3 - "$d" <<'PY'
import json, pathlib, sys
fs = sorted(pathlib.Path(sys.argv[1]).glob("*.json"))
if not fs: print("Exposure 선언 파일이 없다"); sys.exit(1)
HEALTH = {"/healthz", "/readyz", "/metrics"}; bad = []
for f in fs:
    e = json.loads(f.read_text())
    for r in e.get("routes", []):
        if r.get("auth", {}).get("kind") == "denied": continue
        for p in r.get("paths", []):
            if p in HEALTH: continue
            if e.get("service") == "dataset-store" or "datasets" in p: bad.append(f"{f.name}: {p} (auth={r.get('auth', {}).get('kind')})")
if bad: print("공개 입구가 내보낼 dataset-store 경로:", "; ".join(bad)); sys.exit(1)
print(f"Exposure {len(fs)}개: 공개 입구에 나가는 dataset-store 경로 없음(dataset-store 경로는 모두 denied)")
PY
}
chk "공개 입구에 낸 영역 Exposure 선언에 dataset-store 경로가 없다" no_dataset_route
chk "차단: question-authoring -> survey-service" blocked question-authoring survey-service
for pair in "db-survey:survey-service:survey-db" "db-qa:question-authoring:question-authoring-db" "db-ops:ops-feedback:ops-feedback-db" "db-gate:release-gate:release-gate-db"; do   # 영역마다 자기 DB 컨테이너(구조 규칙 1)
  _n=${pair%%:*}; _r=${pair#*:}; _svc=${_r%%:*}; _db=${_r##*:}
  chk "db 네트워크 $_n 에는 $_db 와 $_svc 영역 pod 만 있다(다른 영역의 DB 에 닿지 않는다)" net_is "$_n" "${PROJECT}-$_db-1" "${PROJECT}-$_svc-net-1"   # 영역 쪽 구성원은 pod 공간 컨테이너(<서비스>-net, ADR 0060)
done
tcp() { [ "$(probe_tcp "$1" "$2" "$3" "$TCP_T")" = ok ]; }
for pair in survey-service:survey-db question-authoring:question-authoring-db ops-feedback:ops-feedback-db release-gate:release-gate-db; do chk "도달: ${pair%%:*} -> ${pair##*:}:5432 (db 네트워크)" tcp "${pair%%:*}" "${pair##*:}" 5432; done
no_published_port() { "$DOCKER" inspect "$1" >/dev/null 2>&1 || { echo "컨테이너가 없다: $1"; return 1; }; [ -z "$("$DOCKER" port "$1" 2>/dev/null)" ]; }   # 컨테이너가 없으면 "게시 없음"으로 통과하지 않는다
tcp_blocked() { [ "$(probe_tcp "$1" "$2" "$3" "$TCP_T")" = unreachable ]; }
for _db in survey-db question-authoring-db ops-feedback-db release-gate-db; do chk "차단: model-registry -> $_db" tcp_blocked model-registry $_db 5432; done
chk "차단: survey-service -> 다른 영역의 DB(release-gate-db)" tcp_blocked survey-service release-gate-db 5432
for _db in survey-db question-authoring-db ops-feedback-db release-gate-db; do chk "차단: 호스트에 $_db 포트 게시 없음" no_published_port "${PROJECT}-$_db-1"; done
chk "도달: survey-service -> 추론 서버 (다른 호스트 역할, I9)" reachu survey-service "https://host.docker.internal:$IPORT/healthz"   # body-judged: reachu 가 본문 status/ok 를 판정한다
# 추론 서버가 release-gate 를 읽는 운영 경로는 공개 입구가 아니라 release-gate 영역 게이트웨이다(ADR 0070, 계약 R1.5·R3.23: 공개 입구에는 기계 호출자 경로가 없다). 검증 루트는 OUT-FILE 의 루트(R1.5, 대조 통과본)
reach_outfile() { [ "$(bash "$DEPLOY_ROOT/scripts/client-probe.sh" "$(cn "$1")" "$W/out-file/root_ca.crt" http "https://$2/healthz" "$REACH_T" 2>/dev/null | tail -1)" = ok ]; }
chk "도달: 추론 서버 -> release-gate 영역 게이트웨이(R1.5: OUT-FILE 루트로 TLS 검증, inference-in 망 별칭 release-gate, I4 번들 읽기의 운영 경로 ADR 0070·D72)" reach_outfile model-serving release-gate
chk "차단: 추론 서버 -> question-authoring (제품 내부 이름으로는 닿지 않는다)" blocked model-serving question-authoring
chk "도달: question-authoring -> ops-feedback (authoring, 개선 신호가 I7을 읽음)" reach question-authoring ops-feedback
chk "차단: ops-feedback -> model-registry" blocked ops-feedback model-registry
noegress() { [ "$(probe_http release-gate http://1.1.1.1 "$TCP_T")" = unreachable ]; }
chk "내부 네트워크 밖으로 나가지 못함(release-gate -> 외부 인터넷)" noegress
chk "보존 정리 잡이 이미지 선언의 argv로 실행된다: release-gate prune(멱등)" bash "$DEPLOY_ROOT/scripts/run-job.sh" job-release-gate-prune
chk "보존 정리 잡이 Compose 에서 실행된다: survey purge(SURVEY_SESSION_RETENTION_DAYS=90, 지운 개수 JSON)" bash -c "set -o pipefail; bash $DEPLOY_ROOT/scripts/run-job.sh job-survey-purge | tail -1 | python3 -c 'import json,sys;json.loads(sys.stdin.read());print(\"purge 출력이 JSON 한 줄\")'"
chk "보존 정리 잡이 Compose 에서 실행된다: question-authoring purge(멱등; 출력 한 줄은 지운 개수 요약)" bash -c "set -o pipefail; bash $DEPLOY_ROOT/scripts/run-job.sh job-question-authoring-purge | tail -1 | grep -q ."
chk "컨테이너 격리 실제 확인(check-containers: 비루트·읽기 전용·cap_drop ALL·no-new-privileges·자원 한도·로그 회전)" bash "$DEPLOY_ROOT/scripts/check-containers.sh" "$PROJECT"
nonroot() { local u; u=$("$DOCKER" inspect "$(cn "$1")" --format '{{.Config.User}}' | tr -d '\r'); u=${u%%:*}; [ -n "$u" ] || u=$("$DOCKER" top "$(cn "$1")" -eo pid,uid | awk 'NR==2{print $2}' | tr -d '\r'); case "$u" in ""|0|root) return 1;; esac; }   # 컨테이너 밖에서 본다: Config.User, 없으면 docker top 의 PID 1 uid(CONVENTIONS 13절)
bydigest() { "$DOCKER" inspect "$(cn "$1")" --format '{{.Config.Image}}' | tr -d '\r' | grep -E '@sha256:[0-9a-f]{64}$'; }
labels6() { validate_image_labels "$1" "$2"; }   # 라벨 검사는 계약 ImageLabels 검증 하나다(손으로 키를 따로 보지 않는다, U44). 필수 키·빈 값·revision 형식·n/a 표기를 스키마가 본다
for s in survey-service question-authoring ops-feedback release-gate model-registry dataset-store model-serving kiosk-frontend admin-console; do
  chk "비root 실행 $s" nonroot "$s"
  chk "컨테이너가 digest로 만들어짐 $s" bydigest "$s"
done
for pair in "survey-service:$SURVEY_SERVICE_DIGEST" "question-authoring:$QUESTION_AUTHORING_DIGEST" "ops-feedback:$OPS_FEEDBACK_DIGEST" "release-gate:$RELEASE_GATE_DIGEST" "model-registry:$MODEL_REGISTRY_DIGEST" "dataset-store:$DATASET_STORE_DIGEST" "model-serving:$MODEL_SERVING_DIGEST" "admin-console:$ADMIN_CONSOLE_DIGEST"; do
  chk "이미지 라벨이 계약 ImageLabels 를 따른다 ${pair%%:*}" labels6 "$DEPLOY_REGISTRY/openit/${pair%%:*}@${pair#*:}" "${pair%%:*}"
done

labels_kiosk() { validate_image_labels "$1" kiosk-frontend; }   # 계약 ImageLabels 검증 하나(app-version 은 계약의 선택 확장 키로 스키마가 형식을 본다)
chk "이미지 라벨이 계약 ImageLabels 를 따른다 kiosk-frontend" labels_kiosk "$DEPLOY_REGISTRY/openit/kiosk-frontend@$KIOSK_FRONTEND_DIGEST"
langgraph_label() { local v; v=$("$DOCKER" image inspect "$DEPLOY_REGISTRY/openit/survey-service@$SURVEY_SERVICE_DIGEST" --format '{{index .Config.Labels "io.openit.langgraph"}}' | tr -d '\r'); [ -n "$v" ] && [ "$v" != unknown ] && echo "io.openit.langgraph=$v"; }
chk "survey-service 이미지의 io.openit.langgraph 라벨이 unknown이 아니다" langgraph_label
sect "단계 1~8 (실제 서비스의 HTTP로 잇는다)"
IMAGES="{\"survey-service\":\"$DEPLOY_REGISTRY/openit/survey-service@$SURVEY_SERVICE_DIGEST\",\"question-authoring\":\"$DEPLOY_REGISTRY/openit/question-authoring@$QUESTION_AUTHORING_DIGEST\",\"ops-feedback\":\"$DEPLOY_REGISTRY/openit/ops-feedback@$OPS_FEEDBACK_DIGEST\",\"dataset-store\":\"$DEPLOY_REGISTRY/openit/dataset-store@$DATASET_STORE_DIGEST\"}"
PORTS="{\"gw\":$PGWS,\"ms\":$IPORT}"   # 샌드박스: 단계 코드가 아는 호스트 포트는 게이트웨이(TLS)와 추론 서버뿐이다. 옛 키(qa, gate, ops, survey, mr, ds)는 없다: 쓰면 KeyError 로 드러난다
if [ "$UPONLY" = 1 ]; then
  echo "--up-only: 기동·도달·격리 점검까지만 했다. 단계(e2e_steps.py)는 돌리지 않는다"
  sect ""; finish; [ "$FAILS" = 0 ]; exit $?
fi
STEP_OPTS=(); [ "$FAILFAST" = 1 ] && STEP_OPTS+=(--fail-fast); [ "$CHANGED" = 1 ] && STEP_OPTS+=(--changed-only)
"$VENV/bin/python" "$DEPLOY_ROOT/scripts/e2e_steps.py" --forms-dir "${E2E_FORMS_DIR:-${SETUP_ENV_WORK:-$DEPLOY_ROOT/state/areas}/question-authoring/forms}" --project "$PROJECT" --secrets "$SECRETS_DIR" --ports "$PORTS" --images "$IMAGES" --docker "$DOCKER" --root "$DEPLOY_ROOT" --work "$W/work" --gw-ca "$W/trust.crt" --ms-container "$INF-model-serving-1" --out-file "$W/out-file" --run-id e2e-test ${ONLY:+--only "$ONLY"} "${STEP_OPTS[@]}" | tee "$W/steps.log"
STEPS_RC=${PIPESTATUS[0]}
# 단계별 상태(steps.json)를 항목 상태표에 올린다: '단계 N' 이름으로 뒤 항목이 선행으로 쓴다. 단계 안의 SKIP 은 SKIP 개수에 더한다
if [ -f "$W/work/steps.json" ]; then
  while IFS='|' read -r sid sst; do STAT["단계 $sid"]=$sst; done < <(python3 "$DEPLOY_ROOT/scripts/e2e_plan.py" step-status "$W/work/steps.json")
  STEP_SKIPS=$(python3 "$DEPLOY_ROOT/scripts/e2e_plan.py" skips "$W/work/steps.json")
fi
if [ "$STEPS_RC" = 0 ]; then res "단계 1~8 (REAL/TEST-SUB 항목의 스키마·해시 검증)" PASS "BLOCKED 항목은 아래 요약과 docs/change-requests 참고$([ "${STEP_SKIPS:-0}" != 0 ] && echo "; 단계 안 SKIP ${STEP_SKIPS}")"
else res "단계 1~8" FAIL "e2e_steps.py 종료 코드 $STEPS_RC"
  # 단계가 실패하면 그 자리에서 영역 컨테이너 로그 끝 300줄을 진단 폴더($W/diag, collect_diag 가 복사한다)에 남긴다. 왜: 뒤의 백업·복구·롤백 구간이 제품 스택을 내렸다 올려
  # 정리 때 수집하면 실패 순간의 영역 로그가 없다(2026-11-08 진단 폴더에 감시·추론 서버 로그만 남았다). 로그만 쓰고 환경 변수·inspect 전체는 담지 않는다(비밀 금지)
  mkdir -p "$W/diag/logs-after-steps"
  for c in $("$DOCKER" ps -a --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Names}}' 2>/dev/null | tr -d '\r'); do timeout 60 "$DOCKER" logs --tail 300 "$c" > "$W/diag/logs-after-steps/$c.log" 2>&1; done
fi
chk "비밀 노출 점검: 환경 변수·inspect·exec env 에 secrets 값 없음 (check-secrets-hidden)" bash "$DEPLOY_ROOT/scripts/check-secrets-hidden.sh" "$PROJECT"

if [ "$FAST" = 0 ]; then   # --fast 에서는 아래 세 구간(스케줄러, 백업·복구, 롤백)을 건너뛴다
has_s9() { case ",$SECTIONS," in *",$1,"*) return 0;; esac; return 1; }
if has_s9 jobs; then
sect "단계 9: 주기 잡 (D39, systemd timer)"
chk "ops-feedback 잡이 이미지 선언·설정·볼륨·네트워크로 실제 실행된다" bash "$DEPLOY_ROOT/scripts/run-job.sh" job-ops-feedback
chk_dep "단계 4" "수집기 잡 엔트리포인트(release_gate collect, 단계 4에서 실제 실행됨)" bash -c "grep -a -q 'job-release-gate-collect\|수집기 run-once' $W/steps.log"
chk "잡 설정이 없으면 run-job 은 거부(종료 코드 2)" bash -c "OPS_JOB_CONFIG=/nonexistent/job.yaml bash $DEPLOY_ROOT/scripts/run-job.sh job-ops-feedback; [ \$? = 2 ]"
# 주기 실행은 systemd timer 의 몫이다(ADR 0036). 유닛 파일은 정적 시험으로 확인하고(주기·oneshot·스크립트·systemd-analyze verify), 실제 잡 실행은 위 run-job.sh 호출이 Compose 안에서 확인한다
# 감시 스택(ADR 0037): 같은 프로젝트에 compose.monitoring.yaml 의 서비스를 올려 실제 gateway·release-gate·model-serving 를 탐침하는지 본다.
# (이전 구간은 check-health.sh 가 gateway /healthz 평문·HTTPS 를 읽었다. HTTPS 탐침은 서버 밖 감시의 몫이라 external-targets.yml 에 둔다.)
export METRICS_DIR="$W/metrics"; mkdir -p "$METRICS_DIR"; chmod 755 "$METRICS_DIR"; SERVICE_RESULT=success must bash "$DEPLOY_ROOT/scripts/job-metrics.sh" e2e-demo 600   # 600초: 시험용 임의 주기(알람 판정이 아니라 지표 파일 형식 시험용, 측정 안 함)
chk "감시 스택 기동 (prometheus, alertmanager, blackbox/json/node exporter)" bash -c "source '$DEPLOY_ROOT/scripts/lib.sh'; COMPOSE_EXTRA='$COMPOSE_EXTRA $DEPLOY_ROOT/compose.monitoring.yaml' dc '$PROJECT' up -d --wait --wait-timeout $E2E_UP_WAIT_S prometheus alertmanager"
chk_dep "감시 스택 기동 (prometheus, alertmanager, blackbox/json/node exporter)" "감시 스택이 실제 서비스를 본다 (탐침 probe_success=1 이 하나 이상이고 0 이 없다, platform 감시 이미지의 Prometheus API)" bash -c 'for i in $(seq 1 '"$((E2E_MON_POLL_S/2))"'); do out=$('"$DOCKER"' exec "'"$PROJECT"'-prometheus-1" wget -qO- "http://127.0.0.1:9090/api/v1/query?query=probe_success" 2>/dev/null); ok=$(printf "%s" "$out" | grep -o "\"1\"\]" | wc -l); bad=$(printf "%s" "$out" | grep -o "\"0\"\]" | wc -l); [ "$ok" -ge 1 ] && [ "$bad" = 0 ] && exit 0; sleep 2; done; exit 1'
chk "GPU 서버 잡(synthetic-data, model-lab, gate-worker)은 이 Compose에 없다(서빙 서버 밖, D40)" bash -c "! grep -E '^  (job-)?(synthetic-data|model-lab|gate-worker)' $DEPLOY_ROOT/compose.yaml"

fi
if has_s9 backup; then
sect "단계 9: 영역 백업·복구 (영역이 자기 백업·복구 잡을 돌린다, RUNTIME R10.1·DATA_OWNERSHIP)"
# deploy 는 영역 데이터를 직접 꺼내지 않는다(구조 규칙 1·6, 계약 3.4.16): 영역의 백업·복구 잡(io.openit.jobs, compose job-*-backup / job-*-restore)을 돌리고 결과는 마지막 줄의 BackupJobResult(계약 검증)로 판정한다.
# 복구한 데이터는 공개 API 로 다시 읽어 대조한다(e2e_verify_restore.py). 영역 DB 를 직접 읽는 지문(pg-fingerprint.sh)·docker exec psql 은 쓰지 않는다.
# 범위: survey-service, question-authoring, ops-feedback, release-gate(DB 영역 4개), model-lab(models-data), synthetic-data(datasets-data), 백업은 platform 의 공개 입구(gateway-data)·인증기관(pki-ca)도 돈다(그 둘의 복구는 이 흐름에서 검증할 수 없다: e2e_backup_jobs.py NO_E2E_RESTORE). identity-db(Keycloak 계정·역할)는 platform 의 identity-db 이미지 잡이다(복구는 identity 를 멈춘 뒤).
chk "백업 잡 9개(영역 6 + 사람 인증 DB + 공개 입구·인증기관) (BackupJobResult status=ok)" "$VENV/bin/python" "$DEPLOY_ROOT/scripts/e2e_backup_jobs.py" backup --project "$PROJECT"
NEED+=("백업 잡 9개(영역 6 + 사람 인증 DB + 공개 입구·인증기관) (BackupJobResult status=ok)")   # 백업이 실패하면 아래 데이터 삭제·복구는 의미가 없다(볼륨을 지우지도 않는다)
dc "$PROJECT" down >/dev/null 2>&1
AREA_VOLUMES="survey-db-data question-authoring-db-data ops-feedback-db-data release-gate-db-data identity-db-data gate-data models-data datasets-data"   # 영역 데이터 볼륨(compose 볼륨 이름)
chk_dep "백업 잡 9개(영역 6 + 사람 인증 DB + 공개 입구·인증기관) (BackupJobResult status=ok)" "볼륨 삭제(재난을 흉내: 영역 데이터 볼륨, 백업 저장소 볼륨은 남긴다)" bash -c "$DOCKER volume rm $(for _v in $AREA_VOLUMES; do printf '%s_%s ' "$PROJECT" "$_v"; done) >/dev/null"
chk_dep "볼륨 삭제(재난을 흉내: 영역 데이터 볼륨, 백업 저장소 볼륨은 남긴다)" "빈 볼륨에서 스택 기동" bash "$DEPLOY_ROOT/scripts/up.sh" "$PROJECT"
chk_dep "빈 볼륨에서 스택 기동" "사람 인증(identity) 정지: 복구는 identity 를 멈춘 뒤 돌린다(platform identity-db 잡 선언)" dc "$PROJECT" stop identity
chk_dep "사람 인증(identity) 정지: 복구는 identity 를 멈춘 뒤 돌린다(platform identity-db 잡 선언)" "영역 복구 잡 7개 (BackupJobResult status=ok)" "$VENV/bin/python" "$DEPLOY_ROOT/scripts/e2e_backup_jobs.py" restore --project "$PROJECT"
# 복구한 데이터를 서비스가 다시 읽게 영역 서비스만 다시 시작한다(compose 재시작, 영역 안으로 들어가지 않는다)
chk_dep "영역 복구 잡 7개 (BackupJobResult status=ok)" "복구 뒤 영역 서비스 재시작" dc "$PROJECT" restart identity survey-service question-authoring ops-feedback release-gate model-registry dataset-store
NEED+=("볼륨 삭제(재난을 흉내: 영역 데이터 볼륨, 백업 저장소 볼륨은 남긴다)" "빈 볼륨에서 스택 기동" "영역 복구 잡 7개 (BackupJobResult status=ok)" "복구 뒤 영역 서비스 재시작")
PGWS=$(port_of "${PROJECT}-gateway-1" 8443)   # 스택을 다시 만들었으니 게이트웨이 호스트 포트를 다시 읽는다
PORTS="{\"gw\":$PGWS,\"ms\":$IPORT}"
chk_dep "단계 1~8" "복구한 데이터를 실제 서비스의 HTTP로 다시 읽는다(문항 2버전·해시, 같은 Trace 재전송=DUPLICATE, 모델 패키지·어댑터 해시, 활성 포인터)" \
  "$VENV/bin/python" "$DEPLOY_ROOT/scripts/e2e_verify_restore.py" --secrets "$SECRETS_DIR" --ports "$PORTS" --work "$W/work" --run-id e2e-test --project "$PROJECT" --docker "$DOCKER" --root "$DEPLOY_ROOT" --gw-ca "$W/trust.crt"

fi
if has_s9 rollback; then
sect "단계 9: digest 잠금으로 코드 축 롤백"
NEED=("compose up --wait (digest 이미지, 읽기 전용 루트, cap_drop ALL)" "복구 뒤 영역 서비스 재시작")   # 롤백 구간: 복구 뒤 스택이 떠 있어야 한다. 백업 구간의 나머지 실패는 이 구간과 무관하다
OLD_REF=$("$DOCKER" inspect "${PROJECT}-survey-service-1" --format '{{.Config.Image}}' | tr -d '\r')
cp "$DEPLOY_ROOT/build/images.env" "$W/images.env.bak"
chk "새 버전 빌드(시험: 시험 라벨 openit.test-build=test2, revision 은 그대로)" env BUILD_TEST_ID=test2 bash "$DEPLOY_ROOT/scripts/build-images.sh" survey-service
chk_dep "새 버전 빌드(시험: 시험 라벨 openit.test-build=test2, revision 은 그대로)" "새 버전 publish -> 잠금 갱신(이전 잠금은 history에 보관)" bash "$DEPLOY_ROOT/scripts/publish-images.sh" survey-service
cp "$W/images.env.bak" "$DEPLOY_ROOT/build/images.env"   # 시험용 test2 빌드가 build/images.env 에 남지 않게 한다
chk_dep "새 버전 publish -> 잠금 갱신(이전 잠금은 history에 보관)" "새 잠금으로 적용 -> survey-service가 새 digest 이미지로 교체" bash -c "bash $DEPLOY_ROOT/scripts/up.sh $PROJECT >/dev/null && [ \"\$($DOCKER inspect ${PROJECT}-survey-service-1 --format '{{.Config.Image}}' | tr -d '\r')\" != \"$OLD_REF\" ]"
chk_dep "새 잠금으로 적용 -> survey-service가 새 digest 이미지로 교체" "롤백: 잠금을 이전 것으로 되돌리고 적용 -> 이전 digest 이미지로 복귀" bash -c "bash $DEPLOY_ROOT/scripts/rollback.sh $PROJECT >/dev/null && [ \"\$($DOCKER inspect ${PROJECT}-survey-service-1 --format '{{.Config.Image}}' | tr -d '\r')\" = \"$OLD_REF\" ]"
survey_ready_after() { for i in $(seq 1 $((E2E_ROLLBACK_READY_S/2))); do o=$(inpy survey-service /readyz 2>/dev/null); echo "$o" | grep -q '"ready": true' && { echo "$o" | cut -c1-120; return 0; }; sleep 2; done; echo "$o"; return 1; }
chk_dep "롤백: 잠금을 이전 것으로 되돌리고 적용 -> 이전 digest 이미지로 복귀" "롤백 뒤 survey-service /readyz 200 (복구한 포인터의 릴리스를 HTTP로 다시 적재)" survey_ready_after

fi
fi
sect ""
finish
[ "$FAILS" = 0 ] && [ "$REC_RC" = 0 ]; exit $?
