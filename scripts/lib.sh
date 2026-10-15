#!/usr/bin/env bash
# deploy 스크립트 공통. source 해서 쓴다.
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="$(cd "$DEPLOY_ROOT/.." && pwd)"
VENV="$DEPLOY_ROOT/.venv"
# WSL에서 docker가 없으면 docker.exe를 쓴다.
if [ -z "${DOCKER:-}" ]; then
  # docker가 데몬에 닿으면 그것을, 아니면(WSL에서 통합이 꺼진 경우) docker.exe 를 쓴다.
  if docker info >/dev/null 2>&1; then DOCKER=docker; else DOCKER=docker.exe; fi
fi
# docker.exe에는 윈도 경로를 넘겨야 한다.
hostpath() { if [ "$DOCKER" = docker.exe ] && command -v wslpath >/dev/null 2>&1; then wslpath -w "$1"; else echo "$1"; fi; }
die() { echo "오류: $*" >&2; exit 1; }
# 서비스 목록: 영역 리포지토리 이름 = 이미지 이름
SERVICES="survey-service question-authoring ops-feedback release-gate model-registry"
# 이미지 이름은 영역 이름과 같다. 로컬 레지스트리 안의 저장소 이름은 openit/<영역>.
# docker.exe(윈도 프로그램)는 WSL의 환경 변수를 받지 못한다. 그래서 compose가 읽는 변수는 --env-file 로 넘긴다.
PASS_VARS="REGISTRY_PROJECT REGISTRY_HOST_BIND REGISTRY_HOST_PORT SECRETS_DIR CONFIG_DIR TEST_SURVEY_TESTS_DIR GATEWAY_BIND GATEWAY_PORT OPS_JOB_CONFIG TEST_POLICY_FILE TEST_RUNNER_DIR"
PATH_VARS=" SECRETS_DIR CONFIG_DIR OPS_JOB_CONFIG TEST_POLICY_FILE TEST_RUNNER_DIR "
envfile() { # envfile <출력 파일>: 설정된 변수만 쓴다(빈 값도 "설정됨"으로 쓴다). 경로는 docker.exe용으로 바꾼다
  : > "$1"
  local v val
  for v in $PASS_VARS; do
    if [ -n "${!v+x}" ]; then
      val=${!v}
      if [[ "$PATH_VARS" == *" $v "* ]] && [ -n "$val" ]; then val=$(hostpath "$val"); fi
      printf '%s=%s\n' "$v" "$val" >> "$1"
    fi
  done
}
dc() { # dc <project> <compose args...>
  local project=$1; shift
  local files=(-f "$(hostpath "$DEPLOY_ROOT/compose.yaml")")
  if [ -n "${COMPOSE_EXTRA:-}" ]; then
    for f in $COMPOSE_EXTRA; do files+=(-f "$(hostpath "$f")"); done
  fi
  local ef; ef=$(mktemp); envfile "$ef"; trap 'rm -f "$ef"' RETURN
  local envs=(--env-file "$(hostpath "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}")" --env-file "$(hostpath "$ef")")
  [ -f "${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}" ] && envs+=(--env-file "$(hostpath "${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}")")
  [ -f "$DEPLOY_ROOT/.env" ] && envs+=(--env-file "$(hostpath "$DEPLOY_ROOT/.env")")
  # 잠금 파일이 digest의 유일한 출처다: 셸에 남은 같은 이름의 변수가 --env-file 을 이기지 못하게 지운다
  env -u SURVEY_SERVICE_DIGEST -u QUESTION_AUTHORING_DIGEST -u OPS_FEEDBACK_DIGEST -u RELEASE_GATE_DIGEST -u GATEWAY_IMAGE -u REGISTRY_IMAGE -u UTIL_IMAGE -u DEPLOY_REGISTRY \
    "$DOCKER" compose -p "$project" --project-directory "$(hostpath "$DEPLOY_ROOT")" "${files[@]}" "${envs[@]}" "$@"
}
# 컨테이너 포트가 Docker가 배정한 호스트 포트를 읽는다. port_of <컨테이너> <내부포트>
port_of() { "$DOCKER" port "$1" "$2/tcp" | head -1 | tr -d '\r' | sed 's/.*://'; }
# 빈 포트를 하나 고른다(Docker Desktop은 Docker가 배정한 포트에 데몬 쪽에서 닿지 못해 레지스트리에만 쓴다).
free_port() {
  python3 - <<'PY'
import random, socket
for _ in range(200):
    p = random.randint(20000, 39999)
    s = socket.socket()
    try:
        s.bind(("0.0.0.0", p)); s.close(); print(p); break
    except OSError:
        s.close()
PY
}
