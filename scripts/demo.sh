#!/usr/bin/env bash
# 사람이 화면을 직접 눌러 볼 수 있는 데모 환경. 상시 구성(`deploy` 프로젝트)과 따로, 같은 서버에서 함께 돌 수 있다.
#   scripts/demo.sh up [--stop-before-approval] [--rebuild] [--external-inference <URL>]   데모 구성을 띄우고 시험용 릴리스를 만들어 활성화한다
#   scripts/demo.sh activate                                   (--stop-before-approval 로 띄운 뒤) /admin/ 에서 승인한 제출의 릴리스를 활성화한다
#   scripts/demo.sh status | down | reset [--stop-before-approval]
# 이 데이터는 시험용 대체다: 가짜 모델(fake 백엔드), 시험용 어댑터·평가 보고서, 시험용 승인자(스크립트). E2E와 같은 시험 구성(compose.test.yaml)을 쓴다.
# 표준 `docker`만 쓴다. 컨테이너의 호스트 포트는 Docker가 배정한다(고정 포트 없음). 임시 레지스트리도 빈 포트를 고른다.
# 환경 변수: DEMO_PROJECT(기본 deploy-demo, 반드시 deploy-demo 로 시작), DEMO_BIND(gateway 호스트 바인드, 기본 127.0.0.1; 다른 PC에서 보려면 0.0.0.0 -- HTTP·기본 인증이라 시험 때만),
#           DEMO_REGISTRY_BIND(레지스트리 바인드, 기본 127.0.0.1; 데몬이 닿지 못하면 사용자가 0.0.0.0 으로 바꾼다 -- 끝나면 down).
set -uo pipefail
DEPLOY_NO_DOCKER=1   # 사용법·인자 검사는 Docker 없이도 동작한다. 데몬 감지는 그 뒤에 한다
source "$(dirname "$0")/lib.sh"
CMD=${1:-}; shift || true
STOP=0; REBUILD=0; EXT=""
while [ $# -gt 0 ]; do case "$1" in
  --stop-before-approval) STOP=1; shift;; --rebuild) REBUILD=1; shift;;
  --external-inference) [ $# -ge 2 ] || die "--external-inference 에는 URL이 필요하다"; EXT=$2; shift 2;;
  --external-inference=*) EXT=${1#*=}; shift;;
  *) die "알 수 없는 인자: $1";; esac; done
P=${DEMO_PROJECT:-deploy-demo}
case "$P" in deploy-demo*) ;; *) die "DEMO_PROJECT 는 deploy-demo 로 시작해야 한다 (상시 구성과 섞이지 않게)";; esac
W="$DEPLOY_ROOT/state/demo"
usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; }

env_demo() { # 데모 프로젝트의 환경 변수(모든 하위 스크립트가 같은 값을 본다)
  export DEPLOY_LOCK="$W/images.lock" DEPLOY_REGISTRY_ENV="$W/registry.env" DEPLOY_PROJECT="$P" DEPLOY_SKIP_DOCTOR=1
  export REGISTRY_PROJECT="$P-reg" REGISTRY_HOST_BIND="${DEMO_REGISTRY_BIND:-127.0.0.1}" REGISTRY_HOST_PORT=
  export SECRETS_DIR="$W/secrets" COMPOSE_EXTRA="$DEPLOY_ROOT/compose.test.yaml" GATEWAY_BIND="${DEMO_BIND:-127.0.0.1}" GATEWAY_PORT=
  export OPS_JOB_CONFIG="$DEPLOY_ROOT/test/ops-job/test-ops-job.yaml"
  # 외부 추론 서버(D72): up 때 기록한 주소를 이후 명령(activate/status/down)도 쓴다. 토큰 값은 기록하지 않고 파일 경로만 둔다
  if [ -n "$EXT" ]; then external_inference_setup "$EXT"; printf '%s\n%s\n' "$EXT" "$INFERENCE_TOKEN_FILE" > "$W/external-inference"
  elif [ -f "$W/external-inference" ]; then
    EXT=$(sed -n 1p "$W/external-inference"); export INFERENCE_TOKEN_FILE; INFERENCE_TOKEN_FILE=$(sed -n 2p "$W/external-inference"); external_inference_setup "$EXT"
  fi
}
ports_json() {
  local pp; pp() { port_of "$P-$1-1" 8080; }
  local ms; if [ -n "$EXT" ]; then ms=0; else ms=$(pp model-serving); fi
  echo "{\"qa\":$(pp question-authoring),\"gate\":$(pp release-gate),\"ops\":$(pp ops-feedback-ingest),\"survey\":$(pp survey-service),\"mr\":$(pp model-registry),\"gw\":$(pp gateway),\"ms\":$ms}"
}
run_steps() { # run_steps <--only 목록> [추가 인자]
  local only=$1; shift
  local msx=(); [ -z "$EXT" ] || msx=(--ms-url "$EXT" --ms-token-file "$INFERENCE_TOKEN_FILE")
  local img; img=$( set -a; . "$DEPLOY_LOCK"; . "$DEPLOY_REGISTRY_ENV"; set +a
    echo "{\"survey-service\":\"$DEPLOY_REGISTRY/openit/survey-service@$SURVEY_SERVICE_DIGEST\",\"question-authoring\":\"$DEPLOY_REGISTRY/openit/question-authoring@$QUESTION_AUTHORING_DIGEST\",\"ops-feedback\":\"$DEPLOY_REGISTRY/openit/ops-feedback@$OPS_FEEDBACK_DIGEST\"}" )
  "$VENV/bin/python" "$DEPLOY_ROOT/scripts/e2e_steps.py" --project "$P" --secrets "$SECRETS_DIR" --ports "$(ports_json)" --images "$img" \
    --docker "$DOCKER" --root "$DEPLOY_ROOT" --work "$W/work" --run-id demo-test --only "$only" \
    "${msx[@]}" "$@"
}
risk_phrase() { sed -n "s/^[[:space:]]*MODEL_RUNTIME_FAKE_RISK_PHRASE:[[:space:]]*['\"]\{0,1\}\([^'\"#]*\)['\"]\{0,1\}.*/\1/p" "$DEPLOY_ROOT/compose.test.yaml" | head -1 | sed 's/[[:space:]]*$//'; }

