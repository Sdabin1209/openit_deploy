#!/usr/bin/env bash
# compose 파일이 이미지를 digest로만 참조하는지(태그 금지, D07) 검사한다. 시험 대역 파일은 이미지를 정의하지 않아야 한다.
set -euo pipefail
DEPLOY_NO_DOCKER=1   # 파일만 검사한다
source "$(dirname "$0")/lib.sh"
bad=0
for f in compose.yaml compose.registry.yaml compose.test.yaml compose.external-inference.yaml compose.inference.yaml; do
  while IFS= read -r line; do
    ref=$(echo "$line" | sed 's/^[[:space:]]*image:[[:space:]]*//')
    # 허용: ${VAR} 로 시작하는 참조(잠금 파일이 digest를 채운다). 그 변수는 아래에서 잠금 파일이 digest인지 검사한다.
    case "$ref" in *'@${'*|'${'*) ;; *) echo "digest가 아닌 이미지 참조: $f: $line"; bad=1;; esac
  done < <(grep -E '^[[:space:]]*image:' "$DEPLOY_ROOT/$f" || true)
done
LOCK=${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}
while IFS='=' read -r k v; do
  case "$k" in *_IMAGE) [[ "$v" == *@sha256:* ]] || { echo "잠금 파일 $k 에 digest가 없다: $v"; bad=1; };;
               *_DIGEST) [[ "$v" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "잠금 파일 $k 형식 오류: $v"; bad=1; };; esac
done < <(grep -v '^#' "$LOCK" | grep '=')
[ $bad = 0 ] && echo "compose: 모든 이미지가 digest로 참조된다"
exit $bad
