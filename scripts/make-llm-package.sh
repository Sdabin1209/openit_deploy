#!/usr/bin/env bash
# 실제 LLM 데모용 중립 LoRA 패키지(학습하지 않은 시험용 대체, lora_B=0이라 출력은 기반 모델과 같다)를 만든다. Docker 불필요.
# 사용: scripts/make-llm-package.sh <프로파일 이름, 예: gpu-12g> <출력 폴더>
# model-runtime 리포지토리를 직접 읽지 않고 태그($DEPLOY_MR_TAG, 기본은 lib.sh 의 DEPLOY_MR_TAG)의 git archive 에서 scripts/make_neutral_package.py 와
# profiles/<이름>.json 을 꺼내 deploy 전용 .venv 의 python 으로 실행한다(표준 라이브러리 + boundary-contracts 만 쓴다).
# 기반 모델의 차원(Qwen3 등)은 코드에 박지 않고 Hugging Face config.json 을 고정 리비전으로 받아 쓴다(build/hf-config/ 에 보관, sha256 검사).
# 시스템 프롬프트는 test/llm-demo/lora_{a,b}.system.txt(학습 데이터의 system 메시지, model-lab 리포 prompts/ 에서 복사한 데모 입력)로 바꿔 넣는다.
# 결과: <출력>/LORA_A, LORA_B (adapter/ 와 manifest.json), SUMMARY.json. 같은 입력이면 같은 바이트(결정적).
set -euo pipefail
DEPLOY_NO_DOCKER=1
source "$(dirname "$0")/lib.sh"
case "${1:-}" in -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0;; esac
[ $# -eq 2 ] || { sed -n '2,3p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
NAME=$1; OUT=$2
[[ "$NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "프로파일 이름은 소문자·숫자·하이픈이다 (예: gpu-12g): $NAME" >&2; exit 2; }
[ -x "$VENV/bin/python" ] || die "가상환경이 없다: bash scripts/prepare-host.sh venv 후 wheels (boundary-contracts 필요)"
SRC=$(mktemp -d "${TMPDIR:-/tmp}/deploy-mrpkg.XXXXXX"); trap 'rm -rf "$SRC"' EXIT
git -C "$WORKSPACE/model-runtime" archive "$DEPLOY_MR_TAG" scripts src profiles | tar -x -C "$SRC" || die "model-runtime $DEPLOY_MR_TAG 태그에서 꺼내지 못했다"
[ -f "$SRC/profiles/$NAME.json" ] || die "프로파일이 없다: profiles/$NAME.json ($DEPLOY_MR_TAG). 있는 것: $(ls "$SRC/profiles" | tr '\n' ' ')"
# 기반 모델의 config.json: 확인한 것만 쓴다(리비전과 sha256 고정). 표에 없는 모델은 "미확인"으로 중단한다.
BASE=$("$VENV/bin/python" -c 'import json,sys;print(json.load(open(sys.argv[1]))["base_model"])' "$SRC/profiles/$NAME.json")
case "$BASE" in
  Qwen/Qwen3-1.7B) HF_REV=70d244cc86ccca08cf5af4e1e306ecf908b1ad5e; HF_SHA=1ddb5b89ebc90dcb417a45c213d818577e65976454d29385c8f6140771d95197;;   # 2026-10-27 에 받아 sha256 을 기록한 값
  *) die "기반 모델 $BASE 의 config.json 리비전·sha256 이 이 스크립트에 기록되지 않았다(미확인). 받아서 확인한 뒤 case 에 추가하라";;
esac
CFG="$DEPLOY_ROOT/build/hf-config/${BASE//\//__}.config.json"
if [ ! -f "$CFG" ]; then
  mkdir -p "$(dirname "$CFG")"
  curl -fsSL -m 60 -o "$CFG.tmp" "https://huggingface.co/$BASE/resolve/$HF_REV/config.json" || { rm -f "$CFG.tmp"; die "$BASE 의 config.json 을 받지 못했다(미확인: 차원을 추정하지 않는다). 인터넷 도달을 확인하라"; }
  mv "$CFG.tmp" "$CFG"
fi
[ "$(sha256sum "$CFG" | cut -d' ' -f1)" = "$HF_SHA" ] || die "$CFG 의 sha256 이 기록된 값($HF_SHA)과 다르다. 지우고 다시 받거나 기록을 확인하라"
rm -rf "$OUT"; mkdir -p "$OUT"
"$VENV/bin/python" "$SRC/scripts/make_neutral_package.py" "$OUT" --profile "$SRC/profiles/$NAME.json" --model-config "$CFG" \
  --system-prompt-a "$DEPLOY_ROOT/test/llm-demo/lora_a.system.txt" --system-prompt-b "$DEPLOY_ROOT/test/llm-demo/lora_b.system.txt" >/dev/null
[ -f "$OUT/SUMMARY.json" ] || die "패키지 생성 실패 (SUMMARY.json 없음)"
echo "중립 LoRA 패키지: $OUT (프로파일 $NAME, 기반 모델 $BASE, model-runtime $DEPLOY_MR_TAG, 시스템 프롬프트 = 데모 입력 파일)"
