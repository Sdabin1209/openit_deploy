#!/usr/bin/env bash
# check-versions.sh 자체 시험(Docker 불필요, 가짜 docker, ADR 0042): 이미지 라벨이 기준 표와 같으면 0, 다르면 1(서비스·라벨·값 출력), 검증하지 못하면 3(통과 아님).
# 사용: bash scripts/test-check-versions.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; N=0; F=0
export DEPLOY_NO_DOCKER=1; source "$HERE/lib.sh"; BC=$DEPLOY_BC_TAG; MR=$DEPLOY_MR_TAG; SS=$(sed -n 's/^survey-schema-v\([0-9]*\)\..*/\1/p' <<<"$DEPLOY_SS_TAG")
# 가짜 docker: info 성공. image inspect <이미지> 는 $FAKE_DIR/<이미지 이름의 / 와 : 를 _ 로 바꾼 것> 파일의 JSON 라벨을 낸다(없으면 실패)
cat > "$T/docker" <<'FD'
#!/usr/bin/env bash
[ "$1" = info ] && exit 0
if [ "$1 $2" = "image inspect" ]; then f="$FAKE_DIR/$(tr '/:' '__' <<<"$3")"; [ -f "$f" ] && cat "$f" && exit 0; exit 1; fi
exit 1
FD
chmod +x "$T/docker"; mkdir -p "$T/img"; export FAKE_DIR="$T/img" DOCKER="$T/docker"
lab() { printf '{"io.openit.service":"%s","io.openit.contracts.boundary":"%s","io.openit.model-runtime":"%s","io.openit.contracts.survey-schema":"%s"}' "$1" "$2" "$3" "$4" > "$T/img/$(tr '/:' '__' <<<"$5")"; }
good() { lab survey-service "$BC" "$MR" "$SS" deploy-build/survey-service:aaa1111; lab ops-feedback "$BC" n/a "$SS" deploy-build/ops-feedback:bbb2222; lab model-serving "$BC" "$MR" "$SS" deploy-build/model-serving:ccc3333; lab admin-console "$BC" n/a n/a deploy-build/admin-console:ddd4444
  printf 'survey-service deploy-build/survey-service:aaa1111 aaa1111 bc=x,mr=y\nops-feedback deploy-build/ops-feedback:bbb2222 bbb2222 bc=x,mr=y\nmodel-serving deploy-build/model-serving:ccc3333 ccc3333 bc=x,mr=y\nadmin-console deploy-build/admin-console:ddd4444 ddd4444 bc=x,mr=y\n' > "$T/images.env"; }
t() { local name=$1 want=$2 pat=$3; shift 3; N=$((N+1)); local out rc; out=$(CHECK_VERSIONS_IMAGES_ENV="$T/images.env" bash "$HERE/check-versions.sh" 2>&1); rc=$?
  if [ $rc = "$want" ] && grep -q -- "$pat" <<<"$out"; then echo "  PASS $name (종료 $rc)"; else echo "  FAIL $name (종료 $rc, 기대 $want, 패턴 '$pat')"; echo "$out" | tail -3 | sed 's/^/       /'; F=$((F+1)); fi; }
good;                                                          t "라벨이 모두 표와 같으면 0" 0 "통과: 이미지 4개"
good; lab survey-service v0.0.1 "$MR" "$SS" deploy-build/survey-service:aaa1111;  t "계약 라벨이 표와 다르면 1(서비스·라벨·값을 말한다)" 1 "survey-service: io.openit.contracts.boundary 'v0.0.1'"
good; lab model-serving "$BC" v0.0.1 "$SS" deploy-build/model-serving:ccc3333;    t "model-runtime 라벨이 표와 다르면 1(영역마다 ARG 이름이 달라 소스 grep 이 놓치던 경우: 이미지 라벨은 이름이 같다)" 1 "model-serving: io.openit.model-runtime 'v0.0.1'"
good; lab admin-console "$BC" n/a 9 deploy-build/admin-console:ddd4444;           t "문진 스키마 라벨이 표의 주 버전과 다르면 1" 1 "admin-console: io.openit.contracts.survey-schema"
good; lab ops-feedback "$BC" "" "$SS" deploy-build/ops-feedback:bbb2222;           t "model-runtime 라벨이 비어 있으면(n/a 가 아니다) 1" 1 "ops-feedback: io.openit.model-runtime"
good; printf '{"io.openit.service":"kiosk-frontend","io.openit.contracts.boundary":"%s","io.openit.contracts.survey-schema":"%s"}' "$BC" "$SS" > "$T/img/deploy-build_admin-console_ddd4444"; t "선택 라벨(model-runtime)이 아예 없는 이미지는 어긋남이 아니다(kiosk-frontend)" 0 "통과"
good; lab ops-feedback "" n/a "$SS" deploy-build/ops-feedback:bbb2222;             t "계약 라벨이 없으면(빈 값) 1" 1 "io.openit.contracts.boundary"
good; rm "$T/img/deploy-build_model-serving_ccc3333";                                 t "이미지가 로컬에 없으면 3(검증하지 못함, 통과 아님)" 3 "검증하지 못했다: 로컬에 이미지가 없다"
good; rm "$T/images.env";                                                              t "빌드 기록(images.env)이 없으면 3" 3 "검증하지 못했다: 빌드 기록이 없다"
good; printf 'model-serving-gpu deploy-build/model-serving-gpu:zzz9999 zzz9999 x\n' >> "$T/images.env"; t "선택 이미지(GPU)가 로컬에 없어도 나머지가 같으면 0" 0 "통과"
good; N=$((N+1)); DOCKER=/nonexistent/docker CHECK_VERSIONS_IMAGES_ENV="$T/images.env" bash "$HERE/check-versions.sh" >/dev/null 2>&1; [ $? = 3 ] && echo "  PASS docker 를 쓸 수 없으면 3" || { echo "  FAIL docker 없음"; F=$((F+1)); }
N=$((N+1)); if ! grep -nE 'requirements|Dockerfile|build_wheels|BOUNDARY_VERSION|ARG ' "$HERE/check-versions.sh" | grep -v '^[0-9]*:#' >/dev/null; then echo "  PASS check-versions.sh 는 영역 소스 파일을 읽지 않는다(코드에 requirements·Dockerfile·ARG 이름이 없다)"; else echo "  FAIL 소스 파일 이름이 코드에 있다"; F=$((F+1)); fi
echo; [ $F = 0 ] && echo "통과: check-versions 자체 시험 ${N}건" || { echo "실패: $F건 ($N건)"; exit 1; }
