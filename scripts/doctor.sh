#!/usr/bin/env bash
# 사전 점검(읽기 전용, 비밀 값을 출력하지 않는다). 깨끗한 머신에서 e2e.sh / up.sh 전에 돈다. 항목마다 OK/WARN/FAIL 과 해결 방법 한 줄을 낸다.
# 사용: scripts/doctor.sh [--up]
#   기본: 빌드·E2E 에 필요한 전부(소스 워크스페이스 포함).  --up: 서버에서 띄우기만 할 때(git·형제 리포·태그·빌드 의존 점검을 건너뛴다)
# e2e.sh / up.sh 는 시작에서 이것을 부르고 FAIL 이 있으면 멈춘다. 건너뛰기: DEPLOY_SKIP_DOCTOR=1
# 환경 문제를 코드로 숨기지 않는다: 진단하고 고치는 법을 안내할 뿐 아무것도 바꾸지 않는다.
set -uo pipefail
DEPLOY_NO_DOCKER=1
source "$(dirname "$0")/lib.sh"
UP_ONLY=0; [ "${1:-}" = --up ] && UP_ONLY=1
FAILS=0; WARNS=0
ok()   { printf '  [OK]   %s\n' "$1"; }
warn() { printf '  [WARN] %s\n         -> %s\n' "$1" "$2"; WARNS=$((WARNS+1)); }
fail() { printf '  [FAIL] %s\n         -> 해결: %s\n' "$1" "$2"; FAILS=$((FAILS+1)); }
WSL=0; grep -qi microsoft /proc/version 2>/dev/null && WSL=1   # 진단 문구를 고르는 데만 쓴다(동작 분기가 아니다)
echo "== deploy doctor ($([ $UP_ONLY = 1 ] && echo '서버 기동용 --up' || echo '빌드·E2E 전체')) -- 환경: $([ $WSL = 1 ] && echo WSL || echo 리눅스/기타)"

if [ $UP_ONLY = 0 ]; then
  if command -v git >/dev/null 2>&1; then ok "git $(git --version | awk '{print $3}')"; else fail "git 이 없다" "패키지 관리자로 git 설치 (예: sudo apt-get install -y git)"; fi
fi
if command -v python3 >/dev/null 2>&1; then
  ok "python3 $(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
  if python3 -c "import venv, ensurepip" >/dev/null 2>&1; then ok "python3 venv/ensurepip 모듈"; else fail "python3 venv 모듈이 없다" "예: sudo apt-get install -y python3-venv (E2E·스크립트는 .venv 가상환경을 만든다)"; fi
else
  fail "python3 이 없다" "python3 (3.10 이상)와 python3-venv 설치"
fi

# --- docker: 표준 `docker` CLI 와 설정된 데몬(DOCKER_HOST / context) 하나의 경로만 본다. 고치는 것은 환경 쪽이다(이 스크립트는 아무것도 고치지 않는다)
D="${DOCKER:-docker}"
if ! command -v "$D" >/dev/null 2>&1; then
  fail "docker 실행 파일이 없다 ('$D')" "Docker 설치: 리눅스는 Docker Engine(docs/SETUP.md A절), WSL은 Windows에 Docker Desktop 설치 후 Settings > Resources > WSL integration 에서 이 배포판을 켠다(B절)"
  D=""
