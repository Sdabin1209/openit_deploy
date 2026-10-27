#!/usr/bin/env bash
# 사전 점검(읽기 전용, 비밀 값을 출력하지 않는다). 깨끗한 머신에서 e2e.sh / up.sh 전에 돈다. 항목마다 OK/WARN/FAIL 과 해결 방법 한 줄을 낸다.
# 사용: scripts/doctor.sh [--up] [--inference <URL>]
#   --llm              실제 LLM(GPU) 준비: GPU 컨테이너 접근, 프로파일 VRAM 대 GPU VRAM, 도커 디스크, huggingface.co 도달 (환경 변수 DEMO_LLM_PROFILE)
#   --inference <URL>  외부 추론 서버(D72)에 이 호스트에서 닿는지: /healthz, /readyz, 토큰이 있으면 /v1/info (토큰은 INFERENCE_TOKEN 또는 INFERENCE_TOKEN_FILE, 값은 출력하지 않는다)
#   기본: 빌드·E2E 에 필요한 전부(소스 워크스페이스 포함).  --up: 서버에서 띄우기만 할 때(git·형제 리포·태그·빌드 의존 점검을 건너뛴다)
# e2e.sh / up.sh 는 시작에서 이것을 부르고 FAIL 이 있으면 멈춘다. 건너뛰기: DEPLOY_SKIP_DOCTOR=1
# 환경 문제를 코드로 숨기지 않는다: 진단하고 고치는 법을 안내할 뿐 아무것도 바꾸지 않는다.
set -uo pipefail
DEPLOY_NO_DOCKER=1
source "$(dirname "$0")/lib.sh"
UP_ONLY=0; INF_URL=""; LLM=0
while [ $# -gt 0 ]; do case "$1" in
  --up) UP_ONLY=1; shift;;
  --llm) LLM=1; shift;;
  --inference) [ $# -ge 2 ] || { echo "--inference 에는 URL이 필요하다" >&2; exit 2; }; INF_URL=$2; shift 2;;
  --inference=*) INF_URL=${1#*=}; shift;;
  -h|--help) sed -n '3,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  *) echo "알 수 없는 인자: $1 (사용: doctor.sh [--up] [--llm] [--inference <URL>])" >&2; exit 2;; esac; done
