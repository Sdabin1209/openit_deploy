#!/usr/bin/env bash
# check-versions.sh 자기 점검: 임시 워크스페이스에서 (1) 표와 같으면 통과 (2) 어긋나면 실패하고 파일:줄을 말한다 (3) kiosk-frontend·admin-console 의 Dockerfile ARG(BOUNDARY_CONTRACT[S])도 본다 (4) 문서·시험의 옛 표기는 무시한다.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/lib.sh" 2>/dev/null || DEPLOY_NO_DOCKER=1 source "$HERE/lib.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/head/shared"; cp "$HERE/../../head/shared/areas.json" "$T/head/shared/areas.json"
mkdir -p "$T/survey-service/docs" "$T/survey-service/tests" "$T/model-lab" "$T/synthetic-data" "$T/kiosk-frontend" "$T/admin-console"
BC=$DEPLOY_BC_TAG; MR=$DEPLOY_MR_TAG; TE=$DEPLOY_TE_TAG
printf 'x\ngit+ssh://git@github.com/Sdabin1209/openit_boundary-contracts.git@%s\ngit+ssh://git@github.com/Sdabin1209/openit_turn-engine.git@%s\n' "$BC" "$TE" > "$T/survey-service/requirements.txt"
printf 'BOUNDARY_TAG=${BOUNDARY_TAG:-%s}\n' "$BC" > "$T/model-lab/build.sh"
printf 'boundary-contracts @ git+ssh://git@github.com/x/openit_boundary-contracts.git@%s\n' "$DEPLOY_BC_TAG" > "$T/synthetic-data/requirements.lock"
printf 'ARG BC_SPEC="boundary-contracts @ git+ssh://git@github.com/x/openit_boundary-contracts.git@%s"\n' "$DEPLOY_BC_TAG" > "$T/synthetic-data/Dockerfile"   # dataset-store 이미지는 DS 태그(ADR 0032)
printf 'FROM x\nARG BOUNDARY_CONTRACT=%s\n' "$BC" > "$T/kiosk-frontend/Dockerfile"
printf 'FROM x\nARG BOUNDARY_CONTRACTS=%s\nLABEL io.openit.turn-engine="n/a"\n' "$BC" > "$T/admin-console/Dockerfile"
echo "옛 표기 boundary-contracts@v0.0.1" > "$T/survey-service/docs/old.md"; echo "BOUNDARY_TAG=v0.0.1" > "$T/survey-service/tests/old.sh"
export CHECK_VERSIONS_WORKSPACE="$T"; rc=0
out=$(bash "$HERE/check-versions.sh" 2>&1) && echo "ok: 표와 같으면 통과" || { echo "FAIL: 같은데 실패"; echo "$out"; rc=1; }
sed -i "s/@$MR\$/@v0.0.9/; s/openit_turn-engine.git@$TE/openit_turn-engine.git@v0.0.9/" "$T/survey-service/requirements.txt"
sed -i "s/$BC/v9.9.9/" "$T/model-lab/build.sh"
# 두 영역이 아직 v1.3.x 인 상태(계약 정렬 전): 실패하고 두 영역의 Dockerfile:줄을 말해야 한다
sed -i "s/$BC/v1.3.3/" "$T/kiosk-frontend/Dockerfile" "$T/admin-console/Dockerfile"
out=$(bash "$HERE/check-versions.sh" 2>&1); r=$?
{ [ $r = 1 ] && grep -q 'survey-service/requirements.txt:3: turn-engine v0.0.9' <<<"$out" && grep -q 'model-lab/build.sh:1: boundary-contracts v9.9.9' <<<"$out"; } && grep -q 'kiosk-frontend/Dockerfile:2: boundary-contracts v1.3.3' <<<"$out" && grep -q 'admin-console/Dockerfile:2: boundary-contracts v1.3.3' <<<"$out" && echo "ok: 어긋나면 실패하고 파일:줄을 말한다(kiosk-frontend·admin-console 포함)" || { echo "FAIL: 어긋남을 못 잡았다 (rc=$r)"; echo "$out"; rc=1; }
grep -q 'docs/old.md\|tests/old.sh' <<<"$out" && { echo "FAIL: 문서·시험을 검사했다"; rc=1; } || echo "ok: 문서·시험의 옛 표기는 무시"
sed -i "s/@$DEPLOY_BC_TAG/@v0.0.0-mismatch/" "$T/synthetic-data/Dockerfile"; out=$(bash "$HERE/check-versions.sh" 2>&1)
grep -q 'synthetic-data/Dockerfile:1: boundary-contracts' <<<"$out" && echo "ok: synthetic-data Dockerfile 이 기준 태그와 다르면 실패" || { echo "FAIL: DS 태그 대조가 없다"; rc=1; }
# 구조화된 파일(pyproject.toml, package.json, compose, JSON)의 어긋남도 잡는다
mkdir -p "$T/ops-feedback"
printf '[project]\ndependencies = ["boundary-contracts @ git+ssh://git@github.com/x/openit_boundary-contracts.git@v0.0.0-x"]\n' | sed 's/v0.0.0-x/v1.0.0/' > "$T/ops-feedback/pyproject.toml"
out=$(bash "$HERE/check-versions.sh" 2>&1); grep -q 'ops-feedback/pyproject.toml:2: boundary-contracts v1.0.0' <<<"$out" && echo "ok: pyproject.toml 의 어긋남" || { echo "FAIL: pyproject.toml 을 읽지 못했다"; rc=1; }
rm "$T/ops-feedback/pyproject.toml"
printf '{"dependencies": {"boundary-contracts": "github:x/openit_boundary-contracts#v1.0.0"}}' > "$T/kiosk-frontend/package.json"
out=$(bash "$HERE/check-versions.sh" 2>&1); grep -q 'kiosk-frontend/package.json:1: boundary-contracts v1.0.0' <<<"$out" && echo "ok: package.json 의 어긋남" || { echo "FAIL: package.json 을 읽지 못했다"; rc=1; }
rm "$T/kiosk-frontend/package.json"
printf 'services:\n  a:\n    build:\n      args:\n        TURN_ENGINE_TAG: v1.0.0\n' > "$T/ops-feedback/compose.yaml"
out=$(bash "$HERE/check-versions.sh" 2>&1); grep -q 'ops-feedback/compose.yaml:5: turn-engine v1.0.0' <<<"$out" && echo "ok: compose 의 어긋남" || { echo "FAIL: compose 를 읽지 못했다"; rc=1; }
rm "$T/ops-feedback/compose.yaml"
exit $rc
