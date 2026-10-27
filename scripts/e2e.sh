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
# 사용: scripts/e2e.sh [--fast] [--only <단계,...>] [--keep] [--keep-images] [--reuse-build]
#  --reuse-build: 이미지가 있고 소스 커밋·의존 태그가 라벨과 같으면 다시 빌드하지 않는다(낡은 것만 빌드). 끝나도 이미지를 지우지 않는다.
set -o pipefail
# 정적 일관성 점검(수 초): 영역 사이 어긋남을 6분짜리 E2E 앞에서 잡는다. FAIL 이면 E2E를 시작하지 않는다(건너뛰기 DEPLOY_SKIP_CHECK_ALL=1, 개발 중에만)
CA_TXT=""
if [ "${DEPLOY_SKIP_CHECK_ALL:-0}" != 1 ]; then
  CA_TXT=$(bash "$(dirname "$0")/check-all.sh" 2>&1); CA_RC=$?; printf '%s\n' "$CA_TXT"
  [ $CA_RC = 0 ] || { echo "check-all.sh 가 FAIL 이라 E2E를 시작하지 않는다 (위 FAIL 의 영역/파일:줄을 먼저 고친다)"; exit 1; }
fi
# 사전 점검: 실패하면 바로 멈춘다(건너뛰기 DEPLOY_SKIP_DOCTOR=1). 하위 up.sh 가 다시 점검하지 않게 export 한다
[ "${DEPLOY_SKIP_DOCTOR:-0}" = 1 ] || bash "$(dirname "$0")/doctor.sh" || exit 1
export DEPLOY_SKIP_DOCTOR=1
source "$(dirname "$0")/lib.sh"
KEEP=0; REUSE=0; KEEPIMG=0; FAST=0
ONLY=""
while [ $# -gt 0 ]; do case "$1" in
  --fast) FAST=1;; --keep) KEEP=1;; --reuse-build) REUSE=1; KEEPIMG=1;; --keep-images) KEEPIMG=1;;
  --only) [ $# -ge 2 ] || { echo "--only 에는 단계 목록이 필요하다 (예: --only 5p)" >&2; exit 2; }; ONLY=$2; shift;;
  --only=*) ONLY=${1#*=};;
esac; shift; done
# --only: e2e_steps.py 의 단계 일부만 돌린다(개발 중 한 단계 확인용). 스택 기동과 준비는 같이 하고, 스케줄러·백업·롤백 구간은 생략하며 결과를 정본에 기록하지 않는다. 전체 합격이 아니다
if [ -n "$ONLY" ]; then FAST=1; export DEPLOY_NO_RECORD=1; fi
ID=$$; PROJECT=deploy-e2e-$ID; RPROJ=deploy-e2e-reg-$ID
W="$DEPLOY_ROOT/state/e2e-$ID"; mkdir -p "$W"
export DEPLOY_LOCK="$W/images.lock" DEPLOY_REGISTRY_ENV="$W/registry.env" DEPLOY_PROJECT=$PROJECT
export REGISTRY_PROJECT=$RPROJ REGISTRY_HOST_BIND=0.0.0.0 REGISTRY_HOST_PORT=
UTIL_REF=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
export SECRETS_DIR="$W/secrets" COMPOSE_EXTRA="$DEPLOY_ROOT/compose.test.yaml $DEPLOY_ROOT/test/compose.fake-model.yaml" GATEWAY_PORT= GATEWAY_TLS_PORT= GATEWAY_TLS_PORT=
export OPS_JOB_CONFIG="$DEPLOY_ROOT/test/ops-job/test-ops-job.yaml"
RESULT=(); FAILS=0
# 구간별 소요 시간: sect "제목" 이 이전 구간을 닫고(소요 시간 출력) 새 구간 제목을 낸다. 끝의 요약에 표로 모은다
SEC_NAMES=(); SEC_SECS=(); SEC_CUR=""; SEC_T0=$SECONDS
sect() { local now=$SECONDS; if [ -n "$SEC_CUR" ]; then SEC_NAMES+=("$SEC_CUR"); SEC_SECS+=($((now-SEC_T0))); printf '  (소요 %ds)\n' $((now-SEC_T0)); fi; SEC_CUR="$1"; SEC_T0=$now; if [ -n "$1" ]; then echo; echo "== $1"; fi; }
res() { RESULT+=("$1|$2|$3"); [ "$2" = FAIL ] && FAILS=$((FAILS+1)); printf '  [%s] %s: %s\n' "$2" "$1" "$3"; }
chk() { local name=$1; shift; local out; if out=$("$@" 2>&1); then res "$name" PASS "$(echo "$out" | tail -1 | cut -c1-150)"; else res "$name" FAIL "$(echo "$out" | tail -3 | tr '\n' ' ' | cut -c1-300)"; fi; }
cleanup() {
  local rc=$?
  [ $KEEP = 1 ] && { echo "--keep: 프로젝트 $PROJECT, 레지스트리 $RPROJ, 작업 폴더 $W 를 남겼다"; return; }
  echo; echo "== 정리"
  dc "$PROJECT" --profile jobs down -v --remove-orphans >/dev/null 2>&1
  bash "$DEPLOY_ROOT/scripts/registry.sh" down -v >/dev/null 2>&1
  for img in $("$DOCKER" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | tr -d '\r' | grep -E '^127\.0\.0\.1:[0-9]+/openit/'); do "$DOCKER" rmi -f "$img" >/dev/null 2>&1; done
  if [ $KEEPIMG = 0 ]; then for img in $("$DOCKER" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | tr -d '\r' | grep -E '^deploy-build/' | grep -v '^deploy-build/model-serving-gpu:'); do "$DOCKER" rmi -f "$img" >/dev/null 2>&1; done; fi   # 사용자가 따로 빌드한 13GB GPU 이미지(데모용)는 지우지 않는다
  rm -rf "$W" 2>/dev/null || "$DOCKER" run --rm -v "$DEPLOY_ROOT/state:/s" "$UTIL_REF" rm -rf "/s/e2e-$ID"
  echo "정리 완료 (프로젝트 $PROJECT, 레지스트리 $RPROJ, 이미지, 임시 폴더)"
  return $rc
}
trap cleanup EXIT

[ -n "$ONLY" ] && echo "!!! --only $ONLY: 일부 단계만 돈다. 전체 합격이 아니다(기록 안 함) !!!"
[ "$FAST" = 1 ] && [ -z "$ONLY" ] && echo "!!! --fast 모드: 스케줄러, 백업·복구, 코드 축 롤백 구간을 생략한다. 전체 합격이 아니다(인도 전에는 옵션 없는 전체 모드 필수) !!!"
cat <<BANNER
=============================================================================
 E2E 합격 시나리오 실행 (프로젝트 $PROJECT)   경계 계약 v2.0.2 (출고는 사람 승인, D53)
 !! 시험 대역 사용 표시 !!
   - 승인자: 사람 대신 이 스크립트가 시험용 승인자 토큰(release-approver)으로 POST /v1/approvals 를 호출한다. 시험용 정책·실행기는 없다(게이트에서 삭제됨)
   - 단계 3 모델: GPU 없이 시험용 어댑터(test/fixtures/e2e-test-adapter)와 시험용 EvaluationReport(고정 지표, 실제 평가 아님)를 model-registry에 HTTP로 게시한다(E2E_GPU=1이면 gpu-dev 경로, 기본 끔)
   - 단계 5 모델: model-serving 컨테이너(CPU)의 가짜 백엔드. A 출력은 입력 문항 기준으로 유효한 ActionExtraction(NEXT, 다음 문항; 흐름 파일에 칸 정의가 있는 문항은 발화에서 첫 칸의 ANSWERED 값과 건너뛰기 적용, 단계 5g), B 출력은 문장 "(가짜 응답)"이다(표준 서버 + MODEL_RUNTIME_FAKE_FLOW_FILE=test/fake-model/question_flow.json, model-runtime ${DEPLOY_MR_TAG}). 시험용 번들의 serving_config는 서버 /v1/info 기대값으로 만든다(TEST-SUB)
   - 직원 콘솔 접근: 개발/E2E용 기본 인증(운영 방식은 미정). 실제 브라우저·STT·웹 푸시 수신은 E2E에서 볼 수 없다(BLOCKED, VAPID 키 없이 SSE만)
   - 단계 6 TraceEnvelope와 단계 7 reviewed_input·검토 확인은 이 스크립트가 만든 시험 자료/행위다
   - 시험 자료는 운영 설정(compose.yaml, config/)에 들어가지 않는다
=============================================================================
BANNER

sect "준비: 이미지 빌드, 임시 레지스트리, digest 잠금"
bash "$DEPLOY_ROOT/scripts/prepare-host.sh" venv
have_images() { [ -f "$DEPLOY_ROOT/build/images.env" ] && [ "$(grep -vc '^model-serving-gpu ' "$DEPLOY_ROOT/build/images.env")" -ge 8 ] && while read -r n img _; do [ "$n" = model-serving-gpu ] && continue; "$DOCKER" image inspect "$img" >/dev/null 2>&1 || return 1; done < "$DEPLOY_ROOT/build/images.env"; }
if [ $REUSE = 1 ] && have_images; then
  # 재사용은 소스(커밋)와 의존 태그가 이미지 라벨과 같을 때만이다. 다른 이미지만 다시 빌드한다(판정 코드: verify_area.py stale_images). 판정이 안 되면 전부 다시 빌드한다
  if STALE=$("$VENV/bin/python" "$DEPLOY_ROOT/scripts/verify_area.py" --stale-images 2>/dev/null); then
    echo "  재사용: 낡은 이미지 = ${STALE:-없음}"
    [ -z "$STALE" ] || chk "빌드: 낡은 이미지만 ($STALE)" bash "$DEPLOY_ROOT/scripts/build-images.sh" $STALE
  else chk "빌드: 다섯 서비스 이미지 (낡은 이미지 판정 실패, 전부)" bash "$DEPLOY_ROOT/scripts/build-images.sh"; fi
else chk "빌드: 다섯 서비스 이미지 (현재 HEAD)" bash "$DEPLOY_ROOT/scripts/build-images.sh"; fi
abort_if_failed() { [ "$FAILS" = 0 ] || { echo "준비 단계가 실패해 중단한다"; exit 1; }; }
abort_if_failed
bash "$DEPLOY_ROOT/scripts/prepare-host.sh" wheels
grep -E '^(GATEWAY|REGISTRY|UTIL|POSTGRES)_IMAGE=' "$DEPLOY_ROOT/locks/images.lock" > "$DEPLOY_LOCK"
chk "레지스트리 기동(빈 포트 선택)" bash "$DEPLOY_ROOT/scripts/registry.sh" up
chk "publish: push + digest 잠금" bash "$DEPLOY_ROOT/scripts/publish-images.sh"
chk "compose가 digest로만 이미지를 참조" bash "$DEPLOY_ROOT/scripts/check-compose.sh"
chk "버전 표 드리프트 없음 (check-versions: lib.sh 표 == 형제 영역 표기)" bash "$DEPLOY_ROOT/scripts/check-versions.sh"
chk "check-versions 자기 점검" bash "$DEPLOY_ROOT/scripts/test-check-versions.sh"
chk "게이트웨이 인증 비밀 자체 점검 (계정·역할·기기 토큰, caddy validate)" bash "$DEPLOY_ROOT/scripts/test-gateway-auth.sh"
chk "images.env GPU 기록 자체 점검 (옛·없는 기록이 있어도 기본 publish 가 성공하고 정리가 GPU 이미지를 지우지 않는다)" bash "$DEPLOY_ROOT/scripts/test-images-env.sh"
chk "check-health 자체 점검 (실패 상태 파일·디스크 한계·감시 대상 응답을 읽는다)" bash "$DEPLOY_ROOT/scripts/test-check-health.sh"
chk "e2e 단언 자기 점검 (틀린 값이면 단언이 실패한다)" python3 "$DEPLOY_ROOT/scripts/test_e2e_asserts.py"
abort_if_failed
source "$DEPLOY_LOCK"; source "$DEPLOY_REGISTRY_ENV"   # export 하지 않는다(compose 변수 우선순위)
bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" "$SECRETS_DIR" >/dev/null

sect "단계 9 앞부분: Compose에서 이미지로 서비스가 뜬다"
chk "compose up --wait (digest 이미지, 읽기 전용 루트, cap_drop ALL)" bash "$DEPLOY_ROOT/scripts/up.sh" "$PROJECT"
abort_if_failed
port() { port_of "${PROJECT}-$1-1" 8080; }
PQA=$(port question-authoring); PGATE=$(port release-gate); POPS=$(port ops-feedback-ingest); PSURVEY=$(port survey-service); PMR=$(port model-registry); PMS=$(port model-serving); PGW=$(port gateway); PGWS=$(port_of "${PROJECT}-gateway-1" 8443)   # PGW: 평문(/healthz, 나머지는 308), PGWS: HTTPS
# gateway 의 내부 CA 루트(시험용 CA): 이 시험의 클라이언트(curl --cacert, e2e_steps)가 이것만 신뢰한다. 컨테이너가 방금 떴으므로 인증서가 만들어질 때까지 잠깐 기다린다
for _i in 1 2 3 4 5 6 7 8 9 10; do "$DOCKER" cp "${PROJECT}-gateway-1:/data/caddy/pki/authorities/local/root.crt" "$W/gateway-ca.crt" >/dev/null 2>&1 && break; sleep 1; done
[ -s "$W/gateway-ca.crt" ] || { echo "gateway 내부 CA 루트를 가져오지 못했다"; exit 1; }
GWCURL="curl --cacert $W/gateway-ca.crt"
echo "  Docker가 배정한 호스트 포트: gateway=$PGW(평문) gateway-tls=$PGWS qa=$PQA gate=$PGATE ops=$POPS survey=$PSURVEY model-registry=$PMR model-serving=$PMS"
getj() { curl -fsS -m 5 "http://127.0.0.1:$1$2"; }
for pair in "gateway:$PGW" "question-authoring:$PQA" "release-gate:$PGATE" "ops-feedback-ingest:$POPS" "model-registry:$PMR" "model-serving:$PMS" "survey-service:$PSURVEY"; do
  n=${pair%%:*}; p=${pair##*:}
  chk "/healthz $n" getj "$p" /healthz
  [ "$n" = survey-service ] && continue
  [ "$n" = gateway ] && continue   # gateway /readyz 는 survey-service 를 반영한다(아래에서 따로)
  chk "/readyz $n" getj "$p" /readyz
done
survey_noactive() { local o; o=$(curl -s -m 5 -w ' [%{http_code}]' "http://127.0.0.1:$PSURVEY/readyz"); echo "$o" | grep -q 'no_active_release' && echo "$o" | grep -q '\[503\]' && echo "활성 릴리스가 없어 503 no_active_release (정상: 아직 게이트에 PASS 릴리스가 없다)"; }
chk "/readyz survey-service: 활성 릴리스 전에는 503 no_active_release" survey_noactive
gw_mirrors() { local o; o=$(curl -s -m 5 -w ' [%{http_code}]' --cacert "$W/gateway-ca.crt" "https://127.0.0.1:$PGWS/readyz"); echo "$o" | grep -q '\[503\]' && ! echo "$o" | grep -q 'survey' && echo "gateway /readyz 는 survey-service 를 반영한다: 활성 릴리스 전 503, 본문에 내부 정보 없음 ($o)"; }
chk "/readyz gateway: 정적 200 이 아니라 환자 경로 survey-service 를 반영(활성 릴리스 전 503, 내부 정보 없음)" gw_mirrors
chk "/healthz gateway: 상류와 무관하게 200" getj "$PGW" /healthz
tls_checks() { # HTTPS 필수(D88/U5): 평문은 /healthz 만 답하고 나머지는 308 로 https 로 보낸다. HTTPS 는 시험용 CA 로 검증되고 HSTS 가 있다
  local r; r=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' "http://127.0.0.1:$PGW/v1/sessions"); echo "$r" | grep -q '^308 https://' || { echo "평문 요청이 https 로 308 이동하지 않는다: $r"; return 1; }
  [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PGW/staff/")" = 308 ] || { echo "평문 /staff/ 가 308 이 아니다"; return 1; }
  curl -s "http://127.0.0.1:$PGW/healthz" | grep -q '^ok' || { echo "평문 /healthz 가 ok 가 아니다"; return 1; }
  curl -s -o /dev/null "https://127.0.0.1:$PGWS/healthz" 2>/dev/null && { echo "시험용 CA 없이 https 가 검증을 통과했다(자체 서명 인증서를 신뢰하는 환경?)"; return 1; }
  local h; h=$($GWCURL -s -D - -o /dev/null "https://127.0.0.1:$PGWS/healthz") || { echo "시험용 CA 로 https 접속 실패"; return 1; }
  echo "$h" | grep -qi '^strict-transport-security: max-age=31536000' || { echo "HSTS 헤더가 없다"; return 1; }
  echo "$h" | grep -qi '^x-content-type-options: nosniff' || { echo "X-Content-Type-Options 가 없다"; return 1; }
  echo "$h" | grep -qi '^x-frame-options: DENY' || { echo "X-Frame-Options 가 없다"; return 1; }
  [ "$($GWCURL -s -o /dev/null -w '%{http_code}' "https://127.0.0.1:$PGWS/config.json")" = 404 ] || { echo "/config.json 이 막혀 있지 않다"; return 1; }
  echo "평문: /healthz 만 ok, 나머지 308 https; https: 시험용 CA 검증 통과, HSTS·nosniff·X-Frame-Options, /config.json 404"
}
chk "TLS(D88/U5): 평문은 308 https 로 이동, https 는 시험용 CA 로 검증되고 HSTS·보안 헤더가 있다" tls_checks
chk "운영 compose.yaml/config 에 시험용 정책·실행기·대역이 없다" bash -c "! grep -rEn --exclude=verify-areas.yaml 'test-gate|test_gate|smoke_fakes|GATE_POLICY_FILE|GATE_ALLOW_TEST|FAKE_RISK_PHRASE' $DEPLOY_ROOT/compose.yaml $DEPLOY_ROOT/config/ | grep -v '^[^:]*:[0-9]*:#'"
no_auto_pass() { getj "$PGATE" /readyz | python3 -c "import sys,json;d=json.load(sys.stdin);print('gate /readyz',{k:d.get(k) for k in ('judging','awaiting_approval','gate_policy_version')});sys.exit(0 if d.get('judging')=='enabled' else 1)"; }
chk "gate /readyz: 판정 켜짐(I1·I3 연결), 정책 파일 없이 기본 정책, 승인 대기 개수 항목" no_auto_pass
chk "gateway: /v1/turns -> 404, /staff/ 와 직원 API 는 인증 없이 401, /v1/activate 는 인증 없이 401, 키오스크 경로는 기기 토큰 없이 401(D85)" bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST --cacert $W/gateway-ca.crt https://127.0.0.1:$PGWS/v1/turns)\" = 404 ] && [ \"\$(curl -s -o /dev/null -w '%{http_code}' --cacert $W/gateway-ca.crt https://127.0.0.1:$PGWS/staff/)\" = 401 ] && [ \"\$(curl -s -o /dev/null -w '%{http_code}' --cacert $W/gateway-ca.crt https://127.0.0.1:$PGWS/admin/)\" = 401 ] && [ \"\$(curl -s -o /dev/null -w '%{http_code}' --cacert $W/gateway-ca.crt https://127.0.0.1:$PGWS/v1/submissions)\" = 401 ] && [ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST -d '{}' --cacert $W/gateway-ca.crt https://127.0.0.1:$PGWS/v1/activate)\" = 401 ] && [ \"\$(curl -s -o /dev/null -w '%{http_code}' --cacert $W/gateway-ca.crt https://127.0.0.1:$PGWS/v1/cases)\" = 401 ] && [ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST -d '{}' --cacert $W/gateway-ca.crt https://127.0.0.1:$PGWS/v1/traces)\" = 404 ] && [ \"\$(curl -s -o /dev/null -w '%{http_code}' --cacert $W/gateway-ca.crt https://127.0.0.1:$PGWS/v1/staff/alerts)\" = 401 ] && [ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST --cacert $W/gateway-ca.crt https://127.0.0.1:$PGWS/v1/sessions/x/intervention)\" = 401 ] && [ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST -d '{}' --cacert $W/gateway-ca.crt https://127.0.0.1:$PGWS/v1/sessions)\" = 401 ]"
reach() { "$DOCKER" exec "${PROJECT}-$1-1" python -c "import urllib.request;urllib.request.urlopen('http://$2:8080/healthz',timeout=3)" >/dev/null 2>&1; }
blocked() { ! reach "$@"; }
chk "도달: survey-service -> ops-feedback-ingest (serving, I6)" reach survey-service ops-feedback-ingest
chk "도달: survey-service -> release-gate (serving, I4)" reach survey-service release-gate
chk "도달: release-gate -> question-authoring (release, I1)" reach release-gate question-authoring
chk "도달: release-gate -> model-registry (release, I3)" reach release-gate model-registry
chk "차단: survey-service -> question-authoring" blocked survey-service question-authoring
chk "차단: survey-service -> model-registry" blocked survey-service model-registry
chk "차단: question-authoring -> survey-service" blocked question-authoring survey-service
chk "차단: model-registry -> model-serving" blocked model-registry model-serving
chk "차단: question-authoring -> model-serving" blocked question-authoring model-serving
net_is() { # net_is <네트워크> <컨테이너...>: 네트워크의 구성원이 정확히 그 컨테이너들이다
  local n=$1; shift; local got want
  got=$("$DOCKER" network inspect "${PROJECT}_$n" --format '{{range .Containers}}{{.Name}}{{"\n"}}{{end}}' | sed '/^$/d' | sort | tr '\n' ' ')
  want=$(printf '%s\n' "$@" | sort | tr '\n' ' ')
  [ "$got" = "$want" ] || { echo "구성원 불일치: $n"; return 1; }
}
for pair in "db-survey:survey-service" "db-qa:question-authoring" "db-ops:ops-feedback-ingest" "db-gate:release-gate"; do
  chk "db 네트워크 ${pair%%:*} 에는 postgres 와 ${pair##*:} 만 있다(postgres 클라이언트끼리 닿지 않는다)" net_is "${pair%%:*}" "${PROJECT}-postgres-1" "${PROJECT}-${pair##*:}-1"
done
tcp() { "$DOCKER" exec "${PROJECT}-$1-1" python -c "import socket;socket.create_connection(('$2',$3),timeout=3)" >/dev/null 2>&1; }
for s in survey-service question-authoring ops-feedback-ingest release-gate; do chk "도달: $s -> postgres:5432 (db 네트워크)" tcp $s postgres 5432; done
tcp_blocked() { ! tcp "$@"; }
chk "차단: model-registry -> postgres" tcp_blocked model-registry postgres 5432
chk "차단: 호스트에 postgres 포트 게시 없음" bash -c "[ -z \"\$($DOCKER port ${PROJECT}-postgres-1)\" ]"
chk "도달: survey-service -> model-serving (serving, I9)" reach survey-service model-serving
chk "도달: model-serving -> release-gate (serving, I4 번들 읽기)" reach model-serving release-gate
chk "차단: model-serving -> question-authoring" blocked model-serving question-authoring
chk "도달: question-authoring -> ops-feedback-ingest (authoring, 개선 신호가 I7을 읽음)" reach question-authoring ops-feedback-ingest
chk "차단: ops-feedback-ingest -> model-registry" blocked ops-feedback-ingest model-registry
noegress() { ! "$DOCKER" exec "${PROJECT}-release-gate-1" python -c "import urllib.request;urllib.request.urlopen('http://1.1.1.1',timeout=3)" >/dev/null 2>&1; }
chk "내부 네트워크 밖으로 나가지 못함(release-gate -> 외부 인터넷)" noegress
chk "보존 정리 잡이 Compose 에서 실행된다: release-gate prune --dry-run(멱등, release-gate CR-0008)" bash "$DEPLOY_ROOT/scripts/run-job.sh" job-release-gate-prune python -m release_gate prune --dry-run
chk "보존 정리 잡이 Compose 에서 실행된다: survey purge(SURVEY_SESSION_RETENTION_DAYS=90, 지운 개수 JSON)" bash -c "bash $DEPLOY_ROOT/scripts/run-job.sh job-survey-purge | tail -1 | python3 -c 'import json,sys;json.loads(sys.stdin.read());print(\"purge 출력이 JSON 한 줄\")'"
chk "보존 정리 잡이 Compose 에서 실행된다: question-authoring purge(멱등; 출력 한 줄은 지운 개수 요약)" bash -c "set -o pipefail; bash $DEPLOY_ROOT/scripts/run-job.sh job-question-authoring-purge | tail -1 | grep -q ."
chk "컨테이너 격리 실제 확인(check-containers: 비루트·읽기 전용·cap_drop ALL·no-new-privileges·자원 한도·로그 회전)" bash "$DEPLOY_ROOT/scripts/check-containers.sh" "$PROJECT"
nonroot() { [ "$("$DOCKER" exec "${PROJECT}-$1-1" id -u | tr -d '\r')" != 0 ]; }
bydigest() { "$DOCKER" inspect "${PROJECT}-$1-1" --format '{{.Config.Image}}' | tr -d '\r' | grep -E '@sha256:[0-9a-f]{64}$'; }
labels6() { local L; L=$("$DOCKER" image inspect "$1" --format '{{json .Config.Labels}}' | tr -d '\r'); for k in io.openit.service io.openit.revision io.openit.contracts.boundary io.openit.contracts.survey-schema io.openit.turn-engine io.openit.model-runtime; do echo "$L" | grep -q "\"$k\"" || { echo "라벨 누락 $k"; return 1; }; done; echo "$L" | cut -c1-230; }
for s in survey-service question-authoring ops-feedback-ingest release-gate model-registry model-serving kiosk-frontend admin-console; do
  chk "비root 실행 $s" nonroot "$s"
  chk "컨테이너가 digest로 만들어짐 $s" bydigest "$s"
done
for pair in "survey-service:$SURVEY_SERVICE_DIGEST" "question-authoring:$QUESTION_AUTHORING_DIGEST" "ops-feedback:$OPS_FEEDBACK_DIGEST" "release-gate:$RELEASE_GATE_DIGEST" "model-registry:$MODEL_REGISTRY_DIGEST" "model-serving:$MODEL_SERVING_DIGEST" "admin-console:$ADMIN_CONSOLE_DIGEST"; do
  chk "이미지 라벨 6개(io.openit.*) ${pair%%:*}" labels6 "$DEPLOY_REGISTRY/openit/${pair%%:*}@${pair#*:}"
done

labels_kiosk() { local L; L=$("$DOCKER" image inspect "$1" --format '{{json .Config.Labels}}' | tr -d '\r'); for k in io.openit.service io.openit.revision io.openit.contracts.boundary io.openit.contracts.survey-schema io.openit.app-version; do echo "$L" | grep -q "\"$k\":\"[^\"]\+\"" || { echo "라벨 누락/빈값 $k"; return 1; }; done; echo "$L" | grep -q '"unknown"' && { echo "unknown 라벨이 있다"; return 1; }; echo "$L" | cut -c1-230; }
chk "이미지 라벨(io.openit.* + app-version, unknown 없음) kiosk-frontend" labels_kiosk "$DEPLOY_REGISTRY/openit/kiosk-frontend@$KIOSK_FRONTEND_DIGEST"
langgraph_label() { local v; v=$("$DOCKER" image inspect "$DEPLOY_REGISTRY/openit/survey-service@$SURVEY_SERVICE_DIGEST" --format '{{index .Config.Labels "io.openit.langgraph"}}' | tr -d '\r'); [ -n "$v" ] && [ "$v" != unknown ] && echo "io.openit.langgraph=$v"; }
chk "survey-service 이미지의 io.openit.langgraph 라벨이 unknown이 아니다" langgraph_label
sect "단계 1~8 (실제 서비스의 HTTP로 잇는다)"
IMAGES="{\"survey-service\":\"$DEPLOY_REGISTRY/openit/survey-service@$SURVEY_SERVICE_DIGEST\",\"question-authoring\":\"$DEPLOY_REGISTRY/openit/question-authoring@$QUESTION_AUTHORING_DIGEST\",\"ops-feedback\":\"$DEPLOY_REGISTRY/openit/ops-feedback@$OPS_FEEDBACK_DIGEST\"}"
PORTS="{\"qa\":$PQA,\"gate\":$PGATE,\"ops\":$POPS,\"survey\":$PSURVEY,\"mr\":$PMR,\"gw\":$PGWS,\"ms\":$PMS}"
"$VENV/bin/python" "$DEPLOY_ROOT/scripts/e2e_steps.py" --project "$PROJECT" --secrets "$SECRETS_DIR" --ports "$PORTS" --images "$IMAGES" --docker "$DOCKER" --root "$DEPLOY_ROOT" --work "$W/work" --gw-ca "$W/gateway-ca.crt" --run-id e2e-test ${ONLY:+--only "$ONLY"} | tee "$W/steps.log"
STEPS_RC=${PIPESTATUS[0]}
[ "$STEPS_RC" = 0 ] && res "단계 1~8 (REAL/TEST-SUB 항목의 스키마·해시 검증)" PASS "BLOCKED 항목은 아래 요약과 docs/change-requests 참고" || res "단계 1~8" FAIL "e2e_steps.py 종료 코드 $STEPS_RC"
chk "비밀 노출 점검: 환경 변수·inspect·exec env 에 secrets 값 없음 (check-secrets-hidden)" bash "$DEPLOY_ROOT/scripts/check-secrets-hidden.sh" "$PROJECT"
chk "check-secrets-hidden 자기 점검(노출 컨테이너는 실패, 파일 비밀은 통과)" bash "$DEPLOY_ROOT/scripts/test-check-secrets-hidden.sh"

if [ "$FAST" = 0 ]; then   # --fast 에서는 아래 세 구간(스케줄러, 백업·복구, 롤백)을 건너뛴다
sect "단계 9: 주기 잡 스케줄러 (D39)"
chk "잡 엔트리포인트가 Compose 안에서 이미지·볼륨·네트워크로 실행된다(ops_feedback.job --help)" bash "$DEPLOY_ROOT/scripts/run-job.sh" job-ops-feedback python -m ops_feedback.job --help
chk "수집기 잡 엔트리포인트(release_gate collect, 단계 4에서 실제 실행됨)" bash -c "grep -a -q 'job-release-gate-collect\|수집기 run-once' $W/steps.log"
chk "잡 설정이 없으면 run-job 은 거부(종료 코드 2)" bash -c "OPS_JOB_CONFIG=/nonexistent/job.yaml bash $DEPLOY_ROOT/scripts/run-job.sh job-ops-feedback; [ \$? = 2 ]"
mkdir -p "$W/sched"
cat > "$W/sched/jobs.yaml" <<YAML
jobs:
  - {name: test-fast, where: serving, command: ["bash","-c","echo run >> $W/sched/ran.txt"], interval_seconds: 3}
  - {name: test-undecided, where: serving, command: ["bash","-c","echo SHOULD-NOT-RUN >> $W/sched/ran.txt"], interval_seconds: null}
  - {name: test-gpu, where: gpu-external, command: ["bash","-c","echo SHOULD-NOT-RUN >> $W/sched/ran.txt"], interval_seconds: 3}
YAML
SCHED="$VENV/bin/python $DEPLOY_ROOT/scripts/scheduler.py --config $W/sched/jobs.yaml --state $W/sched/st.json"
$SCHED tick >/dev/null; $SCHED tick >/dev/null; sleep 3.5; $SCHED tick >/dev/null
chk "스케줄러: 기한이 되면 실행하고 기한 전 tick은 아무것도 안 한다(3초 주기, 3번 tick -> 2번 실행), 주기 미정·GPU 밖 잡은 실행 안 함" bash -c "[ \"\$(cat $W/sched/ran.txt)\" = \"\$(printf 'run\nrun')\" ] && echo '실행 2회, SHOULD-NOT-RUN 없음'"
# 단계 5d/5q/5w 가 gateway 를 다시 시작하면 Docker 가 배정한 호스트 포트가 바뀐다: 감시 대상 주소는 지금 포트를 다시 읽어 만든다(평문 /healthz 와 HTTPS /healthz + 시험용 CA)
PGW=$(port gateway); PGWS=$(port_of "${PROJECT}-gateway-1" 8443)
printf 'targets:\n  - {name: gateway-healthz-plain, url: "http://127.0.0.1:%s/healthz", expect_status: 200}\n  - {name: gateway-healthz-https, url: "https://127.0.0.1:%s/healthz", expect_status: 200, ca_file: "%s"}\n' "$PGW" "$PGWS" "$W/gateway-ca.crt" > "$W/sched/monitor.yaml"
chk "check-health: 스케줄러 상태 파일·디스크·외부 감시 대상(gateway /healthz 평문·HTTPS)을 읽어 모두 OK(종료 0)" bash "$DEPLOY_ROOT/scripts/check-health.sh" --jobs "$W/sched/jobs.yaml" --scheduler-state "$W/sched/st.json" --monitor "$W/sched/monitor.yaml" --disk-path "$W" --skip-backup
chk "config/jobs.yaml: GPU 잡 3개는 gpu-external(이 Compose에 없음)" bash -c "[ \$(grep -c 'where: gpu-external' $DEPLOY_ROOT/config/jobs.yaml) = 3 ] && ! grep -E '^  (job-)?(synthetic-data|model-lab|gate-worker)' $DEPLOY_ROOT/compose.yaml"

sect "단계 9: 백업과 복구 (평문 모드 BACKUP_ALLOW_PLAINTEXT=1 은 **시험 전용**이다. 암호화 경로(gpg 공개키)는 scripts/test-backup.sh 가 시험한다. age 분기는 age 가 없어 미실행)"
chk "설정 파일이 없으면 백업 거부(종료 코드 2)" bash -c "BACKUP_CONFIG=$W/none.env bash $DEPLOY_ROOT/scripts/backup.sh; [ \$? = 2 ]"
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=\n' "$W/backups" > "$W/backup-bad.env"
chk "보관 기간이 비어 있으면 백업 거부" bash -c "BACKUP_CONFIG=$W/backup-bad.env bash $DEPLOY_ROOT/scripts/backup.sh; [ \$? = 2 ]"
printf '# 시험 전용 값(사용자 결정이 아니다)\nBACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=7\nBACKUP_ALLOW_PLAINTEXT=1\n' "$W/backups" > "$W/backup-test.env"
export BACKUP_CONFIG="$W/backup-test.env"
# 서비스는 모두 멈추고 postgres 만 남긴다(pg_dump 는 서버가 떠 있어야 한다). 파일 저장소는 번들뿐(gate-data, models-data), 데이터베이스는 PostgreSQL(D85)
dc "$PROJECT" --profile jobs stop $(dc "$PROJECT" --profile jobs config --services | grep -vx postgres | tr '\n' ' ') >/dev/null 2>&1
STORES="gate-data models-data"; PGDBS="survey qa ops_log ops_failure gate"
for s in $STORES; do bash "$DEPLOY_ROOT/scripts/fingerprint.sh" $s > "$W/fp-before-$s.json"; done
for d in $PGDBS; do bash "$DEPLOY_ROOT/scripts/pg-fingerprint.sh" $d > "$W/fp-before-pg-$d.json"; done
mkdir -p "$W/backups/gate-data/20200101T000000Z"; touch -d '2020-01-01' "$W/backups/gate-data/20200101T000000Z"
chk "백업(파일 저장소 2개, SQLite backup API + 해시 MANIFEST)" bash "$DEPLOY_ROOT/scripts/backup.sh" $STORES
chk "백업(PostgreSQL 5개 데이터베이스, pg_dump -Fc + 해시 MANIFEST)" bash "$DEPLOY_ROOT/scripts/pg-backup.sh" $PGDBS
chk "보관 기간(7일)이 지난 스냅샷만 삭제" bash -c "[ ! -d $W/backups/gate-data/20200101T000000Z ] && [ \$(ls $W/backups/gate-data | wc -l) = 1 ]"
dc "$PROJECT" down >/dev/null 2>&1
chk "볼륨 삭제(데이터를 실제로 지운다: 파일 저장소와 pg-data)" bash -c "$DOCKER volume rm ${PROJECT}_survey-data ${PROJECT}_gate-data ${PROJECT}_models-data ${PROJECT}_pg-data >/dev/null"
dc "$PROJECT" up -d --wait --wait-timeout 120 postgres >/dev/null 2>&1   # 빈 볼륨에서 초기화 스크립트가 데이터베이스·계정을 다시 만든다
chk "지운 뒤 지문이 달라졌다(빈 볼륨, 빈 데이터베이스)" bash -c "[ \"\$(bash $DEPLOY_ROOT/scripts/fingerprint.sh gate-data)\" != \"\$(cat $W/fp-before-gate-data.json)\" ] && [ \"\$(bash $DEPLOY_ROOT/scripts/pg-fingerprint.sh survey)\" != \"\$(cat $W/fp-before-pg-survey.json)\" ]"
for s in $STORES; do chk "복구 $s" bash -c "SN=\$(ls -d $W/backups/$s/2* | tail -1); [ -n \"\$SN\" ] && bash $DEPLOY_ROOT/scripts/restore.sh $s \"\$SN\" --yes"; done
for d in $PGDBS; do chk "복구 pg-$d" bash -c "SN=\$(ls -d $W/backups/pg-$d/2* | tail -1); [ -n \"\$SN\" ] && bash $DEPLOY_ROOT/scripts/pg-restore.sh $d \"\$SN\" --yes"; done
for s in $STORES; do chk "복구 후 지문 일치 $s" bash -c "[ \"\$(bash $DEPLOY_ROOT/scripts/fingerprint.sh $s)\" = \"\$(cat $W/fp-before-$s.json)\" ]"; done
for d in $PGDBS; do chk "복구 후 지문 일치 pg-$d" bash -c "[ \"\$(bash $DEPLOY_ROOT/scripts/pg-fingerprint.sh $d)\" = \"\$(cat $W/fp-before-pg-$d.json)\" ]"; done
chk "복구 후 서비스 기동" bash "$DEPLOY_ROOT/scripts/up.sh" "$PROJECT"
PQA=$(port question-authoring); POPS=$(port ops-feedback-ingest); PGATE=$(port release-gate); PMR=$(port model-registry); PSURVEY=$(port survey-service)
PORTS="{\"qa\":$PQA,\"gate\":$PGATE,\"ops\":$POPS,\"survey\":$PSURVEY,\"mr\":$PMR}"
chk "복구한 데이터를 실제 서비스의 HTTP로 다시 읽는다(문항 2버전·해시, 같은 Trace 재전송=DUPLICATE, 모델 패키지·어댑터 해시, 활성 포인터)" \
  "$VENV/bin/python" "$DEPLOY_ROOT/scripts/e2e_verify_restore.py" --secrets "$SECRETS_DIR" --ports "$PORTS" --work "$W/work" --run-id e2e-test

sect "단계 9: digest 잠금으로 코드 축 롤백"
OLD_REF=$("$DOCKER" inspect "${PROJECT}-survey-service-1" --format '{{.Config.Image}}' | tr -d '\r')
cp "$DEPLOY_ROOT/build/images.env" "$W/images.env.bak"
chk "새 버전 빌드(시험: COMMIT 라벨에 -test2)" env BUILD_SUFFIX=-test2 bash "$DEPLOY_ROOT/scripts/build-images.sh" survey-service
chk "새 버전 publish -> 잠금 갱신(이전 잠금은 history에 보관)" bash "$DEPLOY_ROOT/scripts/publish-images.sh" survey-service
cp "$W/images.env.bak" "$DEPLOY_ROOT/build/images.env"   # 시험용 -test2 빌드가 build/images.env 에 남지 않게 한다
chk "새 잠금으로 적용 -> survey-service가 새 digest 이미지로 교체" bash -c "bash $DEPLOY_ROOT/scripts/up.sh $PROJECT >/dev/null && [ \"\$($DOCKER inspect ${PROJECT}-survey-service-1 --format '{{.Config.Image}}' | tr -d '\r')\" != \"$OLD_REF\" ]"
chk "롤백: 잠금을 이전 것으로 되돌리고 적용 -> 이전 digest 이미지로 복귀" bash -c "bash $DEPLOY_ROOT/scripts/rollback.sh $PROJECT >/dev/null && [ \"\$($DOCKER inspect ${PROJECT}-survey-service-1 --format '{{.Config.Image}}' | tr -d '\r')\" = \"$OLD_REF\" ]"
SP=$(port survey-service)
survey_ready_after() { for i in $(seq 1 40); do o=$(curl -s -m 5 "http://127.0.0.1:$SP/readyz"); echo "$o" | grep -q '"ready": true' && { echo "$o" | cut -c1-120; return 0; }; sleep 2; done; echo "$o"; return 1; }
chk "롤백 뒤 survey-service /readyz 200 (복구한 포인터의 릴리스를 HTTP로 다시 적재)" survey_ready_after

fi
sect ""
{
echo; echo "============================ 요약 ============================"
if [ -f "$W/steps.log" ]; then sed -n '/== 요약 (단계 1~8)/,$p' "$W/steps.log"; fi
[ "$FAST" = 1 ] && echo "-- FAST 모드: 생략한 구간 = 단계 9 스케줄러(D39), 백업·복구, digest 잠금 코드 축 롤백. 전체 합격 아님"
echo "-- 9단계 및 준비 검사"
printf '   PASS %s / FAIL %s\n' "$(printf '%s\n' "${RESULT[@]}" | grep -c '|PASS|')" "$FAILS"
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
[ "$FAILS" = 0 ] && [ "$REC_RC" = 0 ]; exit $?