case "$INF_URL" in ""|http://*|https://*) ;; *) echo "--inference 에는 http:// 또는 https:// 주소가 필요하다: $INF_URL" >&2; exit 2;; esac
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
# --- 실제 LLM(GPU) 준비(D72/D73): 읽기 전용 점검. 컨테이너에서 GPU가 보여야 하고, 프로파일이 GPU 메모리에 맞아야 한다
if [ $LLM = 1 ]; then
  echo "== 실제 LLM(GPU) 준비"
  CUDA_IMG="nvidia/cuda:12.4.1-base-ubuntu22.04"
  PROFILE="${DEMO_LLM_PROFILE:-/app/profiles/gpu-12g.json}"
  if [ -z "$D" ]; then fail "docker 데몬을 쓸 수 없어 GPU 점검을 건너뛴다" "위의 docker 항목을 먼저 해결"
  else
    GPU_OUT=$("$D" run --rm --gpus all "$CUDA_IMG" nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>&1); GRC=$?
    if [ $GRC = 0 ] && [ -n "$GPU_OUT" ]; then
      ok "GPU 컨테이너 접근: $(echo "$GPU_OUT" | head -1 | tr -d '\r') MiB$( [ "$(echo "$GPU_OUT" | wc -l)" -gt 1 ] && echo " 외 $(( $(echo "$GPU_OUT" | wc -l) - 1 ))장")"
      MAXMIB=$(echo "$GPU_OUT" | tr -d '\r' | awk -F', *' '{gsub(/[^0-9]/,"",$NF); if($NF+0>m)m=$NF+0} END{print m+0}')
      NEEDG=$(basename "$PROFILE" | sed -n 's/.*-\([0-9][0-9]*\)g\.json$/\1/p')
      if [ -z "$NEEDG" ]; then warn "프로파일 이름($PROFILE)에서 필요한 VRAM(예: -12g)을 읽지 못해 GPU 메모리 비교를 건너뛴다" "DEMO_LLM_PROFILE 을 gpu-12g.json 처럼 크기가 이름에 든 프로파일로 지정하거나, 프로파일의 gpu_memory_utilization 으로 직접 판단"
      elif [ "$MAXMIB" -lt $(( NEEDG * 1024 * 95 / 100 )) ]; then fail "프로파일 $(basename "$PROFILE") 는 ${NEEDG}GB급인데 GPU 메모리는 ${MAXMIB}MiB" "더 작은 GPU용 프로파일을 DEMO_LLM_PROFILE 로 지정(model-runtime 의 profiles/ 안내)하거나 더 큰 GPU 사용"
      else ok "프로파일 $(basename "$PROFILE") (${NEEDG}GB급) <= GPU 메모리 ${MAXMIB}MiB (프로파일 이름의 크기 기준, 실제 사용량은 측정 전)"; fi
    else
      if echo "$GPU_OUT" | grep -qi "pull access denied\|manifest unknown\|no such host\|timeout\|TLS\|dial tcp"; then
        fail "GPU 점검용 이미지 $CUDA_IMG 를 받지 못했다" "인터넷(Docker Hub) 접근을 확인하거나 이 이미지를 미리 받아 둔다: docker pull $CUDA_IMG"
      elif [ $WSL = 1 ]; then
        fail "GPU 컨테이너를 실행하지 못했다 (docker run --gpus all $CUDA_IMG nvidia-smi)" "Windows에 WSL을 지원하는 NVIDIA 드라이버를 설치하고, Docker Desktop의 WSL2 백엔드에서 GPU 지원이 켜져 있는지 확인(Docker Desktop 문서의 GPU support)"
      else
        fail "GPU 컨테이너를 실행하지 못했다 (docker run --gpus all $CUDA_IMG nvidia-smi)" "리눅스: NVIDIA 드라이버와 nvidia-container-toolkit 설치 후 sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker"
      fi
    fi
    # 도커 디스크: GPU 이미지 약 13GB + HF 캐시 약 4GB(Qwen3-1.7B 추정) (서버에서 측정 전). 회수 가능량을 함께 보인다
    DF=$("$D" system df --format '{{.Type}}: {{.Size}} (회수 가능 {{.Reclaimable}})' 2>/dev/null | tr '\n' ';')
    [ -n "$DF" ] && echo "  [정보] docker system df -- $DF"
    ROOT=$("$D" info --format '{{.DockerRootDir}}' 2>/dev/null | tr -d '\r')
    AV=""; [ -n "$ROOT" ] && [ -d "$ROOT" ] && AV=$(df -Pk "$ROOT" 2>/dev/null | awk 'NR==2{printf "%d", $4/1048576}')
    if [ -z "$AV" ]; then warn "도커 저장 위치의 여유 디스크를 이 셸에서 읽지 못했다 (Docker Desktop은 VM/윈도 드라이브 안)" "GPU 이미지 약 13GB + HF 캐시 약 4GB(Qwen3-1.7B 추정)(측정 전)가 들어갈 여유를 도커 디스크 위치에서 직접 확인(docs/RUN.md). 줄이기: docker system df 로 회수 가능량 확인 후 사용자가 판단해 정리"
    elif [ "$AV" -lt 25 ]; then warn "도커 저장 위치 ($ROOT) 여유 약 ${AV}GB (권장 25GB 이상)" "공간 확보: docker system df 로 회수 가능량을 보고 사용자가 판단해 정리 (docs/RUN.md)"
    else ok "도커 저장 위치 ($ROOT) 여유 약 ${AV}GB"; fi
  fi
  if command -v curl >/dev/null 2>&1; then
    HC=$(curl -s -o /dev/null -m 8 -w '%{http_code}' https://huggingface.co 2>/dev/null || true)
    if [ -n "$HC" ] && [ "$HC" != 000 ]; then ok "huggingface.co 도달 (HTTP $HC): 첫 기동의 모델 내려받기(약 4GB(Qwen3-1.7B 추정))에 필요"
    else warn "huggingface.co 에 닿지 않는다" "인터넷/프록시를 확인하거나, 오프라인이면 hf-cache 볼륨을 미리 채우고 HF_HUB_OFFLINE=1 (docs/RUN.md)"; fi
  else warn "curl 이 없어 huggingface.co 도달을 확인하지 못했다" "curl 설치(선택)"; fi
fi

# --- 외부 추론 서버 도달성(D72): 호출자(이 호스트)에서 본다. 서버가 release-gate 에 닿는 것은 서버 쪽 조건이라 여기서 대신 확인하지 못한다.
if [ -n "$INF_URL" ]; then
  echo "== 외부 추론 서버 $INF_URL"
  INF_URL=${INF_URL%/}
  if ! command -v curl >/dev/null 2>&1; then fail "curl 이 없어 추론 서버 도달을 확인하지 못했다" "curl 설치"
  else
    HINT="주소·포트가 맞는지, 서버가 떠 있는지(서버 호스트에서 docker compose -p deploy-inference ps), 방화벽·보안 그룹이 호출자 -> 서버 포트를 허용하는지, 서버의 INFERENCE_BIND 가 외부에서 닿는 주소인지 확인"
    hc=$(curl -s -o /dev/null -m 6 -w '%{http_code}' "$INF_URL/healthz" 2>/dev/null || true)
    if [ "$hc" = 200 ]; then ok "추론 서버 /healthz 200"; else fail "추론 서버 /healthz 에 닿지 못했다 (응답 ${hc:-없음})" "$HINT"; fi
    if [ "$hc" = 200 ]; then
      rc=$(curl -s -o /dev/null -m 6 -w '%{http_code}' "$INF_URL/readyz" 2>/dev/null || true)
      if [ "$rc" = 200 ]; then ok "추론 서버 /readyz 200"
      else warn "추론 서버 /readyz 응답 ${rc:-없음} (살아 있으나 준비되지 않음)" "양방향 도달성: 서버가 release-gate 에 닿아야 한다. 서버 호스트에서 RELEASE_URL 로 닿는지, MODEL_RUNTIME_RELEASE_TOKEN(_FILE) 이 게이트 읽기 토큰인지 확인 (서버 로그: docker compose -p deploy-inference logs model-serving)"; fi
    fi
    TOKF="${INFERENCE_TOKEN_FILE:-}"; T=""
    if [ -n "$TOKF" ] && [ -r "$TOKF" ]; then T=$(tr -d '[:space:]' < "$TOKF")
    elif [ -n "${INFERENCE_TOKEN:-}" ]; then T=$INFERENCE_TOKEN; fi
    if [ -z "$T" ]; then warn "추론 서버 토큰이 없어 /v1/info 확인을 건너뛴다" "INFERENCE_TOKEN 환경 변수 또는 INFERENCE_TOKEN_FILE(토큰 하나가 든 파일)을 주고 다시 실행"
    elif [ "$hc" = 200 ]; then
      ic=$(printf 'header = "Authorization: Bearer %s"\n' "$T" | curl -s -o /dev/null -m 8 -w '%{http_code}' -K - "$INF_URL/v1/info" 2>/dev/null || true)
      case "$ic" in
        200) ok "추론 서버 /v1/info 200 (토큰 통과)";;
        401|403) fail "추론 서버가 토큰을 거부했다 (/v1/info $ic)" "서버의 MODEL_RUNTIME_TOKENS 에 이 호출자 토큰이 등록되어 있는지, 호출자 토큰 파일이 같은 값인지 확인 (값은 출력하지 않는다)";;
        *) fail "추론 서버 /v1/info 응답 이상 (${ic:-없음})" "서버 로그 확인: docker compose -p deploy-inference logs model-serving";; esac
    fi
    T=""
    echo "  [안내] 양방향 도달성: 호출자 -> 추론 서버(위 점검)와 추론 서버 -> release-gate(RELEASE_URL)가 모두 열려야 한다. 후자는 서버 호스트에서 확인한다."
  fi
fi

echo; if [ $FAILS = 0 ]; then echo "doctor: 통과 (WARN $WARNS)"; else echo "doctor: FAIL $FAILS건 (WARN $WARNS) -- 위 해결 방법을 따른 뒤 다시 실행. 건너뛰기: DEPLOY_SKIP_DOCTOR=1"; fi
exit $([ $FAILS = 0 ] && echo 0 || echo 1)
