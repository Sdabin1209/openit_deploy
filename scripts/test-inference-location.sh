#!/usr/bin/env bash
# 추론 서버 위치 독립 시험(D72). model-serving(CPU/fake 이미지)을 compose.inference.yaml 로 **별도 컴포즈 프로젝트**에 띄우고,
# 본 구성(compose.test.yaml 위에 compose.external-inference.yaml)의 survey-service 가 --external-inference 주소로 그 서버를 부르게 해
# E2E 단계 1~5(릴리스 만들기 -> 활성화 -> 공개 API로 문진 한 턴 이상)가 통과하는지 본다.
# 사용: scripts/test-inference-location.sh [--keep] [--rebuild]      (-h/--help)
#   --keep     끝나도 자원을 남긴다(디버깅). 정리: scripts/test-inference-location.sh --clean
#   --clean    이 시험이 만든 자원(deploy-e2e-loc* 프로젝트, state/loc-test)만 지운다
# 호스트 포트는 모두 Docker 가 배정한다(`127.0.0.1::8080`, 게시 후 `docker port` 로 읽는다). 이 스크립트가 포트를 고르지 않는다
#   (임시 레지스트리만 registry.sh 의 기존 방식: 빈 포트를 명시 -- e2e.sh 와 같다).
# 노출 범위는 최소로 시작한다: 추론 서버와 게이트를 127.0.0.1 에만 게시하고, 컨테이너가 host.docker.internal(host-gateway)로 닿는지
#   컨테이너에서 직접 확인한다. 닿지 않을 때만(리눅스는 loopback 게시 포트에 host-gateway 로 닿지 못한다) 0.0.0.0 으로 올려 다시 시도한다.
#   0.0.0.0 이 필요하면 사유를 출력하고, 열린 상태는 이 시험이 도는 동안뿐이다(끝나면 trap 이 프로젝트를 지운다).
# 만드는 자원은 모두 deploy-e2e-loc 접두사다. 끝나면 지운다. 표준 docker 만 쓴다.
set -uo pipefail
DEPLOY_NO_DOCKER=1   # 사용법·인자 검사는 Docker 없이도 동작한다
source "$(dirname "$0")/lib.sh"
KEEP=0; REBUILD=0; CLEAN=0
for x in "$@"; do case "$x" in
  --keep) KEEP=1;; --rebuild) REBUILD=1;; --clean) CLEAN=1;;
  -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  *) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//' >&2; echo "알 수 없는 인자: $x" >&2; exit 2;; esac; done
detect_docker
P=deploy-e2e-loc; INF=deploy-e2e-loc-inf; REGP=deploy-e2e-loc-reg
W="$DEPLOY_ROOT/state/loc-test"
export DEPLOY_LOCK="$W/images.lock" DEPLOY_REGISTRY_ENV="$W/registry.env" DEPLOY_PROJECT="$P" DEPLOY_SKIP_DOCTOR=1
export REGISTRY_PROJECT="$REGP" REGISTRY_HOST_BIND="${LOC_REGISTRY_BIND:-127.0.0.1}" REGISTRY_HOST_PORT=
export SECRETS_DIR="$W/secrets" GATEWAY_PORT=

cleanup() {
  echo "== 정리 ($P, $INF, $REGP, state/loc-test)"
  "$DOCKER" rm -f "$P-probe" >/dev/null 2>&1 || true
  # 프로젝트 이름만으로 지운다(컴포즈가 라벨로 찾는다)
  "$DOCKER" compose -p "$P" --profile jobs --profile local-inference down -v --remove-orphans >/dev/null 2>&1 || true
  "$DOCKER" compose -p "$INF" down -v --remove-orphans >/dev/null 2>&1 || true
  bash "$DEPLOY_ROOT/scripts/registry.sh" down -v >/dev/null 2>&1 || true
  [ "$W" = "$DEPLOY_ROOT/state/loc-test" ] && rm -rf "$W"
  echo "남은 자원:"; for q in "$P" "$INF" "$REGP"; do "$DOCKER" ps -a --filter "label=com.docker.compose.project=$q" --format '  컨테이너 {{.Names}}'; "$DOCKER" volume ls --filter "label=com.docker.compose.project=$q" --format '  볼륨 {{.Name}}'; done
}
if [ $CLEAN = 1 ]; then cleanup; exit 0; fi
[ -d "$W" ] && die "이전 시험 상태가 남아 있다 ($W). scripts/test-inference-location.sh --clean"
[ $KEEP = 1 ] || trap cleanup EXIT

PASS=0; FAIL=0
chk() { # chk <설명> <명령...>
  local d=$1; shift
  if "$@" >/dev/null 2>&1; then PASS=$((PASS+1)); echo "  [PASS] $d"; else FAIL=$((FAIL+1)); echo "  [FAIL] $d"; fi
}
bail() { echo "중단: $*" >&2; exit 1; }