guide() {
  local gw; gw=$(port_of "$P-gateway-1" 8080)
  local host=127.0.0.1; [ "${DEMO_BIND:-127.0.0.1}" != 127.0.0.1 ] && host="<서버 주소>"
  cat <<GUIDE

==================== 데모 접속 안내 ====================
 !! 이 데이터는 시험용 대체(가짜 모델, 시험용 승인자)입니다. 실제 모델·실제 승인이 아닙니다. !!

 주소 (Docker가 배정한 포트): http://$host:$gw
   키오스크 화면      http://$host:$gw/
   직원 콘솔          http://$host:$gw/staff/      계정 staff
   승인·실패 사례 검토 http://$host:$gw/admin/      승인자 계정 trainer-e2e / 검토자 계정 reviewer-e2e
 (HTTP·기본 인증이라 시험용이다. 원격 서버면: ssh -L $gw:127.0.0.1:$gw <서버>  로 터널을 열고 http://127.0.0.1:$gw 로 본다)

 암호: 값은 출력하지 않는다. 비밀 파일을 열어 본다 (권한 600, 저장소 밖 $W/secrets):
   staff            $W/secrets/tokens/staff-console-password
   trainer-e2e      $W/secrets/tokens/admin-console-password
   reviewer-e2e     $W/secrets/tokens/reviewer-console-password
   예: cat $W/secrets/tokens/staff-console-password

 $( [ -n "$EXT" ] && echo "추론 서버: 외부($EXT). 이 구성의 model-serving 은 꺼져 있다. 아래 위험 문구는 그 서버가 시험 스위치(MODEL_RUNTIME_FAKE_RISK_PHRASE)로 떠 있을 때만 듣는다" )
 키오스크에서 위험 정지를 시험하려면 이 문구를 말하거나(입력) 한다:  $(risk_phrase)
   (시험 구성의 가짜 모델에만 있는 문구다. 정지되면 직원 콘솔(/staff/)에 알림이 뜨고 RESUME/END 로 풀 수 있다)
 승인 화면: 승인 대기 시험 제출이 있다$( [ $STOP = 1 ] && echo " (--stop-before-approval: 문항 세트 v1·v2 모두 대기. 승인한 뒤 scripts/demo.sh activate)" || echo " (보지 못한 문항 세트 제출 1건. v1·v2는 스크립트가 시험용 승인자로 이미 승인·활성화)")
 실패 사례 검토 화면: 시험 사례 1건(PENDING). /admin/ 의 검토 메뉴(검토자 계정)

 끄기: scripts/demo.sh down    (데모 프로젝트 $P 의 컨테이너·네트워크·볼륨·임시 레지스트리·state/demo 만 지운다)
=========================================================
GUIDE
}

case "$CMD" in up|activate|status|down|reset) detect_docker;; esac
case "$CMD" in
  up)
    [ -d "$W" ] && [ -f "$W/registry.env" ] && die "이미 데모 상태가 있다 ($W). scripts/demo.sh down 또는 reset"
    bash "$DEPLOY_ROOT/scripts/doctor.sh" || exit 1
    mkdir -p "$W"; env_demo
    [ -z "$EXT" ] || bash "$DEPLOY_ROOT/scripts/doctor.sh" --up --inference "$EXT" || { rm -f "$W/external-inference"; exit 1; }
    bash "$DEPLOY_ROOT/scripts/prepare-host.sh" venv || die "호스트 가상환경 준비 실패"
    have_images() { [ -f "$DEPLOY_ROOT/build/images.env" ] && [ "$(wc -l < "$DEPLOY_ROOT/build/images.env")" -ge 8 ] && while read -r _ img _; do "$DOCKER" image inspect "$img" >/dev/null 2>&1 || return 1; done < "$DEPLOY_ROOT/build/images.env"; }
    if [ $REBUILD = 1 ] || ! have_images; then echo "== 이미지 빌드(현재 HEAD)"; bash "$DEPLOY_ROOT/scripts/build-images.sh" || die "이미지 빌드 실패"; fi
    bash "$DEPLOY_ROOT/scripts/prepare-host.sh" wheels || die "호스트 클라이언트 준비 실패"
    grep -E '^(GATEWAY|REGISTRY|UTIL)_IMAGE=' "$DEPLOY_ROOT/locks/images.lock" > "$DEPLOY_LOCK"
    echo "== 임시 레지스트리와 digest 잠금(이 데모 전용)"
    bash "$DEPLOY_ROOT/scripts/registry.sh" up || die "레지스트리 기동 실패 (데몬이 닿지 못하면 DEMO_REGISTRY_BIND=0.0.0.0 으로 다시, 끝나면 down)"
    bash "$DEPLOY_ROOT/scripts/publish-images.sh" || die "게시 실패"
    bash "$DEPLOY_ROOT/scripts/check-compose.sh" || exit 1
    bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" "$SECRETS_DIR" >/dev/null || die "비밀 생성 실패"
    echo "== 데모 프로젝트 $P 기동 (compose.yaml + compose.test.yaml, 호스트 포트는 Docker 배정)"
    bash "$DEPLOY_ROOT/scripts/up.sh" "$P" || die "기동 실패. 원인: docker compose -p $P logs"
    echo "== 시험용 릴리스 만들기(E2E 단계 코드 재사용): 문항 세트 등록 -> 데이터셋 -> 시험용 어댑터·평가 보고서 -> 후보 수집·자동 검사 $( [ $STOP = 1 ] && echo '(승인 전에 멈춤)' || echo '-> 시험용 승인자 승인 -> 활성화 -> 실패 사례')"
    if [ $STOP = 1 ]; then run_steps "1,2,3,demo4" --demo-stop || die "데모 릴리스 준비 실패"
    else run_steps "1,2,3,demo4,6" || die "데모 릴리스 준비 실패"; fi
    guide ;;
  activate)
    [ -f "$W/registry.env" ] || die "데모가 떠 있지 않다 (scripts/demo.sh up)"
    env_demo; run_steps "demo_activate,6" || die "활성화 실패(/admin/ 에서 먼저 승인했는지 확인)"
    guide ;;
  status)
    [ -f "$W/registry.env" ] || { echo "데모가 떠 있지 않다."; exit 0; }
    exec bash "$DEPLOY_ROOT/scripts/status.sh" "$P" "$P-reg" ;;
  down)
    env_demo
    echo "== 데모 프로젝트 $P 제거 (컨테이너·네트워크·볼륨)"
    dc "$P" --profile jobs down -v --remove-orphans 2>&1 | tail -3
    bash "$DEPLOY_ROOT/scripts/registry.sh" down -v 2>&1 | tail -1
    for i in $("$DOCKER" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -E '^127\.0\.0\.1:[0-9]+/openit/'); do "$DOCKER" rmi -f "$i" >/dev/null 2>&1; done
    [ -n "$W" ] && [ "$W" = "$DEPLOY_ROOT/state/demo" ] && rm -rf "$W"
    echo "정리 완료 ($P 로 시작하는 자원과 state/demo). 상시 구성과 로컬 deploy-build 이미지는 그대로다." ;;
  reset)
    "$0" down || true
    exec "$0" up $( [ $STOP = 1 ] && echo --stop-before-approval ) ;;
  ""|-h|--help|help) usage; [ -z "$CMD" ] && exit 2 || exit 0 ;;
  *) usage >&2; exit 2 ;;
esac
