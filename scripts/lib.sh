#!/usr/bin/env bash
# deploy 스크립트 공통. source 해서 쓴다.
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="$(cd "$DEPLOY_ROOT/.." && pwd)"
VENV="$DEPLOY_ROOT/.venv"
die() { echo "오류: $*" >&2; exit 1; }
# docker 고르기. 환경 변수 DOCKER 가 있으면 그것을 쓴다(실행 파일이 있어야 한다).
#  1) 일반 리눅스·WSL 통합: `docker` 가 있고 데몬에 닿으면 그것.
#  2) WSL(/proc/version 에 microsoft)이면서 `docker.exe` 가 실제로 있고 그 데몬에 닿을 때만 docker.exe 로 폴백한다.
#  3) 그 밖에는 원인을 구분해 한국어 오류로 즉시 중단한다(docker 실행 파일 없음 / 데몬에 닿지 않음).
# docker 가 필요 없는 스크립트(정적 검사 등)는 source 하기 전에 DEPLOY_NO_DOCKER=1 을 둔다. 나중에 필요하면 detect_docker 를 부른다.
detect_docker() {
  if [ -n "${DOCKER:-}" ]; then
    command -v "$DOCKER" >/dev/null 2>&1 || die "DOCKER='$DOCKER' 실행 파일을 찾을 수 없다. DOCKER 변수를 지우거나 올바른 경로로 지정하라."
    return 0
  fi
  local wsl=0 has_docker=0 has_exe=0
  grep -qi microsoft /proc/version 2>/dev/null && wsl=1
  command -v docker >/dev/null 2>&1 && has_docker=1
  [ $wsl = 1 ] && command -v docker.exe >/dev/null 2>&1 && has_exe=1
  if [ $has_docker = 1 ] && docker info >/dev/null 2>&1; then DOCKER=docker; return 0; fi
  if [ $has_exe = 1 ] && docker.exe info >/dev/null 2>&1; then DOCKER=docker.exe; return 0; fi
  if [ $has_docker = 0 ] && [ $has_exe = 0 ]; then
    die "docker 실행 파일이 없다. Docker를 설치하라(리눅스: docker 엔진과 compose 플러그인, WSL: Docker Desktop 통합 또는 docker.exe)."
  fi
  die "Docker 데몬에 닿지 않는다: 데몬이 떠 있는지(리눅스: systemctl start docker, WSL: Docker Desktop 실행) 확인하고, 현재 사용자가 docker 그룹에 속하는지(권한)도 확인하라."
}
[ "${DEPLOY_NO_DOCKER:-0}" = 1 ] || detect_docker
# docker.exe에는 윈도 경로를 넘겨야 한다.
hostpath() { if [ "$DOCKER" = docker.exe ] && command -v wslpath >/dev/null 2>&1; then wslpath -w "$1"; else echo "$1"; fi; }
# 서비스 목록: 영역 리포지토리 이름 = 이미지 이름
SERVICES="survey-service question-authoring ops-feedback release-gate model-registry model-serving kiosk-frontend admin-console"
# 이미지 이름은 영역 이름과 같다. 로컬 레지스트리 안의 저장소 이름은 openit/<영역>.
# docker.exe(윈도 프로그램)는 WSL의 환경 변수를 받지 못한다. 그래서 compose가 읽는 변수는 --env-file 로 넘긴다.
PASS_VARS="REGISTRY_PROJECT REGISTRY_HOST_BIND REGISTRY_HOST_PORT SECRETS_DIR CONFIG_DIR GATEWAY_BIND GATEWAY_PORT OPS_JOB_CONFIG"
PATH_VARS=" SECRETS_DIR CONFIG_DIR OPS_JOB_CONFIG "
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
