#!/usr/bin/env bash
# 실제 LLM 데모용 중립 LoRA 패키지(학습하지 않은 시험용 대체, lora_B=0이라 출력은 기반 모델과 같다)를 만든다. Docker 불필요.
# 사용: scripts/make-llm-package.sh <프로파일 이름, 예: gpu-12g> <출력 폴더> [--adapter-a DIR --adapter-b DIR --prompt-a FILE --prompt-b FILE]
# 어댑터 인자 네 개를 모두 주면 중립 LoRA 대신 학습 서버에서 가져온 진짜 어댑터를 같은 구조의 패키지로 만든다(scripts/llm_attach_package.py). --check-only 를 더하면 검사만 하고 아무것도 만들지 않는다(model-runtime·boundary_contracts 불필요).
#   기반 모델(adapter_config.json 의 base_model_name_or_path)이 프로파일과 다르거나 순위가 max_lora_rank 를 넘으면 거부(종료 코드 2). 평가하지 않는다. 프롬프트는 학습에 쓴 파일이어야 한다.
# model-runtime 리포지토리를 직접 읽지 않고 태그($DEPLOY_MR_TAG, 기본은 lib.sh 의 DEPLOY_MR_TAG)의 git archive 에서 scripts/make_neutral_package.py 와
# profiles/<이름>.json 을 꺼내 deploy 전용 .venv 의 python 으로 실행한다(표준 라이브러리 + boundary-contracts 만 쓴다).
# 기반 모델의 차원(Qwen3 등)은 코드에 박지 않고 Hugging Face config.json 을 고정 리비전으로 받아 쓴다(build/hf-config/ 에 보관, sha256 검사).
# 시스템 프롬프트는 test/llm-demo/lora_{a,b}.system.txt(학습 데이터의 system 메시지, model-lab 리포 prompts/ 에서 복사한 데모 입력)로 바꿔 넣는다.
# 결과: <출력>/LORA_A, LORA_B (adapter/ 와 manifest.json), SUMMARY.json. 같은 입력이면 같은 바이트(결정적).
set -euo pipefail
DEPLOY_NO_DOCKER=1
source "$(dirname "$0")/lib.sh"
case "${1:-}" in -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0;; esac
[ $# -ge 2 ] || { sed -n '2,3p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
NAME=$1; OUT=$2; shift 2
AD_A=""; AD_B=""; PR_A=""; PR_B=""; CHECK_ONLY=0
while [ $# -gt 0 ]; do case "$1" in
  --adapter-a) [ $# -ge 2 ] || { echo "--adapter-a 에는 디렉터리가 필요하다" >&2; exit 2; }; AD_A=$2; shift 2;;
  --adapter-b) [ $# -ge 2 ] || { echo "--adapter-b 에는 디렉터리가 필요하다" >&2; exit 2; }; AD_B=$2; shift 2;;
  --prompt-a) [ $# -ge 2 ] || { echo "--prompt-a 에는 파일이 필요하다" >&2; exit 2; }; PR_A=$2; shift 2;;
  --prompt-b) [ $# -ge 2 ] || { echo "--prompt-b 에는 파일이 필요하다" >&2; exit 2; }; PR_B=$2; shift 2;;
  --check-only) CHECK_ONLY=1; shift;;
  *) echo "알 수 없는 인자: $1" >&2; exit 2;; esac; done
ATTACH=0
if [ -n "$AD_A$AD_B$PR_A$PR_B" ]; then
  [ -n "$AD_A" ] && [ -n "$AD_B" ] && [ -n "$PR_A" ] && [ -n "$PR_B" ] || { echo "--adapter-a --adapter-b --prompt-a --prompt-b 는 네 개를 모두 준다" >&2; exit 2; }
  ATTACH=1
fi
[[ "$NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "프로파일 이름은 소문자·숫자·하이픈이다 (예: gpu-12g): $NAME" >&2; exit 2; }
[ -x "$VENV/bin/python" ] || die "가상환경이 없다: bash scripts/prepare-host.sh venv 후 wheels (boundary-contracts 필요)"
SRC=$(mktemp -d "${TMPDIR:-/tmp}/deploy-mrpkg.XXXXXX"); trap 'rm -rf "$SRC"' EXIT
git -C "$WORKSPACE/model-runtime" archive "$DEPLOY_MR_TAG" scripts src profiles | tar -x -C "$SRC" || die "model-runtime $DEPLOY_MR_TAG 태그에서 꺼내지 못했다"
[ -f "$SRC/profiles/$NAME.json" ] || die "프로파일이 없다: profiles/$NAME.json ($DEPLOY_MR_TAG). 있는 것: $(ls "$SRC/profiles" | tr '\n' ' ')"
if [ $ATTACH = 1 ]; then   # 진짜 어댑터(--check-only: 검사만): 기반 모델 차원이 필요 없다(어댑터를 새로 만들지 않는다). 검사는 llm_attach_package.py
  if [ $CHECK_ONLY = 1 ]; then   # 검사만(이미지 빌드 전에 거부하려고): 표준 라이브러리만 쓴다
    PYTHONDONTWRITEBYTECODE=1 "$VENV/bin/python" "$DEPLOY_ROOT/scripts/llm_attach_package.py" "$OUT" --check-only --profile "$SRC/profiles/$NAME.json" \
      --adapter-a "$AD_A" --adapter-b "$AD_B" --prompt-a "$PR_A" --prompt-b "$PR_B" || exit 2
    exit 0
  fi
  rm -rf "$OUT.tmp"; mkdir -p "$OUT.tmp"
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$SRC/src" "$VENV/bin/python" "$DEPLOY_ROOT/scripts/llm_attach_package.py" "$OUT.tmp" --profile "$SRC/profiles/$NAME.json" \
    --adapter-a "$AD_A" --adapter-b "$AD_B" --prompt-a "$PR_A" --prompt-b "$PR_B" >/dev/null || { rm -rf "$OUT.tmp"; echo "어댑터 패키지 생성이 거부되었다(위 사유). 아무것도 만들지 않았다" >&2; exit 2; }
  rm -rf "$OUT"; mv "$OUT.tmp" "$OUT"; : > "$OUT/ATTACHED"
  echo "어댑터 패키지: $OUT (프로파일 $NAME, 기반 모델 $("$VENV/bin/python" -c 'import json,sys;print(json.load(open(sys.argv[1]))["base_model"])' "$SRC/profiles/$NAME.json"), model-runtime $DEPLOY_MR_TAG, 평가하지 않음)"
  exit 0
fi
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