bash "$DEPLOY_ROOT/scripts/doctor.sh" || exit 1
mkdir -p "$W"
bash "$DEPLOY_ROOT/scripts/prepare-host.sh" venv || bail "호스트 가상환경 준비 실패"
have_images() { [ -f "$DEPLOY_ROOT/build/images.env" ] && [ "$(wc -l < "$DEPLOY_ROOT/build/images.env")" -ge 8 ] && while read -r _ img _; do "$DOCKER" image inspect "$img" >/dev/null 2>&1 || return 1; done < "$DEPLOY_ROOT/build/images.env"; }
if [ $REBUILD = 1 ] || ! have_images; then echo "== 이미지 빌드(현재 HEAD)"; bash "$DEPLOY_ROOT/scripts/build-images.sh" || bail "이미지 빌드 실패"; fi
bash "$DEPLOY_ROOT/scripts/prepare-host.sh" wheels || bail "호스트 클라이언트 준비 실패"
grep -E '^(GATEWAY|REGISTRY|UTIL)_IMAGE=' "$DEPLOY_ROOT/locks/images.lock" > "$DEPLOY_LOCK"
echo "== 임시 레지스트리·게시·비밀"
bash "$DEPLOY_ROOT/scripts/registry.sh" up || bail "레지스트리 기동 실패 (데몬이 닿지 못하면 LOC_REGISTRY_BIND=0.0.0.0 으로 다시)"
bash "$DEPLOY_ROOT/scripts/publish-images.sh" || bail "게시 실패"
bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" "$SECRETS_DIR" >/dev/null || bail "비밀 생성 실패"

UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_LOCK")
printf 'EXTERNAL_INFERENCE_TOKEN=%s\n' "$(cat "$SECRETS_DIR/tokens/inference-survey-service")" > "$W/inference-token.env"; chmod 600 "$W/inference-token.env"
export COMPOSE_EXTRA="$DEPLOY_ROOT/compose.test.yaml" OPS_JOB_CONFIG="$DEPLOY_ROOT/test/ops-job/test-ops-job.yaml"
export INFERENCE_TOKEN_FILE="$W/inference-token.env"
INF_IMAGE=$( set -a; . "$DEPLOY_LOCK"; . "$DEPLOY_REGISTRY_ENV"; set +a; echo "$DEPLOY_REGISTRY/openit/model-serving@$MODEL_SERVING_DIGEST" )
PLACEHOLDER="http://host.docker.internal:1"   # 서버가 뜨기 전 자리표시 주소(아무 포트도 열지 않는다). 뒤에서 실제 주소로 바꿔 survey-service 만 다시 만든다
reach() { # reach <URL>: 컨테이너(호출자·서버와 같은 위치)에서 host.docker.internal 로 닿는지
  "$DOCKER" run --rm --name "$P-probe" --add-host host.docker.internal:host-gateway "$UTIL" python -c "import sys,urllib.request;urllib.request.urlopen(sys.argv[1],timeout=5)" "$1" >/dev/null 2>&1
}
inf_compose() { ( set -a; . "$DEPLOY_LOCK"; . "$DEPLOY_REGISTRY_ENV"; set +a
  INFERENCE_IMAGE="$INF_IMAGE" INFERENCE_ENV_FILE="$SECRETS_DIR/model-serving.env" RELEASE_URL="http://host.docker.internal:$GPORT" INFERENCE_PORT= INFERENCE_BIND=$BIND \
    "$DOCKER" compose -p "$INF" -f "$DEPLOY_ROOT/compose.inference.yaml" "$@" ); }

OK=0
for BIND in 127.0.0.1 0.0.0.0; do
  if [ "$BIND" = 0.0.0.0 ]; then
    echo "== 사유: 컨테이너가 host.docker.internal 로 127.0.0.1 게시 포트에 닿지 못했다. 시험 동안만 0.0.0.0 으로 게시한다"
    cat > "$W/expose-gate.yaml" <<YAML
# 시험 전용(시험 동안만 열림): 별도 프로젝트의 추론 서버가 게이트(I4)를 읽도록 게이트를 0.0.0.0 의 Docker 배정 포트로 한 번 더 게시한다
services:
  release-gate:
    ports: ["0.0.0.0::8080"]
