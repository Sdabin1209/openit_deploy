#!/usr/bin/env bash
# E2E 단계 3의 GPU 경로(E2E_GPU=1): gpu-dev 호스트에서 model-lab 파이프라인을 짧게 돌리고 결과를 model-registry에 HTTP로 게시한다.
# !! 이 환경에서는 실행해 보지 않았다(미검증). 기본은 끔. model-lab 런북("GPU 호스트(gpu-dev) 실행", D47)을 따른다 !!
# 사용: e2e_gpu.sh <model-registry 호스트 포트> <쓰기 토큰 파일>   표준 출력: 게시한 패키지 참조 JSON {"LORA_A": {...}, "LORA_B": {...}} (미구현 부분은 종료 코드 78)
# 알려진 한계: model-lab의 gpu-dev 설정은 시험용 데이터셋 저장소(fixtures/store, model-lab 자체 시험 자료)를 읽는다. 단계 2의 synthetic-data 산출물을
#   읽게 하려면 model-lab 설정의 dataset_store 팩토리(파일 저장소)가 필요한데 런북에 이름이 없다(CR-D12). 그래서 이 경로의 계보 dataset은 단계 2의 것이 아니다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
MR_PORT=${1:?model-registry 호스트 포트}; TOKFILE=${2:?쓰기 토큰 파일}
HOST=${GPU_HOST:-gpu-dev}
# 호스트 SSH가 한 번 실패하면 멈춘다(반복 재시도 금지, model-lab 런북)
ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST" true || { echo "gpu-dev에 접속하지 못했다. 멈춘다(재시도 루프 없음)" >&2; exit 75; }
SRC="$DEPLOY_ROOT/build/ctx/model-lab-gpu"; rm -rf "$SRC"; mkdir -p "$SRC"
git -C "$WORKSPACE/model-lab" archive HEAD | tar -x -C "$SRC"
echo "model-lab 코드를 $HOST 로 보낸다(비밀 값 없음)" >&2
rsync -a --exclude .venv --exclude .git --exclude runs "$SRC"/ "$HOST":openit-gpu/model-lab/ >&2
echo "GPU 호스트에서 학습·평가·패키징·게시: 레지스트리에는 역방향 터널(-R)로 닿는다" >&2
TOKEN=$(cat "$TOKFILE")
ssh -R "18080:127.0.0.1:$MR_PORT" "$HOST" "cd ~/openit-gpu/model-lab && MODEL_REGISTRY_URL=http://127.0.0.1:18080 MODEL_REGISTRY_WRITE_TOKEN=$TOKEN \
  flock -w 1800 ~/openit-gpu/.gpu.lock timeout 3000 .venv/bin/python -m model_lab run --config configs/gpu-dev-http-publish.yaml" >&2
# 게시된 참조는 호출자(e2e_steps.py)가 model-registry의 list_ids/list_versions로 읽는다
echo '{"note": "published via gpu-dev; refs are read back from model-registry by the caller"}'
