#!/usr/bin/env bash
# gen-db-secrets-all.sh 는 실행별 잠금·레지스트리 파일(DEPLOY_LOCK, DEPLOY_REGISTRY_ENV)을 읽는다(E2E 는 임시 잠금에 digest 를 게시한다, 2026-11-05 E2E 가 고정 경로만 읽어 실패했다).
# 이미지가 없는 호스트에서도 돌도록 digest 를 찾는 단계까지만 본다: 임시 잠금에 digest 가 있으면 "잠금에 없다" 로 멈추지 않는다(그 뒤 이미지를 받지 못해 실패하는 것은 정상). 변이: 고정 경로를 읽는 옛 방식이면 "에 없다" 로 멈춘다.
set -uo pipefail
cd "$(dirname "$0")/.."; ID=$$; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; MUT="scripts/.gen-db-all.mut-$ID.sh"; trap 'rm -rf "$T" "$MUT"' EXIT
FAILS=0; ok() { echo "  [PASS] $1"; }; ng() { echo "  [FAIL] $1"; FAILS=$((FAILS+1)); }
printf 'SURVEY_DB_DIGEST=sha256:%064d\n' 0 > "$T/lock"; printf 'DEPLOY_REGISTRY=127.0.0.1:1\n' > "$T/reg.env"
[ -z "$(grep -c '^SURVEY_DB_DIGEST=' locks/images.lock | grep -v '^0$')" ] || { echo "SKIP: 실제 잠금에 SURVEY_DB_DIGEST 가 있어 변이를 구별할 수 없다"; exit 77; }
run() { SECRETS_DIR="$T/secrets" DEPLOY_LOCK="$T/lock" DEPLOY_REGISTRY_ENV="$T/reg.env" timeout 60 bash "$1" survey-db 2>&1; }
out=$(run scripts/gen-db-secrets-all.sh)
case "$out" in *"에 없다"*) ng "임시 잠금(DEPLOY_LOCK)의 digest 를 읽는다: '$out'" ;; *) ok "임시 잠금(DEPLOY_LOCK)의 digest 를 읽는다(digest 없음으로 멈추지 않는다)";; esac
printf '' > "$T/lock.empty"; out=$(SECRETS_DIR="$T/secrets" DEPLOY_LOCK="$T/lock.empty" DEPLOY_REGISTRY_ENV="$T/reg.env" timeout 60 bash scripts/gen-db-secrets-all.sh survey-db 2>&1)
case "$out" in *"$T/lock.empty"*"에 없다"*|*"에 없다"*"$T/lock.empty"*) ok "digest 가 없으면 오류 문구가 그 잠금 경로를 말한다";; *) ng "오류 문구가 쓴 잠금 경로를 말하지 않는다: '$out'";; esac
sed 's|^LOCK="${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}"; REGENV="${DEPLOY_REGISTRY_ENV:-$DEPLOY_ROOT/state/registry.env}"|LOCK="$DEPLOY_ROOT/locks/images.lock"; REGENV="$DEPLOY_ROOT/state/registry.env"|' scripts/gen-db-secrets-all.sh > "$MUT"
out=$(run "$MUT")
case "$out" in *"에 없다"*) ok "변이 확인: 고정 경로만 읽으면 임시 잠금의 digest 를 못 본다(시험이 껍데기가 아니다)";; *) ng "변이가 같은 결과를 냈다: '$out'";; esac
[ $FAILS = 0 ] && { echo "test-gen-db-secrets-all: 전부 통과"; exit 0; } || { echo "test-gen-db-secrets-all: 실패 $FAILS건"; exit 1; }
