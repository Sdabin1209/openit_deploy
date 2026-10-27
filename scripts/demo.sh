#!/usr/bin/env bash
# 사람이 화면을 직접 눌러 볼 수 있는 데모 환경. 상시 구성(`deploy` 프로젝트)과 따로, 같은 서버에서 함께 돌 수 있다.
#   scripts/demo.sh up [--stop-before-approval] [--rebuild] [--external-inference <URL>]   데모 구성을 띄우고 시험용 릴리스를 만들어 활성화한다
#   scripts/demo.sh up --llm [--profile gpu-12g] [--yes-large]  실제 LLM(GPU, Qwen3-1.7B(프로파일 gpu-12g, 파이프라인 데모) + 학습하지 않은 중립 LoRA = 시험용 대체)으로 응답하는 데모
#   scripts/demo.sh config --llm [--profile gpu-12g]            컨테이너를 띄우지 않고 실제 LLM 구성의 병합(docker compose config)만 검증한다(이미지 참조가 로컬 태그인지)
#   scripts/demo.sh diag                                        켜져 있는 데모의 release-gate 제출·판정(checks)·수집기·모델 패키지 요약(읽기 전용)
#   scripts/demo.sh activate                                   (--stop-before-approval 로 띄운 뒤) /admin/ 에서 승인한 제출의 릴리스를 활성화한다
#   scripts/demo.sh status | reset [--stop-before-approval] | down [--purge-cache]   (모델 캐시 볼륨은 down 해도 남는다. --purge-cache 로 명시적으로 지운다)
# 이 데이터는 시험용 대체다: 가짜 모델(fake 백엔드), 시험용 어댑터·평가 보고서, 시험용 승인자(스크립트). E2E와 같은 시험 구성(compose.test.yaml)을 쓴다.
# 표준 `docker`만 쓴다. 컨테이너의 호스트 포트는 Docker가 배정한다(고정 포트 없음). 임시 레지스트리도 빈 포트를 고른다.
# 환경 변수: DEMO_PROJECT(기본 deploy-demo, 반드시 deploy-demo 로 시작), DEMO_BIND(gateway 호스트 바인드, 기본 127.0.0.1; 다른 PC에서 보려면 0.0.0.0 -- HTTP·기본 인증이라 시험 때만),
#           DEMO_REGISTRY_BIND(레지스트리 바인드, 기본 127.0.0.1; 데몬이 닿지 못하면 사용자가 0.0.0.0 으로 바꾼다 -- 끝나면 down).
set -uo pipefail
DEPLOY_NO_DOCKER=1   # 사용법·인자 검사는 Docker 없이도 동작한다. 데몬 감지는 그 뒤에 한다
source "$(dirname "$0")/lib.sh"
CMD=${1:-}; shift || true
STOP=0; REBUILD=0; EXT=""; LLM=0; REBUILD_GPU=0; YES_LARGE=0; LLM_PROFILE_NAME=""; PURGE_CACHE=0; PURGE_YES=0
while [ $# -gt 0 ]; do case "$1" in
  --stop-before-approval) STOP=1; shift;; --rebuild) REBUILD=1; shift;;
  --external-inference) [ $# -ge 2 ] || die "--external-inference 에는 URL이 필요하다"; EXT=$2; shift 2;;
  --external-inference=*) EXT=${1#*=}; shift;;
  --purge-cache) PURGE_CACHE=1; shift;; --yes-purge-"${HF_CACHE_VOLUME:-deploy-llm-hf-cache}") PURGE_YES=1; shift;;
  --llm) LLM=1; shift;; --rebuild-gpu) REBUILD_GPU=1; shift;; --yes-large) YES_LARGE=1; shift;;
  --profile) [ $# -ge 2 ] || die "--profile 에는 이름이 필요하다 (예: gpu-12g)"; LLM_PROFILE_NAME=$2; shift 2;;
  --profile=*) LLM_PROFILE_NAME=${1#*=}; shift;;
  *) die "알 수 없는 인자: $1";; esac; done
