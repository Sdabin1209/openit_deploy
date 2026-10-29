#!/usr/bin/env bash
# 롤백 시험이 '다른 digest의 새 버전'을 만드는 방법 자체 시험(wo10). 예전에는 COMMIT 라벨 뒤에 -test2 를 붙였는데(build-images.sh 의 접미사 환경 변수),
# revision 은 소스 커밋(hex)이어야 해서(Dockerfile 형식 검사와 계약 ImageLabels 의 ^[0-9a-f]{7,40}$) 게시 전 검증이 거부한다.
# 지금은 계약 라벨(io.openit.*)을 건드리지 않고 시험 전용 라벨 openit.test-build 를 더한 새 이미지 이름(<이름:태그>-<ID>)을 만든다(lib.sh apply_test_label).
# 근거: ImageLabels 는 io.openit.* 의 모르는 키만 거부하고 다른 접두사는 무시한다(스키마 propertyNames). 사용: bash scripts/test-build-test-label.sh (Docker 필요, 일회용 이미지)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/lib.sh"
export LABELS_PYTHON="${LABELS_PYTHON:-$DEPLOY_ROOT/.venv/bin/python}"; [ -x "$LABELS_PYTHON" ] || export LABELS_PYTHON=python3
N=0; F=0; ok() { N=$((N+1)); local n=$1; shift; if "$@" >/dev/null 2>&1; then echo "  PASS $n"; else echo "  FAIL $n"; F=$((F+1)); fi; }
no() { N=$((N+1)); local n=$1; shift; if "$@" >/dev/null 2>&1; then echo "  FAIL $n (성공하면 안 된다)"; F=$((F+1)); else echo "  PASS $n"; fi; }
T=$(mktemp -d); IMG=deploy-labeltest-$$/x:1; trap '"$DOCKER" rmi -f $IMG $IMG-test2 >/dev/null 2>&1; rm -rf "$T"' EXIT
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
printf 'FROM %s\nLABEL io.openit.service="survey-service" io.openit.revision="abc1234" io.openit.contracts.boundary="v2.3.0" io.openit.contracts.survey-schema="1" io.openit.turn-engine="v0.4.3" io.openit.model-runtime="v0.8.1" io.openit.langgraph="1.2.15"\n' "$UTIL" > "$T/Dockerfile"
"$DOCKER" build -q -t $IMG "$T" >/dev/null || { echo "시험 이미지를 만들지 못했다"; exit 1; }
id_of() { "$DOCKER" image inspect "$1" --format '{{.Id}}' | tr -d '\r'; }
lab() { "$DOCKER" image inspect "$1" --format "{{index .Config.Labels \"$2\"}}" | tr -d '\r'; }
echo "== 정적"
no "접미사 환경 변수를 어떤 스크립트도 쓰지 않는다(revision 에 접미사를 붙이지 않는다)" grep -rnE "BUILD_SUFFIX" "$HERE" --include=*.sh --include=*.py --exclude=test-build-test-label.sh
no "build-images.sh 의 commit_of 와 model-serving 커밋에 접미사가 없다" grep -nE 'SUFFIX' "$HERE/build-images.sh"
ok "e2e.sh 롤백 시험은 BUILD_TEST_ID 로 새 버전을 만든다" grep -q 'BUILD_TEST_ID=test2 .*build-images.sh" survey-service' "$HERE/e2e.sh"
echo "== 예전 방식은 거부된다(이 시험이 있는 이유)"
no "revision 에 -test2 를 붙이면 계약 ImageLabels 가 거부한다" bash -c "echo '{\"io.openit.service\":\"survey-service\",\"io.openit.revision\":\"abc1234-test2\",\"io.openit.contracts.boundary\":\"v2.3.0\",\"io.openit.contracts.survey-schema\":\"1\"}' | $LABELS_PYTHON -W ignore '$HERE/check_image_labels.py'"
echo "== apply_test_label (lib.sh)"
ok "apply_test_label 함수가 있다" bash -c "source '$HERE/lib.sh'; declare -F apply_test_label"
ID0=$(id_of $IMG)
NEW=$(BUILD_TEST_ID=test2 apply_test_label $IMG 2>/dev/null)
ok "새 이름은 <이름:태그>-<ID> 이다" test "$NEW" = "$IMG-test2"
ok "새 이미지는 원래와 다른 이미지다(다른 digest 의 근거)" bash -c "[ -n '$NEW' ] && [ \"\$($DOCKER image inspect '$NEW' --format '{{.Id}}')\" != '$ID0' ]"
ok "시험 라벨이 붙는다(openit.test-build=test2)" test "$(lab "$NEW" openit.test-build)" = test2
ok "revision 라벨은 소스 커밋 그대로다" test "$(lab "$NEW" io.openit.revision)" = abc1234
ok "계약 ImageLabels 검증을 통과한다(io.openit.* 가 아닌 라벨은 무시)" bash -c "source '$HERE/lib.sh'; validate_image_labels '$NEW'"
ok "원래 이미지는 바뀌지 않는다(id 그대로, 시험 라벨 없음)" bash -c "[ \"\$($DOCKER image inspect $IMG --format '{{.Id}}')\" = '$ID0' ] && [ -z \"\$($DOCKER image inspect $IMG --format '{{index .Config.Labels \"openit.test-build\"}}')\" ]"
ok "BUILD_TEST_ID 가 없으면 이미지를 바꾸지 않고 같은 이름을 낸다" bash -c "source '$HERE/lib.sh'; unset BUILD_TEST_ID; [ \"\$(apply_test_label $IMG)\" = '$IMG' ]"
no "형식에 맞지 않는 시험 ID 는 거부한다(계약 라벨을 흉내 내지 않는다)" bash -c "source '$HERE/lib.sh'; BUILD_TEST_ID='x io.openit.revision=zzz' apply_test_label $IMG"
echo; [ $F = 0 ] && echo "통과: 시험 빌드 라벨 자체 시험 $N건" || { echo "실패: $F/$N건"; exit 1; }
