#!/usr/bin/env bash
# publish-image.sh 를 임시 로컬 레지스트리로 실제로 시험한다. 고정 포트를 쓰지 않는다(빈 포트). 끝나면 만든 것을 모두 지운다.
# 사용: bash scripts/test-publish.sh      (이미 받아 둔 UTIL_IMAGE 를 바탕 이미지로 쓴다: 네트워크 불필요)
set -uo pipefail
source "$(dirname "$0")/lib.sh"
ID=$$; W="$DEPLOY_ROOT/state/pubtest-$ID"; mkdir -p "$W"
export DEPLOY_LOCK="$W/images.lock" DEPLOY_REGISTRY_ENV="$W/registry.env" REGISTRY_PROJECT="deploy-pubtest-$ID" REGISTRY_HOST_BIND=0.0.0.0 REGISTRY_HOST_PORT=
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
grep -E '^[A-Z0-9_]+_IMAGE=' "$DEPLOY_ROOT/locks/images.lock" > "$DEPLOY_LOCK"
PYV=${LABELS_PYTHON:-$(deploy_py)} || exit 1
# 마지막 줄은 계약 PublishResult JSON 이고 exit_code 가 실제 종료 코드와 같다(docs/ci.md)
pubres() { tail -1 "$W/out.txt" | "$PYV" -W ignore -c 'import json,sys;from boundary_contracts import validator;r=json.loads(sys.stdin.read());e=[x.message for x in validator("PublishResult").iter_errors(r)];assert not e,e;print(r.get(sys.argv[1],""))' "$1"; }
FAILS=0; ok() { echo "  [PASS] $1"; }; ng() { echo "  [FAIL] $1"; FAILS=$((FAILS+1)); }
check() { local n=$1; shift; if "$@" >/dev/null 2>&1; then ok "$n"; else ng "$n"; fi; }
expect_rc() { local want=$1 n=$2; shift 2; "$@" >"$W/out.txt" 2>&1; local rc=$?; if [ $rc = "$want" ] && [ "$(pubres exit_code 2>/dev/null)" = "$want" ]; then ok "$n (종료 코드 $rc, 마지막 줄 PublishResult 일치)"; else ng "$n: 종료 코드 $rc (기대 $want): $(tail -6 "$W/out.txt" | tr '\n' ' ')"; fi; }
cleanup() {   # 왜 $ID 와 레지스트리 주소로 좁히나: 다른 실행(E2E 사전 점검과 run-self-checks 가 동시에)의 같은 이름 이미지를 지워 15건이 실패했다
  bash "$DEPLOY_ROOT/scripts/registry.sh" down -v >/dev/null 2>&1
  for i in $("$DOCKER" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | tr -d '\r' | grep -E "^(${DEPLOY_REGISTRY:-127\.0\.0\.1:0}/openit/|deploy-pubtest-$ID/)"); do "$DOCKER" rmi -f "$i" >/dev/null 2>&1; done
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
mk_image deploy-pubtest-$ID/a:1 aaa1111; mk_image deploy-pubtest-$ID/b:1 bbb2222; mk_image deploy-pubtest-$ID/c:1 c000000 no-revision
P="bash $DEPLOY_ROOT/scripts/publish-image.sh"
expect_rc 2 "목록에 없는 서비스 이름 거부" $P not-a-service deploy-pubtest-$ID/a:1
expect_rc 2 "인자 없음 거부" $P
expect_rc 3 "필수 라벨(revision) 없는 이미지 거부" $P survey-service deploy-pubtest-$ID/c:1
# 라벨 값 검증(wo8): 게시 전에 계약 ImageLabels 로 검사한다. 필수 4개만 보던 예전 검사는 아래 값들을 모두 통과시켰다
mk_image deploy-pubtest-$ID/g1:1 d111111 x 'io.openit.model-runtime="none"'
mk_image deploy-pubtest-$ID/g2:1 d222222 x 'io.openit.contracts.boundary="2.1.1"'
mk_image deploy-pubtest-$ID/g3:1 unknown x
mk_image deploy-pubtest-$ID/g4:1 d444444 x 'io.openit.contracts.survey-schema="unknown"'
mk_image deploy-pubtest-$ID/g5:1 d555555 x 'io.openit.model-runtime="n/a"'
expect_rc 3 "model-runtime=none 거부(n/a 로 통일)" $P ops-feedback deploy-pubtest-$ID/g1:1
expect_rc 3 "boundary 에 v 접두사가 없으면 거부" $P release-gate deploy-pubtest-$ID/g2:1
expect_rc 3 "revision=unknown 거부" $P survey-service deploy-pubtest-$ID/g3:1
expect_rc 3 "survey-schema=unknown 거부" $P dataset-store deploy-pubtest-$ID/g4:1
check "거부 사유가 키 이름으로 출력된다" bash -c "$P dataset-store deploy-pubtest-$ID/g4:1 2>&1 | grep -q 'io.openit.contracts.survey-schema'"
check "라벨 때문에 거부된 호출은 잠금을 바꾸지 않는다(그 서비스 줄 없음)" bash -c "! grep -qE 'OPS_FEEDBACK|RELEASE_GATE|DATASET_STORE' $DEPLOY_LOCK"
expect_rc 3 "라벨 검사를 못 하면(스키마 폴더 없음) 통과가 아니라 거부" env IMAGE_LABELS_SCHEMA_DIR=/nonexistent-labels-dir $P survey-service deploy-pubtest-$ID/a:1
expect_rc 4 "없는 이미지 거부" $P survey-service deploy-pubtest-$ID/nope:1
# push 실패(레지스트리가 push 를 거부): docker 출력과 'push 실패' 사유가 남고 종료 코드 4, 마지막 줄은 계약 PublishResult. docker 래퍼가 push 만 거부한다(실제 docker 로 나머지를 한다)
cat > "$W/docker-pushfail" <<EOF2
#!/usr/bin/env bash
if [ "\$1" = push ]; then echo "denied: requested access to the resource is denied" >&2; exit 1; fi
exec "$DOCKER" "\$@"
EOF2
chmod +x "$W/docker-pushfail"
expect_rc 4 "push 를 레지스트리가 거부하면 4(사유 출력)" env DOCKER="$W/docker-pushfail" $P survey-service deploy-pubtest-$ID/a:1
check "push 거부 때 docker 출력과 'push 실패' 사유가 남는다" bash -c "grep -q 'denied: requested access' '$W/out.txt' && grep -q 'push 실패' '$W/out.txt'"
check "push 거부 호출은 잠금을 바꾸지 않는다" bash -c "! grep -q 'SURVEY_SERVICE' $DEPLOY_LOCK"
check "거부된 호출은 잠금을 바꾸지 않는다(서비스 줄 없음)" bash -c "! grep -q 'SURVEY_SERVICE' $DEPLOY_LOCK"
expect_rc 0 "게시(첫 번째)" $P survey-service deploy-pubtest-$ID/a:1
D1=$(pubres digest); check "첫 게시는 status PUBLISHED, service·revision 이 맞다" bash -c "[ \"$(pubres status)\" = PUBLISHED ] && [ \"$(pubres service)\" = survey-service ] && [ \"$(pubres revision)\" = aaa1111 ]"
check "잠금에 digest·revision 이 기록됨" bash -c "grep -q '^SURVEY_SERVICE_DIGEST=$D1\$' $DEPLOY_LOCK && grep -q '^SURVEY_SERVICE_REVISION=aaa1111\$' $DEPLOY_LOCK"
expect_rc 0 "n/a 표기(model-runtime)는 통과" $P admin-console deploy-pubtest-$ID/g5:1
check "외부 이미지 줄이 유지됨" bash -c "grep -q '^GATEWAY_IMAGE=' $DEPLOY_LOCK && grep -q '^UTIL_IMAGE=' $DEPLOY_LOCK"
check "머리말 + 정렬된 KEY=value 형식" bash -c "head -1 $DEPLOY_LOCK | grep -q '^# 코드 축' && [ \"\$(grep -v '^#' $DEPLOY_LOCK | sort)\" = \"\$(grep -v '^#' $DEPLOY_LOCK)\" ]"
H1=$(ls "$W/history" 2>/dev/null | wc -l); S1=$(sha256sum "$DEPLOY_LOCK" | cut -c1-64)
expect_rc 0 "같은 이미지 재게시(멱등)" $P survey-service deploy-pubtest-$ID/a:1
check "재게시: UNCHANGED, 잠금·history 변화 없음" bash -c "[ \"$(pubres status)\" = UNCHANGED ] && [ \"$(pubres digest)\" = $D1 ] && [ \"\$(sha256sum $DEPLOY_LOCK | cut -c1-64)\" = $S1 ] && [ \$(ls $W/history | wc -l) = $H1 ]"
expect_rc 0 "다른 서비스 게시" $P question-authoring deploy-pubtest-$ID/b:1
check "다른 서비스 게시가 앞 서비스 줄을 건드리지 않음" bash -c "grep -q '^SURVEY_SERVICE_DIGEST=$D1\$' $DEPLOY_LOCK && grep -q '^QUESTION_AUTHORING_DIGEST=sha256:' $DEPLOY_LOCK"
mk_image deploy-pubtest-$ID/a:2 aaa3333
expect_rc 0 "새 버전 게시(같은 서비스)" $P survey-service deploy-pubtest-$ID/a:2
D2=$(pubres digest)
check "새 digest 로 바뀌고 이전 잠금이 history 에 남음" bash -c "[ -n '$D2' ] && [ '$D2' != '$D1' ] && grep -q '^SURVEY_SERVICE_DIGEST=$D2\$' $DEPLOY_LOCK && grep -l 'SURVEY_SERVICE_DIGEST=$D1' $W/history/*.lock >/dev/null"
"$DOCKER" save deploy-pubtest-$ID/b:1 -o "$W/b.tar" >/dev/null 2>&1
expect_rc 0 "tar 파일로 게시" $P ops-feedback "$W/b.tar"
check "tar 게시: question-authoring 과 같은 이미지라 digest 가 같다" bash -c "[ \"\$(sed -n 's/^QUESTION_AUTHORING_DIGEST=//p' $DEPLOY_LOCK)\" = \"\$(sed -n 's/^OPS_FEEDBACK_DIGEST=//p' $DEPLOY_LOCK)\" ]"
check "레지스트리에서 digest 로 받을 수 있다" bash -c "curl -fsSI -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' $(registry_scheme $DEPLOY_REGISTRY)://$DEPLOY_REGISTRY/v2/openit/survey-service/manifests/$D2 >/dev/null"
# 3차 E2E: 사용자 Docker 설정의 credsStore 도우미가 죽어 있으면(WSL 의 Windows 도우미 응답 없음) push 가 "error getting credentials" 로 실패했다. 같은 상태를 만들어 재현한다: 없는 도우미를 가리키는 설정 폴더
mkdir -p "$W/badcreds"; echo '{"credsStore":"openit-nonexistent-helper"}' > "$W/badcreds/config.json"
check "재현 조건: 이 설정에서는 그냥 docker push 가 자격증명 오류로 실패한다" bash -c "DOCKER_CONFIG=$W/badcreds $DOCKER push 127.0.0.1:1/x:y 2>&1 | grep -q 'getting credentials'"
expect_rc 0 "사용자 Docker 설정의 자격증명 도우미가 죽어 있어도 게시된다(push 만 빈 설정을 쓴다)" env DOCKER_CONFIG="$W/badcreds" $P dataset-store deploy-pubtest-$ID/b:1
# publish-images.sh(E2E 가 쓰는 복수 게시)도 같은 push 함수(lib.sh registry_push)를 쓴다: 같은 badcreds 에서 게시되어야 한다(11/3 에 publish-image.sh 만 고쳐져 E2E 경로가 같은 오류로 죽었다, 2026-11-04)
printf 'dataset-store deploy-pubtest-%s/b:1 bbb2222\n' "$ID" > "$W/images.env"
check "publish-images.sh: 자격증명 도우미가 죽어 있어도 게시된다(registry_push 의 빈 DOCKER_CONFIG)" env DOCKER_CONFIG="$W/badcreds" DEPLOY_IMAGES_ENV="$W/images.env" bash "$DEPLOY_ROOT/scripts/publish-images.sh"
# deploy 의 모든 docker 호출은 사용자 전역 설정과 무관하다(lib.sh 가 DOCKER_CONFIG 를 deploy 전용 폴더로 정한다, 2026-11-05): build(로컬에 없는 외부 이미지 FROM)·compose 도 badcreds 에서 자격증명 오류로 죽지 않아야 한다.
# 외부 이미지는 일부러 존재하지 않는 이름이다(받을 수 없어 실패하는 것은 같다). 시험하는 것은 실패 사유에 "getting credentials" 가 있느냐 없느냐다(있으면 자격증명 도우미를 불렀다는 뜻).
mkdir -p "$W/ctx-ext"; printf 'FROM docker.io/library/openit-nonexistent-base-%s:1\n' "$ID" > "$W/ctx-ext/Dockerfile"
check "재현 조건: 사용자 설정(badcreds)으로 그냥 docker build 하면 자격증명 오류가 난다" bash -c "DOCKER_CONFIG=$W/badcreds timeout 120 $DOCKER build -q $W/ctx-ext 2>&1 | grep -q 'getting credentials'"
check "deploy 경로(lib.sh)의 docker build 는 사용자 설정이 badcreds 여도 자격증명 도우미를 부르지 않는다" bash -c "! DOCKER_CONFIG=$W/badcreds bash -c 'source $DEPLOY_ROOT/scripts/lib.sh; timeout 120 \$DOCKER build -q $W/ctx-ext' 2>&1 | grep -q 'getting credentials'"
check "deploy 경로(lib.sh)의 compose 는 badcreds 에서도 설정을 읽는다(config -q)" bash -c "DOCKER_CONFIG=$W/badcreds bash -c 'source $DEPLOY_ROOT/scripts/lib.sh; \$DOCKER compose -f $DEPLOY_ROOT/compose.registry.yaml --env-file $DEPLOY_LOCK config -q'"
check "lib.sh 가 DOCKER_CONFIG 를 deploy 전용 폴더로 정한다(사용자 값이 아니다)" bash -c "DOCKER_CONFIG=$W/badcreds bash -c 'source $DEPLOY_ROOT/scripts/lib.sh; [ \"\$DOCKER_CONFIG\" = \"$DEPLOY_ROOT/state/docker-config\" ] && [ \"\$(cat \$DOCKER_CONFIG/config.json)\" = \"{}\" ]'"
# 변이: lib.sh 의 DOCKER_CONFIG export 를 빼면(사용자 설정이 그대로 쓰이면) 같은 build 가 자격증명 오류로 실패해야 한다
LMUT="$DEPLOY_ROOT/scripts/.lib.mut-$ID.sh"
sed 's|^  else export DOCKER_CONFIG="$DEPLOY_ROOT/state/docker-config"; mkdir -p "$DOCKER_CONFIG"; \[ -f "$DOCKER_CONFIG/config.json" \] \|\| echo .{}. > "$DOCKER_CONFIG/config.json"; fi|  else :; fi|' "$DEPLOY_ROOT/scripts/lib.sh" > "$LMUT"
check "변이 확인: DOCKER_CONFIG export 를 빼면 같은 build 가 자격증명 오류로 실패한다(시험이 껍데기가 아니다)" bash -c "! cmp -s $LMUT $DEPLOY_ROOT/scripts/lib.sh && DOCKER_CONFIG=$W/badcreds bash -c 'source $LMUT; timeout 120 \$DOCKER build -q $W/ctx-ext' 2>&1 | grep -q 'getting credentials'"
# 같은 변이 lib 로 publish-images.sh 를 돌리면 badcreds 에서 push 가 실패해야 한다(publish 경로도 같은 한 곳에 기댄다)
MUT="$DEPLOY_ROOT/scripts/.publish-images.mut-$ID.sh"
sed "s|^source \"\$(dirname \"\$0\")/lib.sh\"|source $LMUT|" "$DEPLOY_ROOT/scripts/publish-images.sh" > "$MUT"
check "변이 확인: DOCKER_CONFIG export 를 빼면 publish-images.sh 도 같은 상황에서 실패한다" bash -c "! grep -q 'scripts/lib.sh' $MUT && ! env DOCKER_CONFIG=$W/badcreds DEPLOY_IMAGES_ENV=$W/images.env bash $MUT"
rm -f "$MUT" "$LMUT"
check "check-compose.sh 가 이 잠금 형식을 받아들인다" bash "$DEPLOY_ROOT/scripts/check-compose.sh"
echo; if [ "$FAILS" = 0 ]; then echo "test-publish: 전부 통과"; else echo "test-publish: 실패 $FAILS건"; fi
exit $([ "$FAILS" = 0 ] && echo 0 || echo 1)