[ -z "$LLM_PROFILE_NAME" ] || [ $LLM = 1 ] || die "--profile 은 --llm 과 함께 쓴다"
[ $LLM = 0 ] || [ -z "$EXT" ] || die "--llm 은 --external-inference 와 함께 쓰지 않는다 (외부 GPU 서버는 그 서버에서 compose.inference.yaml, docs/RUN.md 7-1)"
[[ "${LLM_PROFILE_NAME:-gpu-12g}" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "프로파일 이름은 소문자·숫자·하이픈이다: $LLM_PROFILE_NAME"
[ $PURGE_CACHE = 1 ] || [ $PURGE_YES = 0 ] || die "--yes-purge-$HF_CACHE_VOLUME 는 --purge-cache 와 함께만 쓴다"
[ $PURGE_CACHE = 0 ] || [ "$CMD" = down ] || die "--purge-cache 는 down 과 함께 쓴다 (모델 캐시는 기본적으로 남는다)"
P=${DEMO_PROJECT:-deploy-demo}
case "$P" in deploy-demo*) ;; *) die "DEMO_PROJECT 는 deploy-demo 로 시작해야 한다 (상시 구성과 섞이지 않게)";; esac
W="$DEPLOY_ROOT/state/demo"
usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; }

set_llm_image() { # 데모는 방금 빌드한 로컬 GPU 이미지를 태그로 직접 쓴다(레지스트리에 올리지 않는다: 13GB 이중 보관 방지). digest 고정은 데모에서 하지 않는다
  MODEL_SERVING_GPU_IMAGE=$(sed -n 's/^model-serving-gpu \([^ ]*\) .*/\1/p' "$DEPLOY_ROOT/build/images.env" 2>/dev/null || true)
  export MODEL_SERVING_GPU_IMAGE="${MODEL_SERVING_GPU_IMAGE:-deploy-build/model-serving-gpu:unset}"
}
env_demo() { # 데모 프로젝트의 환경 변수(모든 하위 스크립트가 같은 값을 본다)
  export DEPLOY_LOCK="$W/images.lock" DEPLOY_REGISTRY_ENV="$W/registry.env" DEPLOY_PROJECT="$P" DEPLOY_SKIP_DOCTOR=1
  export REGISTRY_PROJECT="$P-reg" REGISTRY_HOST_BIND="${DEMO_REGISTRY_BIND:-127.0.0.1}" REGISTRY_HOST_PORT=
  export SECRETS_DIR="$W/secrets" COMPOSE_EXTRA="$DEPLOY_ROOT/compose.test.yaml $DEPLOY_ROOT/test/compose.fake-model.yaml" GATEWAY_BIND="${DEMO_BIND:-127.0.0.1}" GATEWAY_PORT=
  export OPS_JOB_CONFIG="$DEPLOY_ROOT/test/ops-job/test-ops-job.yaml"
  # 실제 LLM 모드(D73): up --llm 이 기록한 프로파일 이름을 이후 명령도 쓴다. 파일 순서가 중요하다: compose.llm.yaml 이 compose.test.yaml 의 fake 백엔드를 덮는다. 실제 LLM 모드에는 test/compose.fake-model.yaml(fake 진입점)을 붙이지 않는다.

  if [ $LLM = 1 ] && [ "$CMD" = up ]; then printf '%s\n' "${LLM_PROFILE_NAME:-gpu-12g}" > "$W/llm"; fi
  if [ $LLM = 0 ] && [ -f "$W/llm" ]; then LLM=1; LLM_PROFILE_NAME=$(sed -n 1p "$W/llm"); fi
  if [ $LLM = 1 ]; then
    LLM_PROFILE_NAME=${LLM_PROFILE_NAME:-gpu-12g}
    export DEMO_LLM_PROFILE="/app/profiles/$LLM_PROFILE_NAME.json"
    set_llm_image
    # 이미지는 파일로 고른다(compose.llm.local.yaml = 로컬 태그). 중첩 기본값 한 파일로는 안쪽 필수 변수가 먼저 평가되어 실패한다
    COMPOSE_EXTRA="$DEPLOY_ROOT/compose.test.yaml $DEPLOY_ROOT/compose.llm.yaml $DEPLOY_ROOT/compose.llm.local.yaml"; export COMPOSE_EXTRA
  fi
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
  [ $LLM = 0 ] || msx+=(--llm-package "$W/llm-package")
  local img; img=$( set -a; . "$DEPLOY_LOCK"; . "$DEPLOY_REGISTRY_ENV"; set +a
    echo "{\"survey-service\":\"$DEPLOY_REGISTRY/openit/survey-service@$SURVEY_SERVICE_DIGEST\",\"question-authoring\":\"$DEPLOY_REGISTRY/openit/question-authoring@$QUESTION_AUTHORING_DIGEST\",\"ops-feedback\":\"$DEPLOY_REGISTRY/openit/ops-feedback@$OPS_FEEDBACK_DIGEST\"}" )
  "$VENV/bin/python" "$DEPLOY_ROOT/scripts/e2e_steps.py" --project "$P" --secrets "$SECRETS_DIR" --ports "$(ports_json)" --images "$img" \
    --docker "$DOCKER" --root "$DEPLOY_ROOT" --work "$W/work" --run-id demo-test --only "$only" \
    "${msx[@]}" "$@"
}

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

 암호: 값은 출력하지 않는다. 비밀 파일을 열어 본다 (폴더 700, 저장소 밖 $W/secrets):
   staff            $W/secrets/tokens/staff-console-password
   trainer-e2e      $W/secrets/tokens/admin-console-password
   reviewer-e2e     $W/secrets/tokens/reviewer-console-password
   예: cat $W/secrets/tokens/staff-console-password

 $( [ -n "$EXT" ] && echo "추론 서버: 외부($EXT). 이 구성의 model-serving 은 꺼져 있다." )
 $( [ $LLM = 1 ] && printf '%s' " 실제 LLM: 학습하지 않은 기반 모델(프로파일 $LLM_PROFILE_NAME, gpu-12g 는 Qwen/Qwen3-1.7B) + 학습 데이터의 시스템 프롬프트(prompt-4 조립) + 효과 없는 LoRA(lora_B=0, 시험용 대체). 학습된 모델이 아니라서 A 출력이 형식을 못 지키면 그 턴은 실패 신호로 처리된다(503 OUTPUT_INVALID, 값을 지어내지 않는다, D75). 12GB GPU에서 적재되는지는 서버 미검증이다. 첫 응답은 적재가 끝난 뒤(아래 안내)부터 된다." )
 직원 알림: 지금은 입력원이 없다(OPEN_GAPS G01). 직원 콘솔(/staff/)에 알림이 뜨지 않는 것이 정상이며 survey-service /readyz 의 staff_alert_source.active=false 로 드러난다.
 승인 화면: 승인 대기 시험 제출이 있다$( [ $STOP = 1 ] && echo " (--stop-before-approval: 문항 세트 v1·v2 모두 대기. 승인한 뒤 scripts/demo.sh activate)" || echo " (보지 못한 문항 세트 제출 1건. v1·v2는 스크립트가 시험용 승인자로 이미 승인·활성화)")
 실패 사례 검토 화면: 시험 사례 1건(PENDING). /admin/ 의 검토 메뉴(검토자 계정)

 끄기: scripts/demo.sh down    (데모 프로젝트 $P 의 컨테이너·네트워크·볼륨·임시 레지스트리·state/demo 만 지운다)
