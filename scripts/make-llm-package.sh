#!/usr/bin/env bash
# 실제 LLM 데모용 중립 LoRA 패키지(학습하지 않은 시험용 대체, lora_B=0이라 출력은 기반 모델과 같다)를 만든다. Docker 불필요.
# 사용: scripts/make-llm-package.sh <프로파일 이름, 예: gpu-12g> <출력 폴더>
# model-runtime 리포지토리를 직접 읽지 않고 태그($DEPLOY_MR_TAG, 기본은 lib.sh 의 DEPLOY_MR_TAG)의 git archive 에서 scripts/make_neutral_package.py 와
# profiles/<이름>.json 을 꺼내 deploy 전용 .venv 의 python 으로 실행한다(표준 라이브러리 + boundary-contracts 만 쓴다).
# 결과: <출력>/LORA_A, LORA_B (adapter/ 와 manifest.json), SUMMARY.json. 같은 입력이면 같은 바이트(결정적).
set -euo pipefail
DEPLOY_NO_DOCKER=1
source "$(dirname "$0")/lib.sh"
case "${1:-}" in -h|--help) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0;; esac
[ $# -eq 2 ] || { sed -n '2,3p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
NAME=$1; OUT=$2
[[ "$NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "프로파일 이름은 소문자·숫자·하이픈이다 (예: gpu-12g): $NAME" >&2; exit 2; }
[ -x "$VENV/bin/python" ] || die "가상환경이 없다: bash scripts/prepare-host.sh venv 후 wheels (boundary-contracts 필요)"
SRC=$(mktemp -d "${TMPDIR:-/tmp}/deploy-mrpkg.XXXXXX"); trap 'rm -rf "$SRC"' EXIT
git -C "$WORKSPACE/model-runtime" archive "$DEPLOY_MR_TAG" scripts src profiles | tar -x -C "$SRC" || die "model-runtime $DEPLOY_MR_TAG 태그에서 꺼내지 못했다"
[ -f "$SRC/profiles/$NAME.json" ] || die "프로파일이 없다: profiles/$NAME.json ($DEPLOY_MR_TAG). 있는 것: $(ls "$SRC/profiles" | tr '\n' ' ')"
rm -rf "$OUT"; mkdir -p "$OUT"
"$VENV/bin/python" "$SRC/scripts/make_neutral_package.py" "$OUT" --profile "$SRC/profiles/$NAME.json" >/dev/null
[ -f "$OUT/SUMMARY.json" ] || die "패키지 생성 실패 (SUMMARY.json 없음)"
echo "중립 LoRA 패키지: $OUT (프로파일 $NAME, model-runtime $DEPLOY_MR_TAG)"
