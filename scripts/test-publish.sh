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
mk_image() { # mk_image <태그> <revision> [라벨 생략: no-revision]
  local tag=$1 rev=$2 d="$W/ctx-$2"; mkdir -p "$d"
  { echo "FROM $UTIL"; echo "RUN echo $rev > /rev.txt"
    echo 'LABEL io.openit.service="test" io.openit.contracts.boundary="$DEPLOY_BC_TAG" io.openit.contracts.survey-schema="1"'
    [ "${3:-}" = no-revision ] || echo "LABEL io.openit.revision=\"$rev\""; } > "$d/Dockerfile"
  "$DOCKER" build -q -t "$tag" "$d" >/dev/null
}
echo "== publish-image.sh 시험 (임시 레지스트리, 프로젝트 deploy-pubtest-$ID)"
bash "$DEPLOY_ROOT/scripts/registry.sh" up >/dev/null 2>&1 || { echo "레지스트리를 띄우지 못했다"; exit 1; }
source "$DEPLOY_REGISTRY_ENV"; echo "  레지스트리 $DEPLOY_REGISTRY"
mk_image deploy-pubtest/a:1 rev-aaa111; mk_image deploy-pubtest/b:1 rev-bbb222; mk_image deploy-pubtest/c:1 no-rev no-revision
P="bash $DEPLOY_ROOT/scripts/publish-image.sh"
expect_rc 2 "목록에 없는 서비스 이름 거부" $P not-a-service deploy-pubtest/a:1
expect_rc 2 "인자 없음 거부" $P
expect_rc 3 "필수 라벨(revision) 없는 이미지 거부" $P survey-service deploy-pubtest/c:1
expect_rc 4 "없는 이미지 거부" $P survey-service deploy-pubtest/nope:1
check "거부된 호출은 잠금을 바꾸지 않는다(서비스 줄 없음)" bash -c "! grep -q 'SURVEY_SERVICE' $DEPLOY_LOCK"
expect_rc 0 "게시(첫 번째)" $P survey-service deploy-pubtest/a:1
D1=$(sed -n 's/^PUBLISHED survey-service \(sha256:[0-9a-f]*\) .*/\1/p' "$W/out.txt" | tail -1)
check "잠금에 digest·revision 이 기록됨" bash -c "grep -q '^SURVEY_SERVICE_DIGEST=$D1\$' $DEPLOY_LOCK && grep -q '^SURVEY_SERVICE_REVISION=rev-aaa111\$' $DEPLOY_LOCK"
check "외부 이미지 줄이 유지됨" bash -c "grep -q '^GATEWAY_IMAGE=' $DEPLOY_LOCK && grep -q '^UTIL_IMAGE=' $DEPLOY_LOCK"
check "머리말 + 정렬된 KEY=value 형식" bash -c "head -1 $DEPLOY_LOCK | grep -q '^# 코드 축' && [ \"\$(grep -v '^#' $DEPLOY_LOCK | sort)\" = \"\$(grep -v '^#' $DEPLOY_LOCK)\" ]"
H1=$(ls "$W/history" 2>/dev/null | wc -l); S1=$(sha256sum "$DEPLOY_LOCK" | cut -c1-64)
expect_rc 0 "같은 이미지 재게시(멱등)" $P survey-service deploy-pubtest/a:1
check "재게시: UNCHANGED, 잠금·history 변화 없음" bash -c "grep -q '^UNCHANGED survey-service $D1' $W/out.txt && [ \"\$(sha256sum $DEPLOY_LOCK | cut -c1-64)\" = $S1 ] && [ \$(ls $W/history | wc -l) = $H1 ]"
expect_rc 0 "다른 서비스 게시" $P question-authoring deploy-pubtest/b:1
check "다른 서비스 게시가 앞 서비스 줄을 건드리지 않음" bash -c "grep -q '^SURVEY_SERVICE_DIGEST=$D1\$' $DEPLOY_LOCK && grep -q '^QUESTION_AUTHORING_DIGEST=sha256:' $DEPLOY_LOCK"
mk_image deploy-pubtest/a:2 rev-aaa333
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
