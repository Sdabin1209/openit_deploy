#!/usr/bin/env bash
# 운영·테스트 서버 형태 확인: 소스(형제 리포, build/)가 없는 deploy 리포 사본 하나와 레지스트리의 digest 이미지만으로 서비스가 뜨는가.
#  1) 이 워크스페이스의 로컬 이미지(build/images.env)를 임시 레지스트리에 올려 digest 잠금을 만든다(운영에서는 영역 CI가 한 일).
#  2) deploy 리포의 커밋된 내용만 빈 폴더에 clone 한다(형제 리포·build/·.venv 없음).
#  3) 그 사본에서 gen-secrets.sh -> up.sh 로 운영 구성(compose.yaml만)을 띄워 모든 서비스가 healthy 인지 본다. 끝나면 모두 지운다.
# 전제: 로컬에 deploy-build 이미지가 있다(scripts/build-images.sh 를 한 번 돌린 뒤). 고정 포트를 쓰지 않는다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
ID=$$; T=$(mktemp -d "${TMPDIR:-/tmp}/deploy-standalone-XXXXXX"); P="deploy-standalone-$ID"
export DEPLOY_LOCK="$T/images.lock" DEPLOY_REGISTRY_ENV="$T/registry.env" REGISTRY_PROJECT="deploy-standalone-reg-$ID" REGISTRY_HOST_BIND=0.0.0.0 REGISTRY_HOST_PORT= SECRETS_DIR="$T/secrets"
FAILS=0; ok() { echo "  [PASS] $1"; }; ng() { echo "  [FAIL] $1"; FAILS=$((FAILS+1)); }
cleanup() {
  ( cd "$T/deploy" 2>/dev/null && dc "$P" down -v --remove-orphans >/dev/null 2>&1 )
  bash "$DEPLOY_ROOT/scripts/registry.sh" down -v >/dev/null 2>&1
  for i in $("$DOCKER" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | tr -d '\r' | grep -E '^127\.0\.0\.1:[0-9]+/openit/'); do "$DOCKER" rmi -f "$i" >/dev/null 2>&1; done
  rm -rf "$T"
}
trap cleanup EXIT
[ -f "$DEPLOY_ROOT/build/images.env" ] || { echo "build/images.env 가 없다: 먼저 scripts/build-images.sh"; exit 2; }
grep -E '^(GATEWAY|REGISTRY|UTIL)_IMAGE=' "$DEPLOY_ROOT/locks/images.lock" > "$DEPLOY_LOCK"
echo "== 1) 임시 레지스트리에 올려 digest 잠금을 만든다"
bash "$DEPLOY_ROOT/scripts/registry.sh" up >/dev/null 2>&1 && ok "레지스트리 기동" || { ng "레지스트리 기동"; exit 1; }
bash "$DEPLOY_ROOT/scripts/publish-images.sh" >/dev/null 2>&1 && ok "publish-images.sh (잠금 생성)" || { ng "publish-images.sh"; exit 1; }
echo "== 2) deploy 리포의 커밋된 내용만 빈 폴더에 clone (형제 리포·build/·.venv 없음)"
git clone -q --no-hardlinks "$DEPLOY_ROOT" "$T/deploy" && ok "clone ($T/deploy)" || { ng clone; exit 1; }
[ ! -e "$T/deploy/build" ] && [ ! -e "$T/deploy/.venv" ] && [ -z "$(ls "$T" | grep -v -E '^(deploy|images.lock|registry.env|images.lock.lock|history)$')" ] && ok "사본 옆에 형제 리포·build/·.venv 가 없다" || ng "사본 환경이 깨끗하지 않다"
echo "== 3) 사본에서 비밀 생성 -> up.sh (compose.yaml만, 시험 덮어쓰기 없음)"
( cd "$T/deploy" && bash scripts/gen-secrets.sh "$SECRETS_DIR" >/dev/null 2>&1 ) && ok "gen-secrets.sh" || { ng "gen-secrets.sh"; exit 1; }
( cd "$T/deploy" && bash scripts/up.sh "$P" > "$T/up.log" 2>&1 ) && ok "up.sh: 모든 서비스 healthy (워크스페이스 없이)" || { ng "up.sh"; tail -5 "$T/up.log"; }
BAD=$( cd "$T/deploy" && dc "$P" ps -a --format '{{.Name}} {{.Status}}' 2>/dev/null | grep -v -E 'healthy|Exited \(0\)' ); [ -z "$BAD" ] && ok "컨테이너가 모두 healthy (일회성 작업은 Exited 0)" || { ng "healthy 가 아닌 컨테이너: $BAD"; }
echo; [ "$FAILS" = 0 ] && echo "check-standalone: 전부 통과" || echo "check-standalone: 실패 $FAILS건"
exit $([ "$FAILS" = 0 ] && echo 0 || echo 1)