YAML
    export COMPOSE_EXTRA="$DEPLOY_ROOT/compose.test.yaml $W/expose-gate.yaml"
    inf_compose down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  echo "== 본 구성 기동(바인드 $BIND): model-serving 끔, 외부 추론 서버 자리표시 주소"
  bash "$DEPLOY_ROOT/scripts/up.sh" "$P" --external-inference "$PLACEHOLDER" || bail "본 구성 기동 실패"
  GPORT=$("$DOCKER" port "$P-release-gate-1" 8080/tcp | tr -d '\r' | sed -n 's/^\(0\.0\.0\.0\|127\.0\.0\.1\):\([0-9]*\)$/\1 \2/p' | awk -v b="$BIND" '$1==b{print $2; exit}')
  [ -n "$GPORT" ] || bail "게이트 호스트 포트를 읽지 못했다 (바인드 $BIND)"
  echo "== 별도 프로젝트 $INF: compose.inference.yaml 하나로 추론 서버 기동 (바인드 $BIND, 포트는 Docker 배정)"
  inf_compose up -d --wait || bail "추론 서버 기동 실패"
  IPORT=$(port_of "$INF-model-serving-1" 8080)
  [ -n "$IPORT" ] || bail "추론 서버 호스트 포트를 읽지 못했다"
  if reach "http://host.docker.internal:$IPORT/healthz" && reach "http://host.docker.internal:$GPORT/healthz"; then OK=1; break; fi
  echo "  컨테이너에서 host.docker.internal:$IPORT(서버) 또는 :$GPORT(게이트)에 닿지 못했다 (바인드 $BIND)"
done
[ $OK = 1 ] || bail "컨테이너가 호스트에 게시된 서버·게이트에 닿지 못했다(방화벽·제외 포트 범위 확인)"
echo "  바인드 $BIND 로 추론 서버 http://host.docker.internal:$IPORT, 게이트 :$GPORT 에 컨테이너에서 닿는다"
chk "추론 서버가 별도 프로젝트($INF)의 컨테이너다" test -n "$("$DOCKER" ps -q --filter "label=com.docker.compose.project=$INF" --filter "name=model-serving")"
chk "doctor --inference (호출자 호스트 -> 추론 서버)" bash "$DEPLOY_ROOT/scripts/doctor.sh" --up --inference "http://127.0.0.1:$IPORT"

echo "== survey-service 를 실제 서버 주소로 다시 만든다(--external-inference http://host.docker.internal:$IPORT)"
bash "$DEPLOY_ROOT/scripts/up.sh" "$P" --external-inference "http://host.docker.internal:$IPORT" || bail "본 구성 재기동 실패"
chk "본 구성에 model-serving 컨테이너가 없다(프로필로 꺼짐)" test -z "$("$DOCKER" ps -a -q --filter "name=^$P-model-serving")"

port() { port_of "$P-$1-1" 8080; }
PORTS="{\"qa\":$(port question-authoring),\"gate\":$(port release-gate),\"ops\":$(port ops-feedback-ingest),\"survey\":$(port survey-service),\"mr\":$(port model-registry),\"gw\":$(port gateway),\"ms\":$IPORT}"
IMG=$( set -a; . "$DEPLOY_LOCK"; . "$DEPLOY_REGISTRY_ENV"; set +a
  echo "{\"survey-service\":\"$DEPLOY_REGISTRY/openit/survey-service@$SURVEY_SERVICE_DIGEST\",\"question-authoring\":\"$DEPLOY_REGISTRY/openit/question-authoring@$QUESTION_AUTHORING_DIGEST\",\"ops-feedback\":\"$DEPLOY_REGISTRY/openit/ops-feedback@$OPS_FEEDBACK_DIGEST\"}" )
echo "== E2E 단계 1~5 (추론 서버는 외부; 중단·복구는 건너뜀: 서버 재시작 뒤 Docker 배정 포트가 바뀔 수 있다)"
"$VENV/bin/python" "$DEPLOY_ROOT/scripts/e2e_steps.py" --project "$P" --secrets "$SECRETS_DIR" --ports "$PORTS" --images "$IMG" --docker "$DOCKER" \
  --root "$DEPLOY_ROOT" --work "$W/work" --run-id loc-test --only 1,2,3,4,5 --skip-ms-restart \
  --ms-url "http://127.0.0.1:$IPORT" --ms-token-file "$INFERENCE_TOKEN_FILE" --ms-container "$INF-model-serving-1"
RC=$?
[ $RC = 0 ] && { PASS=$((PASS+1)); echo "  [PASS] 단계 1~5 (외부 추론 서버로 한 턴 이상 통과)"; } || { FAIL=$((FAIL+1)); echo "  [FAIL] 단계 1~5 (종료 코드 $RC)"; }
echo; echo "위치 독립 시험: PASS $PASS / FAIL $FAIL (게시 바인드 $BIND)"
[ $KEEP = 1 ] && echo "(--keep: 자원을 남겼다. 지우기: scripts/test-inference-location.sh --clean)"
[ $FAIL = 0 ]
