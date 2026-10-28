#!/usr/bin/env bash
# publish-image.sh 를 임시 로컬 레지스트리로 실제로 시험한다. 고정 포트를 쓰지 않는다(빈 포트). 끝나면 만든 것을 모두 지운다.
# 사용: bash scripts/test-publish.sh      (이미 받아 둔 UTIL_IMAGE 를 바탕 이미지로 쓴다: 네트워크 불필요)
set -uo pipefail
source "$(dirname "$0")/lib.sh"
ID=$$; W="$DEPLOY_ROOT/state/pubtest-$ID"; mkdir -p "$W"
export DEPLOY_LOCK="$W/images.lock" DEPLOY_REGISTRY_ENV="$W/registry.env" REGISTRY_PROJECT="deploy-pubtest-$ID" REGISTRY_HOST_BIND=0.0.0.0 REGISTRY_HOST_PORT=
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
grep -E '^[A-Z0-9_]+_IMAGE=' "$DEPLOY_ROOT/locks/images.lock" > "$DEPLOY_LOCK"
FAILS=0; ok() { echo "  [PASS] $1"; }; ng() { echo "  [FAIL] $1"; FAILS=$((FAILS+1)); }
check() { local n=$1; shift; if "$@" >/dev/null 2>&1; then ok "$n"; else ng "$n"; fi; }
expect_rc() { local want=$1 n=$2; shift 2; "$@" >"$W/out.txt" 2>&1; local rc=$?; if [ $rc = "$want" ]; then ok "$n (종료 코드 $rc)"; else ng "$n: 종료 코드 $rc (기대 $want): $(tail -2 "$W/out.txt" | tr '\n' ' ')"; fi; }
cleanup() {
  bash "$DEPLOY_ROOT/scripts/registry.sh" down -v >/dev/null 2>&1
  for i in $("$DOCKER" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | tr -d '\r' | grep -E "^(127\.0\.0\.1:[0-9]+/openit/|deploy-pubtest/)"); do "$DOCKER" rmi -f "$i" >/dev/null 2>&1; done
  rm -rf "$W"
}
trap cleanup EXIT
mk_image() { # mk_image <태그> <revision> [no-revision] [추가 LABEL 한 줄]
  local tag=$1 rev=$2 d="$W/ctx-$2-$RANDOM"; mkdir -p "$d"
  { echo "FROM $UTIL"; echo "RUN echo $rev > /rev.txt"
    echo "LABEL io.openit.service=\"test\" io.openit.contracts.boundary=\"$DEPLOY_BC_TAG\" io.openit.contracts.survey-schema=\"1\""
    [ "${3:-}" = no-revision ] || echo "LABEL io.openit.revision=\"$rev\""
    [ -z "${4:-}" ] || echo "LABEL $4"; } > "$d/Dockerfile"
  "$DOCKER" build -q -t "$tag" "$d" >/dev/null
}
echo "== publish-image.sh 시험 (임시 레지스트리, 프로젝트 deploy-pubtest-$ID)"
bash "$DEPLOY_ROOT/scripts/registry.sh" up >/dev/null 2>&1 || { echo "레지스트리를 띄우지 못했다"; exit 1; }
source "$DEPLOY_REGISTRY_ENV"; echo "  레지스트리 $DEPLOY_REGISTRY"
mk_image deploy-pubtest/a:1 aaa1111; mk_image deploy-pubtest/b:1 bbb2222; mk_image deploy-pubtest/c:1 c000000 no-revision
P="bash $DEPLOY_ROOT/scripts/publish-image.sh"
expect_rc 2 "목록에 없는 서비스 이름 거부" $P not-a-service deploy-pubtest/a:1
expect_rc 2 "인자 없음 거부" $P
expect_rc 3 "필수 라벨(revision) 없는 이미지 거부" $P survey-service deploy-pubtest/c:1
# 라벨 값 검증(wo8): 게시 전에 계약 ImageLabels 로 검사한다. 필수 4개만 보던 예전 검사는 아래 값들을 모두 통과시켰다
mk_image deploy-pubtest/g1:1 d111111 x 'io.openit.turn-engine="none"'
mk_image deploy-pubtest/g2:1 d222222 x 'io.openit.contracts.boundary="2.1.1"'
mk_image deploy-pubtest/g3:1 unknown x
mk_image deploy-pubtest/g4:1 d444444 x 'io.openit.contracts.survey-schema="unknown"'
mk_image deploy-pubtest/g5:1 d555555 x 'io.openit.model-runtime="n/a" io.openit.turn-engine="n/a"'
expect_rc 3 "turn-engine=none 거부(n/a 로 통일)" $P ops-feedback deploy-pubtest/g1:1
expect_rc 3 "boundary 에 v 접두사가 없으면 거부" $P release-gate deploy-pubtest/g2:1
expect_rc 3 "revision=unknown 거부" $P survey-service deploy-pubtest/g3:1
expect_rc 3 "survey-schema=unknown 거부" $P dataset-store deploy-pubtest/g4:1
check "거부 사유가 키 이름으로 출력된다" bash -c "$P dataset-store deploy-pubtest/g4:1 2>&1 | grep -q 'io.openit.contracts.survey-schema'"
check "라벨 때문에 거부된 호출은 잠금을 바꾸지 않는다(그 서비스 줄 없음)" bash -c "! grep -qE 'OPS_FEEDBACK|RELEASE_GATE|DATASET_STORE' $DEPLOY_LOCK"
expect_rc 3 "라벨 검사를 못 하면(스키마 폴더 없음) 통과가 아니라 거부" env IMAGE_LABELS_SCHEMA_DIR=/nonexistent-labels-dir $P survey-service deploy-pubtest/a:1
expect_rc 4 "없는 이미지 거부" $P survey-service deploy-pubtest/nope:1
check "거부된 호출은 잠금을 바꾸지 않는다(서비스 줄 없음)" bash -c "! grep -q 'SURVEY_SERVICE' $DEPLOY_LOCK"
expect_rc 0 "게시(첫 번째)" $P survey-service deploy-pubtest/a:1
D1=$(sed -n 's/^PUBLISHED survey-service \(sha256:[0-9a-f]*\) .*/\1/p' "$W/out.txt" | tail -1)
check "잠금에 digest·revision 이 기록됨" bash -c "grep -q '^SURVEY_SERVICE_DIGEST=$D1\$' $DEPLOY_LOCK && grep -q '^SURVEY_SERVICE_REVISION=aaa1111\$' $DEPLOY_LOCK"
expect_rc 0 "n/a 표기(turn-engine, model-runtime)는 통과" $P admin-console deploy-pubtest/g5:1
check "외부 이미지 줄이 유지됨" bash -c "grep -q '^GATEWAY_IMAGE=' $DEPLOY_LOCK && grep -q '^UTIL_IMAGE=' $DEPLOY_LOCK"
check "머리말 + 정렬된 KEY=value 형식" bash -c "head -1 $DEPLOY_LOCK | grep -q '^# 코드 축' && [ \"\$(grep -v '^#' $DEPLOY_LOCK | sort)\" = \"\$(grep -v '^#' $DEPLOY_LOCK)\" ]"
H1=$(ls "$W/history" 2>/dev/null | wc -l); S1=$(sha256sum "$DEPLOY_LOCK" | cut -c1-64)
expect_rc 0 "같은 이미지 재게시(멱등)" $P survey-service deploy-pubtest/a:1
check "재게시: UNCHANGED, 잠금·history 변화 없음" bash -c "grep -q '^UNCHANGED survey-service $D1' $W/out.txt && [ \"\$(sha256sum $DEPLOY_LOCK | cut -c1-64)\" = $S1 ] && [ \$(ls $W/history | wc -l) = $H1 ]"
expect_rc 0 "다른 서비스 게시" $P question-authoring deploy-pubtest/b:1
check "다른 서비스 게시가 앞 서비스 줄을 건드리지 않음" bash -c "grep -q '^SURVEY_SERVICE_DIGEST=$D1\$' $DEPLOY_LOCK && grep -q '^QUESTION_AUTHORING_DIGEST=sha256:' $DEPLOY_LOCK"
mk_image deploy-pubtest/a:2 aaa3333
expect_rc 0 "새 버전 게시(같은 서비스)" $P survey-service deploy-pubtest/a:2
D2=$(sed -n 's/^PUBLISHED survey-service \(sha256:[0-9a-f]*\) .*/\1/p' "$W/out.txt" | tail -1)
check "새 digest 로 바뀌고 이전 잠금이 history 에 남음" bash -c "[ -n '$D2' ] && [ '$D2' != '$D1' ] && grep -q '^SURVEY_SERVICE_DIGEST=$D2\$' $DEPLOY_LOCK && grep -l 'SURVEY_SERVICE_DIGEST=$D1' $W/history/*.lock >/dev/null"
"$DOCKER" save deploy-pubtest/b:1 -o "$W/b.tar" >/dev/null 2>&1
expect_rc 0 "tar 파일로 게시" $P ops-feedback "$W/b.tar"
check "tar 게시: question-authoring 과 같은 이미지라 digest 가 같다" bash -c "[ \"\$(sed -n 's/^QUESTION_AUTHORING_DIGEST=//p' $DEPLOY_LOCK)\" = \"\$(sed -n 's/^OPS_FEEDBACK_DIGEST=//p' $DEPLOY_LOCK)\" ]"
check "레지스트리에서 digest 로 받을 수 있다" bash -c "curl -fsSI -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' http://$DEPLOY_REGISTRY/v2/openit/survey-service/manifests/$D2 >/dev/null"
check "check-compose.sh 가 이 잠금 형식을 받아들인다" bash "$DEPLOY_ROOT/scripts/check-compose.sh"
echo; if [ "$FAILS" = 0 ]; then echo "test-publish: 전부 통과"; else echo "test-publish: 실패 $FAILS건"; fi
exit $([ "$FAILS" = 0 ] && echo 0 || echo 1)