else
  ok "docker 실행 파일 ($D)"
  ERR=$("$D" info 2>&1 >/dev/null); RC=$?
  if [ $RC = 0 ]; then
    ok "데몬 접속 (DOCKER_HOST=${DOCKER_HOST:-<기본 소켓>})"
  else
    SOCK="${DOCKER_HOST:-unix:///var/run/docker.sock}"; SOCK=${SOCK#unix://}
    if echo "$ERR" | grep -qi "permission denied"; then
      fail "Docker 소켓 접근 권한이 없다" "현재 사용자를 docker 그룹에 넣고 다시 로그인: sudo usermod -aG docker \$USER (docs/SETUP.md A절)"
    elif [ "${SOCK#/}" != "$SOCK" ] && [ ! -S "$SOCK" ]; then
      if [ $WSL = 1 ]; then fail "Docker 소켓이 없다 ($SOCK): Docker Desktop의 WSL 연동이 꺼져 있거나 Docker Desktop이 실행 중이 아니다" "Windows에서 Docker Desktop을 먼저 실행해 엔진이 Running이 된 뒤, Settings > Resources > WSL integration 에서 이 배포판을 켜고, Windows에서 wsl --shutdown 후 WSL을 다시 연다 (docs/SETUP.md B절)"
      else fail "Docker 소켓이 없다 ($SOCK): 데몬이 꺼져 있다" "sudo systemctl start docker (부팅 때 자동 시작: sudo systemctl enable docker). DOCKER_HOST 를 쓴다면 주소 확인 (docs/SETUP.md A절)"; fi
    else
      fail "Docker 데몬에 닿지 않는다 (응답 없음)" "데몬 상태 확인(리눅스: systemctl status docker, WSL: Docker Desktop이 완전히 시작됐는지). 오류 첫 줄: $(echo "$ERR" | head -1 | cut -c1-120)"
    fi
    D=""
  fi
fi
if [ -n "$D" ]; then
  if "$D" compose version >/dev/null 2>&1; then ok "docker compose $("$D" compose version --short 2>/dev/null)"; else fail "docker compose 플러그인이 없다" "리눅스: sudo apt-get install -y docker-compose-plugin. WSL: Docker Desktop 통합을 켠다 (docs/SETUP.md)"; fi
  if [ $UP_ONLY = 0 ]; then
    if "$D" buildx version >/dev/null 2>&1; then ok "docker buildx"; else fail "docker buildx 플러그인이 없다" "이미지 빌드(--build-context)에 필요: sudo apt-get install -y docker-buildx-plugin (WSL은 Docker Desktop 통합)"; fi
  fi
fi
# 자격증명 도우미: ~/.docker/config.json 의 credsStore/credHelpers 가 가리키는 docker-credential-<이름> 이 실행 가능해야 pull/build 가 된다.
# 이 파일은 읽기만 한다(내용은 출력하지 않고, 수정하지 않는다). 고치는 것은 사용자가 한다.
CFG="${DOCKER_CONFIG:-$HOME/.docker}/config.json"
if [ -f "$CFG" ] && command -v python3 >/dev/null 2>&1; then
  HELPERS=$(python3 - "$CFG" <<'PY' 2>/dev/null
import json, sys
try: c = json.load(open(sys.argv[1]))
except Exception: sys.exit(0)
n = set()
if isinstance(c.get("credsStore"), str) and c["credsStore"]: n.add(c["credsStore"])
if isinstance(c.get("credHelpers"), dict): n.update(v for v in c["credHelpers"].values() if isinstance(v, str) and v)
print("\n".join(sorted(n)))
PY
)
  BAD=""; for h in $HELPERS; do b="docker-credential-$h"
    if ! command -v "$b" >/dev/null 2>&1; then BAD="$BAD $b(없음)"; continue; fi
    "$b" version >/dev/null 2>&1 </dev/null; rc=$?; if [ $rc = 126 ] || [ $rc = 127 ]; then BAD="$BAD $b(실행 불가)"; fi
  done
  if [ -z "$BAD" ]; then ok "docker 자격증명 도우미 이상 없음$([ -z "$HELPERS" ] && echo ' (도우미 설정 없음)')"
  else fail "docker 자격증명 도우미를 실행할 수 없다:$BAD -> 이미지 pull/build 가 'error getting credentials … exec format error' 로 실패한다" "사용자가 직접 고친다(이 스크립트는 $CFG 를 수정하지 않는다): (1) 그 파일에서 \"credsStore\" 항목을 지운다(저장된 레지스트리 로그인은 쓸 수 없게 된다, 익명 pull 에는 영향 없음), 또는 (2) WSL 이면 interop 을 켠다(/etc/wsl.conf 의 [interop] enabled=true 후 윈도에서 wsl --shutdown). docs/SETUP.md B절"; fi
else
  ok "docker 자격증명 설정 파일 없음 또는 확인 불가 (도우미 문제 없음으로 본다)"
fi

if [ $UP_ONLY = 0 ]; then
  # --- 워크스페이스 형제 리포와 필요한 태그 (build-images.sh 가 쓰는 값: lib.sh)
  NEED="boundary-contracts turn-engine model-runtime survey-service question-authoring ops-feedback release-gate model-lab kiosk-frontend admin-console synthetic-data"
  MISSING=""; for r in $NEED; do [ -e "$WORKSPACE/$r/.git" ] || MISSING="$MISSING $r"; done
  if [ -z "$MISSING" ]; then ok "형제 리포 $(echo $NEED | wc -w)개가 $WORKSPACE 옆에 있다"; else fail "형제 리포가 없다:$MISSING" "docs/SETUP.md C절: head 를 clone 한 뒤 bash <루트>/head/setup.sh (폴더 이름은 head/workspace.yaml 과 같아야 한다)"; fi
  tagchk() { # tagchk <리포> <태그>
    [ -e "$WORKSPACE/$1/.git" ] || return 0
    if git -C "$WORKSPACE/$1" rev-parse -q --verify "refs/tags/$2" >/dev/null 2>&1; then ok "태그 $1 $2"; else fail "태그가 없다: $1 $2" "git -C ../$1 fetch --tags (그래도 없으면 원격에 태그가 없다: head 에 알린다)"; fi
  }
  tagchk boundary-contracts "$DEPLOY_BC_TAG"; tagchk boundary-contracts "$DEPLOY_BC_TAG_SD"
  tagchk model-runtime "$DEPLOY_MR_TAG"; tagchk turn-engine "$DEPLOY_TE_TAG"; tagchk survey-service "$DEPLOY_SS_TAG"
  # --- 디스크
  AVAIL=$(df -Pk "$DEPLOY_ROOT" 2>/dev/null | awk 'NR==2{printf "%d", $4/1048576}')
  # 주의: WSL 에서 df 는 WSL 가상 디스크의 여유만 알려 주고, 윈도 호스트 드라이브(Docker Desktop 의 이미지 저장 위치)의 여유는 알려 주지 않는다.
  if [ -n "$AVAIL" ] && [ "$AVAIL" -lt 20 ]; then warn "디스크 여유 약 ${AVAIL}GB (이미지 빌드·E2E 에 20GB 이상 권장)" "공간 확보 (docker system df 로 이미지·캐시 확인, 필요 시 docker builder prune)$([ $WSL = 1 ] && echo '. WSL: 이 값은 WSL 디스크 기준이며 윈도 호스트 드라이브 여유는 따로 확인')"
  else ok "디스크 여유 약 ${AVAIL:-?}GB$([ $WSL = 1 ] && echo ' (WSL 디스크 기준. 윈도 호스트 드라이브 여유는 df 로 알 수 없다)')"; fi
  # --- 인터넷(빌드 때만 필요)
  if command -v curl >/dev/null 2>&1; then
    NET=""; for u in "https://registry-1.docker.io/v2/" "https://pypi.org/simple/" "https://registry.npmjs.org/"; do
      c=$(curl -s -o /dev/null -m 6 -w '%{http_code}' "$u" 2>/dev/null || true); { [ "$c" = 200 ] || [ "$c" = 401 ]; } || NET="$NET $u"; done
    if [ -z "$NET" ]; then ok "인터넷 도달(Docker Hub, PyPI, npm): 이미지 빌드(pip/npm/베이스 이미지)에 필요"; else warn "닿지 않는 곳:$NET" "이미지를 새로 빌드하려면 인터넷이 필요하다. 오프라인이면 이미 만든 이미지를 쓰는 --reuse-build 만 가능(소스를 바꿨다면 안 된다). 프록시가 필요하면 HTTP(S)_PROXY 설정"; fi
  else
    warn "curl 이 없어 인터넷 도달을 확인하지 못했다" "curl 설치(선택). 이미지 빌드에는 인터넷이 필요하다"
  fi
  # --- 고정 포트 금지
  if grep -nE '^[[:space:]]*-[[:space:]]*"?([0-9.]+:)?[0-9]+:[0-9]+"?[[:space:]]*$' "$DEPLOY_ROOT/compose.test.yaml" >/dev/null 2>&1; then fail "compose.test.yaml 에 고정 호스트 포트가 있다" "시험 구성은 \"127.0.0.1::8080\" 처럼 Docker 가 포트를 배정하게 한다"; else ok "고정 포트 없음: 시험 구성의 호스트 포트는 Docker 가 배정하고 임시 레지스트리만 빈 포트를 고른다"; fi
fi
echo; if [ $FAILS = 0 ]; then echo "doctor: 통과 (WARN $WARNS)"; else echo "doctor: FAIL $FAILS건 (WARN $WARNS) -- 위 해결 방법을 따른 뒤 다시 실행. 건너뛰기: DEPLOY_SKIP_DOCTOR=1"; fi
exit $([ $FAILS = 0 ] && echo 0 || echo 1)