=========================================================
GUIDE
}

llm_config_check() { # llm_config_check sentinel|real : 병합된 compose 설정에서 model-serving 이미지 참조가 로컬 태그인지 검증한다(컨테이너를 띄우지 않는다)
  local mode=$1 out rc img pol expect tmp=""
  if [ "$mode" = sentinel ]; then   # 상태 파일 없이: 자리표시 잠금·레지스트리·비밀(빈 파일)로 구조만 본다. 변수 전달 경로를 시험한다
    tmp=$(mktemp -d); expect="deploy-build/model-serving-gpu:config-check"
    cp "$DEPLOY_ROOT/locks/images.lock" "$tmp/images.lock"; echo "DEPLOY_REGISTRY=127.0.0.1:5000" > "$tmp/registry.env"; mkdir -p "$tmp/secrets"
    for f in $(grep -oh 'SECRETS_DIR:-./secrets}/[A-Za-z./-]*' "$DEPLOY_ROOT/compose.yaml" | sed 's|.*secrets}/||' | sort -u); do mkdir -p "$tmp/secrets/$(dirname "$f")"; : > "$tmp/secrets/$f"; done
    out=$( DEPLOY_LOCK="$tmp/images.lock" DEPLOY_REGISTRY_ENV="$tmp/registry.env" SECRETS_DIR="$tmp/secrets" MODEL_SERVING_GPU_IMAGE="$expect" dc "$P" --profile jobs config 2>&1 ); rc=$?
    rm -rf "$tmp"
  else
    expect=$MODEL_SERVING_GPU_IMAGE
    out=$(dc "$P" --profile jobs config 2>&1); rc=$?
  fi
  if [ $rc != 0 ]; then echo "compose 설정 병합 실패 ($mode):" >&2; printf '%s\n' "$out" | tail -6 | cut -c1-300 >&2; return 1; fi
  img=$(printf '%s\n' "$out" | awk '/^  model-serving:/{f=1;next} f&&/^  [^ ]/{f=0} f&&/^    image:/{print $2; exit}')
  pol=$(printf '%s\n' "$out" | awk '/^  model-serving:/{f=1;next} f&&/^  [^ ]/{f=0} f&&/^    pull_policy:/{print $2; exit}')
  echo "  병합 결과 ($mode): model-serving image=${img:-<없음>} pull_policy=${pol:-<없음>}"
  [ "$img" = "$expect" ] || { echo "model-serving 이미지가 기대한 로컬 태그($expect)가 아니다: '${img}'. 변수 MODEL_SERVING_GPU_IMAGE 가 compose 에 전달되지 않았거나 compose.llm.local.yaml 이 빠졌다 (COMPOSE_EXTRA=$COMPOSE_EXTRA)" >&2; return 1; }
  [ "$pol" = never ] || { echo "pull_policy 가 never 가 아니다: '${pol}' (레지스트리에서 받으려 한다)" >&2; return 1; }
  case "$expect" in *:unset) echo "build/images.env 에 model-serving-gpu 항목이 없다: build-images.sh --gpu 를 먼저 (GPU 이미지는 빌드되어 있어야 한다)" >&2; return 1;; esac
}
wait_llm() { # 첫 기동은 모델 내려받기와 적재로 오래 걸린다. 시간 상한 후에도 실패시키지 않고 안내하고 끝낸다
  local mins=${DEMO_LLM_WAIT_MIN:-20} t0=$SECONDS mp sp sc ms
  mp=$(port_of "$P-model-serving-1" 8080); sp=$(port_of "$P-survey-service-1" 8080)
  echo "== 실제 LLM 적재 대기 (최대 ${mins}분, 환경 변수 DEMO_LLM_WAIT_MIN 로 바꾼다). 첫 기동은 huggingface.co 에서 모델(약 4GB(Qwen3-1.7B 추정))을 받고 적재한다"
  while [ $((SECONDS - t0)) -lt $((mins * 60)) ]; do
    sc=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$sp/readyz" 2>/dev/null || true)
    if [ "$sc" = 200 ]; then echo "survey-service 준비됨: 활성 릴리스 적재를 마쳤다. 위 주소에서 키오스크를 눌러 본다"; return 0; fi
    ms=$(curl -s -m 5 "http://127.0.0.1:$mp/readyz" 2>/dev/null | python3 -I -c 'import sys,json;d=json.load(sys.stdin);print(d.get("status"),"사유:",d.get("reason") or "-")' 2>/dev/null || echo "응답 없음")
    echo "  [$(((SECONDS - t0) / 60))분 경과] model-serving /readyz: $ms ; survey-service /readyz: ${sc:-없음}"
    sleep 30
  done
  echo "아직 적재 중이다 (${mins}분 경과). 실패가 아니다. 진행은 scripts/demo.sh status (model-serving 사유) 와 docker compose -p $P logs model-serving 로 본다. 끝나면 survey-service /readyz 가 200 이 된다."
  return 0
}
case "$CMD" in up|activate|status|down|reset|config|diag) detect_docker;; esac
case "$CMD" in
  up)
    [ -d "$W" ] && [ -f "$W/registry.env" ] && die "이미 데모 상태가 있다 ($W). scripts/demo.sh down 또는 reset"
    bash "$DEPLOY_ROOT/scripts/doctor.sh" || exit 1
    mkdir -p "$W"; env_demo
    if [ $LLM = 1 ]; then
      echo "== 실제 LLM 구성 병합 사전 검증 (빌드·게시 전에, 컨테이너를 띄우지 않는다)"
      llm_config_check sentinel || { rm -f "$W/llm"; die "병합 검증 실패: 빌드·게시를 하지 않고 멈춘다 (위 원인을 고친 뒤 scripts/demo.sh down 으로 상태를 지우고 다시)"; }
      DEMO_LLM_PROFILE="$DEMO_LLM_PROFILE" bash "$DEPLOY_ROOT/scripts/doctor.sh" --up --llm || { rm -f "$W/llm"; exit 1; }
    fi
    [ -z "$EXT" ] || bash "$DEPLOY_ROOT/scripts/doctor.sh" --up --inference "$EXT" || { rm -f "$W/external-inference"; exit 1; }
    bash "$DEPLOY_ROOT/scripts/prepare-host.sh" venv || die "호스트 가상환경 준비 실패"
    mr_label_ok() { # 이미지의 io.openit.model-runtime 라벨이 현재 태그와 같은가(라벨이 없는 이미지는 해당 없음; v 접두사는 무시). 어긋나면 게이트가 CONTRACT_COMPAT 로 반려한다
      local l; l=$("$DOCKER" image inspect "$1" --format '{{index .Config.Labels "io.openit.model-runtime"}}' 2>/dev/null | tr -d '\r') || return 1
      case "$l" in ""|"<no value>"|none) return 0;; esac
      [ "${l#v}" = "${DEPLOY_MR_TAG#v}" ]
    }
    have_images() { # 기본 8개 이미지가 기록되어 있고 로컬에 모두 있고 model-runtime 라벨이 현재 태그와 같은가(GPU 이미지 기록은 따로 본다: 그것이 없다고 8개를 다시 빌드하지 않는다)
      local n=0 name img; [ -f "$DEPLOY_ROOT/build/images.env" ] || return 1
      while read -r name img _; do
        [ "$name" = model-serving-gpu ] && continue; n=$((n+1))
        "$DOCKER" image inspect "$img" >/dev/null 2>&1 || return 1
        mr_label_ok "$img" || { echo "  $img 의 model-runtime 라벨이 현재 태그($DEPLOY_MR_TAG)와 다르다: 다시 빌드한다" >&2; return 1; }
      done < "$DEPLOY_ROOT/build/images.env"
      [ "$n" -ge 8 ]
    }
    if [ $REBUILD = 1 ] || ! have_images; then echo "== 이미지 빌드(현재 HEAD)"; bash "$DEPLOY_ROOT/scripts/build-images.sh" || die "이미지 빌드 실패"; fi
    bash "$DEPLOY_ROOT/scripts/prepare-host.sh" wheels || die "호스트 클라이언트 준비 실패"
    if [ $LLM = 1 ]; then
      have_gpu() { local img; img=$(sed -n 's/^model-serving-gpu \([^ ]*\) .*/\1/p' "$DEPLOY_ROOT/build/images.env" 2>/dev/null); [ -n "$img" ] && "$DOCKER" image inspect "$img" >/dev/null 2>&1 && mr_label_ok "$img"; }
      if [ $REBUILD_GPU = 1 ] || ! have_gpu; then
        old=$(sed -n 's/^model-serving-gpu \([^ ]*\) .*/\1/p' "$DEPLOY_ROOT/build/images.env" 2>/dev/null)
        if [ -n "$old" ] && "$DOCKER" image inspect "$old" >/dev/null 2>&1; then echo "== GPU 이미지($old)가 현재 model-runtime 태그($DEPLOY_MR_TAG)과 맞지 않거나 --rebuild-gpu 라서 다시 빌드한다 (옛 이미지는 지우지 않는다; 비대화형은 --yes-large 필요)"; fi
        echo "== GPU 이미지 빌드(model-serving-gpu, 약 13GB)"; bash "$DEPLOY_ROOT/scripts/build-images.sh" --gpu $( [ $YES_LARGE = 1 ] && echo --yes-large ) || die "GPU 이미지 빌드 실패 (비대화형이면 --yes-large)"; fi
      set_llm_image   # 빌드로 images.env 가 바뀌었을 수 있다
      echo "== 중립 LoRA 패키지(학습하지 않은 시험용 대체) 생성: 프로파일 $LLM_PROFILE_NAME"
      bash "$DEPLOY_ROOT/scripts/make-llm-package.sh" "$LLM_PROFILE_NAME" "$W/llm-package" || die "중립 LoRA 패키지 생성 실패"
      if hf_cache_exists; then echo "== HF 캐시 볼륨 $HF_CACHE_VOLUME 재사용 (모델을 다시 받지 않는다)"; else echo "== HF 캐시 볼륨 $HF_CACHE_VOLUME 생성 (프로젝트 밖 볼륨: down 해도 남는다)"; hf_cache_ensure; fi
    fi
    grep -E '^(GATEWAY|REGISTRY|UTIL)_IMAGE=' "$DEPLOY_ROOT/locks/images.lock" > "$DEPLOY_LOCK"
    echo "== 임시 레지스트리와 digest 잠금(이 데모 전용)"
    bash "$DEPLOY_ROOT/scripts/registry.sh" up || die "레지스트리 기동 실패 (데몬이 닿지 못하면 DEMO_REGISTRY_BIND=0.0.0.0 으로 다시, 끝나면 down)"
    bash "$DEPLOY_ROOT/scripts/publish-images.sh" $( [ $LLM = 1 ] && echo $SERVICES ) || die "게시 실패"   # --llm: GPU 이미지는 게시하지 않는다(이름 지정으로 제외)
    bash "$DEPLOY_ROOT/scripts/check-compose.sh" || exit 1
    bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" "$SECRETS_DIR" >/dev/null || die "비밀 생성 실패"
    if [ $LLM = 1 ]; then
      echo "== 기동 직전 병합 검증 (실제 잠금·레지스트리·로컬 GPU 이미지 태그)"
      llm_config_check real || die "병합 검증 실패: 이미지는 다시 빌드·게시하지 않았다. 원인을 고친 뒤 scripts/demo.sh down 후 다시 (GPU 이미지는 로컬에 남아 재빌드하지 않는다)"
    fi
    echo "== 데모 프로젝트 $P 기동 (compose.yaml + compose.test.yaml, 호스트 포트는 Docker 배정)"
    bash "$DEPLOY_ROOT/scripts/up.sh" "$P" || die "기동 실패. 원인: docker compose -p $P logs"
    echo "== 시험용 릴리스 만들기(E2E 단계 코드 재사용): 문항 세트 등록 -> 데이터셋 -> 시험용 어댑터·평가 보고서 -> 후보 수집·자동 검사 $( [ $STOP = 1 ] && echo '(승인 전에 멈춤)' || echo '-> 시험용 승인자 승인 -> 활성화 -> 실패 사례')"
    if [ $STOP = 1 ]; then run_steps "1,2,3,demo4" --demo-stop || die "데모 릴리스 준비 실패 (원인 진단: scripts/demo.sh diag)"
    else run_steps "1,2,3,demo4,6" || die "데모 릴리스 준비 실패 (원인 진단: scripts/demo.sh diag)"; fi
    guide
    [ $LLM = 0 ] || wait_llm ;;
  config)
    [ $LLM = 1 ] || die "demo.sh config 는 --llm 과 함께 쓴다 (실제 LLM 구성의 병합 검증)"
    env_demo; echo "== 실제 LLM 구성 병합 검증 (컨테이너를 띄우지 않는다): 프로파일 $LLM_PROFILE_NAME"
    llm_config_check sentinel || exit 1
    echo "  compose 파일 순서: $COMPOSE_EXTRA"
    cur=$(sed -n 's/^model-serving-gpu \([^ ]*\) .*/\1/p' "$DEPLOY_ROOT/build/images.env" 2>/dev/null || true)
    if [ -n "$cur" ] && "$DOCKER" image inspect "$cur" >/dev/null 2>&1; then echo "  로컬 GPU 이미지: $cur (있음: up --llm 이 다시 빌드하지 않는다)"
    else echo "  로컬 GPU 이미지: ${cur:-없음} (up --llm 이 build-images.sh --gpu 로 빌드한다, 약 13GB)"; fi
    echo "병합 검증 통과: model-serving 은 로컬 태그를 참조하고 pull_policy: never 이다" ;;
  diag)
    [ -f "$W/registry.env" ] || die "데모가 떠 있지 않다 (scripts/demo.sh up)"
    env_demo; run_steps "diag" || true ;;
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
    echo "정리 완료 ($P 로 시작하는 자원과 state/demo). 상시 구성과 로컬 deploy-build 이미지(GPU 이미지 포함)는 그대로다."
    if [ $PURGE_CACHE = 1 ]; then hf_cache_purge $PURGE_YES; else hf_cache_report; fi ;;
  reset)
    "$0" down || true
    exec "$0" up $( [ $STOP = 1 ] && echo --stop-before-approval ) $( [ $LLM = 1 ] && echo --llm ) $( [ -n "$LLM_PROFILE_NAME" ] && echo --profile "$LLM_PROFILE_NAME" ) $( [ $YES_LARGE = 1 ] && echo --yes-large ) ;;
  ""|-h|--help|help) usage; [ -z "$CMD" ] && exit 2 || exit 0 ;;
  *) usage >&2; exit 2 ;;
esac
