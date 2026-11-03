#!/usr/bin/env bash
# 지원하는 모든 compose 조합(기본, 단독 overlay, 스크립트의 COMPOSE_EXTRA 조합: scripts/compose_combos.py list)이 `docker compose config -q` 를 통과하고,
# 프로필로 꺼지는 서비스에 필수로 의존하는 서비스가 같은 프로필인지 본다(외부 추론 모드에서 사이드카만 남아 compose 가 거부한 사고). Docker 데몬이 없어도 compose 파일만 읽는다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"; detect_docker 2>/dev/null || true
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; mkdir -p "$T/secrets/tokens"
# 해석에 필요한 값은 더미다(잠금의 외부 이미지 줄 + 서비스 digest 더미, 레지스트리 주소, 공개 주소)
cp "$DEPLOY_ROOT/locks/images.lock" "$T/lock"
for v in $(grep -ohE '[A-Z_]+_DIGEST' "$DEPLOY_ROOT"/compose*.yaml "$DEPLOY_ROOT"/test/compose*.yaml "$DEPLOY_ROOT"/demo/compose*.yaml | sort -u); do grep -q "^$v=" "$T/lock" || echo "$v=sha256:$(printf '%064d' 1)" >> "$T/lock"; done
echo "DEPLOY_REGISTRY=127.0.0.1:5000" > "$T/reg.env"
export DEPLOY_LOCK="$T/lock" DEPLOY_REGISTRY_ENV="$T/reg.env" SECRETS_DIR="$T/secrets" GATEWAY_PUBLIC_URL=https://localhost:8443 GATEWAY_HOST_NAMES=localhost
F=0; N=0
while IFS= read -r combo; do
  N=$((N+1)); abs=""; for f in ${combo#ALONE }; do abs="$abs $DEPLOY_ROOT/$f"; done
  case "$combo" in ALONE\ *) alone=1;; *) alone=0;; esac
  # 호출자가 정해 주는 필수 변수(`:?`)는 더미를 채워 다시 해석한다(변수 이름은 compose 가 알려 준다). 값이 맞는지가 아니라 조합이 합쳐지는지를 본다
  ( okx=1; for _ in $(seq 30); do if [ $alone = 1 ]; then out=$("$DOCKER" compose -p deploy-combos -f ${abs# } config -q 2>&1) && { okx=0; break; }; else out=$(COMPOSE_EXTRA="${abs# }" dc deploy-combos config -q 2>&1) && { okx=0; break; }; fi
     
      v=$(echo "$out" | sed -n 's/.*required variable \([A-Z0-9_]*\) is missing.*/\1/p' | head -1); [ -n "$v" ] || break
      case "$v" in *_PORT) export "$v=18443";; *) export "$v=$T/dummy"; touch "$T/dummy";; esac; done; echo "$out" > "$T/out"; exit $okx ) ; rcx=$?; out=$(cat "$T/out")
  if [ $rcx = 0 ]; then echo "  PASS config -q: ${combo:-기본}"
  else echo "  FAIL config -q: ${combo:-기본} :: $(echo "$out" | tail -1 | cut -c1-200)"; F=$((F+1)); fi
done < <("$DEPLOY_PY" "$DEPLOY_ROOT/scripts/compose_combos.py" list)
if "$DEPLOY_PY" "$DEPLOY_ROOT/scripts/compose_combos.py" deps; then :; else F=$((F+1)); fi
[ $F = 0 ] && echo "통과: compose 조합 ${N}개" || { echo "실패: $F건"; exit 1; }
