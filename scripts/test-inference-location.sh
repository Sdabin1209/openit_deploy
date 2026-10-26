#!/usr/bin/env bash
# 추론 서버 위치 독립 시험(D72). model-serving(CPU/fake 이미지)을 compose.inference.yaml 로 **별도 컴포즈 프로젝트**에 띄우고,
# 본 구성(compose.test.yaml 위에 compose.external-inference.yaml)의 survey-service 가 --external-inference 주소로 그 서버를 부르게 해
# E2E 단계 1~5(릴리스 만들기 -> 활성화 -> 공개 API로 문진 한 턴 이상, 서버 중단·복구 포함)가 통과하는지 본다.
# 사용: scripts/test-inference-location.sh [--keep] [--rebuild]      (-h/--help)
#   --keep     끝나도 자원을 남긴다(디버깅). 정리: scripts/test-inference-location.sh --clean
#   --clean    이 시험이 만든 자원(deploy-e2e-loc* 프로젝트, state/loc-test)만 지운다
# 서버 -> release-gate: 서버(별도 프로젝트)가 게이트에 닿아야 해서 시험 동안만 게이트를 0.0.0.0 의 빈 포트로 추가 노출하고
#   (state/loc-test/expose-gate.yaml), 양쪽 컨테이너는 host.docker.internal(host-gateway)로 서로를 부른다. 고정 포트 없음(빈 포트를 고른다).
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
  if [ -f "$DEPLOY_REGISTRY_ENV" ] && [ -f "$DEPLOY_LOCK" ]; then
    INFERENCE_URL=x INFERENCE_TOKEN_FILE=/dev/null COMPOSE_EXTRA="$DEPLOY_ROOT/compose.test.yaml $DEPLOY_ROOT/compose.external-inference.yaml $W/expose-gate.yaml" \
      dc "$P" --profile jobs down -v --remove-orphans >/dev/null 2>&1 || true
    RELEASE_URL=x INFERENCE_ENV_FILE=/dev/null "$DOCKER" compose -p "$INF" -f "$DEPLOY_ROOT/compose.inference.yaml" --env-file "$DEPLOY_LOCK" --env-file "$DEPLOY_REGISTRY_ENV" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  # 파일 없이도 프로젝트 이름만으로 남은 것을 지운다
  "$DOCKER" compose -p "$P" down -v --remove-orphans >/dev/null 2>&1 || true
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

GPORT=$(free_port); IPORT=$(free_port)
while [ "$IPORT" = "$GPORT" ]; do IPORT=$(free_port); done
cat > "$W/expose-gate.yaml" <<YAML
# 시험 전용: 별도 프로젝트의 추론 서버가 게이트(I4)를 읽도록 게이트를 호스트의 빈 포트로 한 번 더 노출한다
services:
  release-gate:
    ports: ["0.0.0.0:$GPORT:8080"]
YAML
printf 'EXTERNAL_INFERENCE_TOKEN=%s\n' "$(cat "$SECRETS_DIR/tokens/inference-survey-service")" > "$W/inference-token.env"; chmod 600 "$W/inference-token.env"
export COMPOSE_EXTRA="$DEPLOY_ROOT/compose.test.yaml $W/expose-gate.yaml" OPS_JOB_CONFIG="$DEPLOY_ROOT/test/ops-job/test-ops-job.yaml"
export INFERENCE_TOKEN_FILE="$W/inference-token.env"

echo "== 본 구성 기동: model-serving 끔, 외부 추론 서버 http://host.docker.internal:$IPORT"
bash "$DEPLOY_ROOT/scripts/up.sh" "$P" --external-inference "http://host.docker.internal:$IPORT" || bail "본 구성 기동 실패"
chk "본 구성에 model-serving 컨테이너가 없다(프로필로 꺼짐)" test -z "$("$DOCKER" ps -a -q --filter "name=^$P-model-serving")"

echo "== 별도 프로젝트 $INF: compose.inference.yaml 하나로 추론 서버 기동 (포트 $IPORT)"
( set -a; . "$DEPLOY_LOCK"; . "$DEPLOY_REGISTRY_ENV"; set +a
  export RELEASE_URL="http://host.docker.internal:$GPORT" INFERENCE_ENV_FILE="$SECRETS_DIR/model-serving.env" INFERENCE_PORT=$IPORT INFERENCE_BIND=0.0.0.0
  "$DOCKER" compose -p "$INF" -f "$DEPLOY_ROOT/compose.inference.yaml" up -d --wait ) || bail "추론 서버 기동 실패"
chk "추론 서버가 별도 프로젝트($INF)의 컨테이너다" test -n "$("$DOCKER" ps -q --filter "label=com.docker.compose.project=$INF" --filter "name=model-serving")"
chk "doctor --inference (호출자 호스트 -> 추론 서버)" bash "$DEPLOY_ROOT/scripts/doctor.sh" --up --inference "http://127.0.0.1:$IPORT"

port() { port_of "$P-$1-1" 8080; }
PORTS="{\"qa\":$(port question-authoring),\"gate\":$(port release-gate),\"ops\":$(port ops-feedback-ingest),\"survey\":$(port survey-service),\"mr\":$(port model-registry),\"gw\":$(port gateway),\"ms\":$IPORT}"
IMG=$( set -a; . "$DEPLOY_LOCK"; . "$DEPLOY_REGISTRY_ENV"; set +a
  echo "{\"survey-service\":\"$DEPLOY_REGISTRY/openit/survey-service@$SURVEY_SERVICE_DIGEST\",\"question-authoring\":\"$DEPLOY_REGISTRY/openit/question-authoring@$QUESTION_AUTHORING_DIGEST\",\"ops-feedback\":\"$DEPLOY_REGISTRY/openit/ops-feedback@$OPS_FEEDBACK_DIGEST\"}" )
echo "== E2E 단계 1~5 (추론 서버는 외부)"
"$VENV/bin/python" "$DEPLOY_ROOT/scripts/e2e_steps.py" --project "$P" --secrets "$SECRETS_DIR" --ports "$PORTS" --images "$IMG" --docker "$DOCKER" \
  --root "$DEPLOY_ROOT" --work "$W/work" --run-id loc-test --only 1,2,3,4,5 \
  --ms-url "http://127.0.0.1:$IPORT" --ms-token-file "$INFERENCE_TOKEN_FILE" --ms-container "$INF-model-serving-1"
RC=$?
[ $RC = 0 ] && { PASS=$((PASS+1)); echo "  [PASS] 단계 1~5 (외부 추론 서버로 한 턴 이상 통과, 서버 중단·복구)"; } || { FAIL=$((FAIL+1)); echo "  [FAIL] 단계 1~5 (종료 코드 $RC)"; }
echo; echo "위치 독립 시험: PASS $PASS / FAIL $FAIL"
[ $KEEP = 1 ] && echo "(--keep: 자원을 남겼다. 지우기: scripts/test-inference-location.sh --clean)"
[ $FAIL = 0 ]
