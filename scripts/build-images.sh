#!/usr/bin/env bash
# 서비스 이미지를 로컬에서 빌드한다(D22, U42). deploy 는 영역의 빌드 구조(Dockerfile 인자 이름, 빌드 산출 파일, wheel 만들기)를 모른다(구조 규칙 1):
#  - 서비스마다 계약 BuildImageRequest JSON 파일 하나를 쓰고, 그 영역 소스 트리의 루트에서 `bash scripts/build-image.sh <요청 파일>` 만 부른다.
#  - 결과는 표준 출력 마지막 줄의 BuildImageResult(계약 validator 로 검증)에서 image·image_id·labels 를 받는다.
#  - versions 는 lib.sh 기준표(boundary, model_runtime, survey_schema), dependency_sources 는 deploy 가 기준표 태그에서 git archive 로 꺼낸 공유 라이브러리(boundary-contracts, model-runtime)와
#    survey-service 의 schema/ 디렉터리(절대 경로)다. 영역 소스는 git archive 사본(HEAD, model-runtime 은 기준표 태그)을 source_dir 로만 준다(작업 트리의 미커밋 변경이 섞이지 않는다).
#  - 서비스 -> 리포·variant 대응은 lib.sh 의 service_repo·service_variant 한 곳이다.
# 이미지 이름: lib.sh 의 SERVICES. 결과: build/images.env (영역 로컬이름 커밋). 레지스트리에 올리고 digest 잠금을 만드는 일은 publish-images.sh.
# 사용: build-images.sh [--gpu [--yes-large]] [이름 ...]   (이름이 없으면 기본 8개 전부)
#  --gpu        model-serving 의 GPU 변형을 별도 이미지 model-serving-gpu 로 빌드한다(약 13GB, 기본 빌드에는 넣지 않는다).
#               --gpu 만 주면 GPU 이미지만 빌드한다(다른 빌드 결과를 지우지 않는다). 빌드 전에 docker system df 로 사용량과 추가 용량을 안내한다.
#  --yes-large  비대화형(터미널이 아닐 때)에서 큰 빌드를 진행한다는 확인. 없으면 비대화형은 멈춘다
#  BUILD_TEST_ID: 시험 전용. 빌드한 이미지에 시험 라벨 openit.test-build=<ID> 를 더해 같은 소스에서 다른 digest 를 만든다(롤백 시험). revision 라벨은 소스 커밋 그대로다(lib.sh apply_test_label). 운영에는 쓰지 않는다.
set -euo pipefail
DEPLOY_NO_DOCKER=1   # 옵션·인자 검사는 Docker 없이도 동작한다. 데몬 감지는 그 뒤에 한다
source "$(dirname "$0")/lib.sh"
CTX="$DEPLOY_ROOT/build/ctx"
GPU=0; YES_LARGE=0; NAMES=()
for a in "$@"; do case "$a" in
  --gpu) GPU=1;; --yes-large) YES_LARGE=1;;
  -h|--help) sed -n '8,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  -*) die "알 수 없는 옵션: $a (사용: build-images.sh [--gpu [--yes-large]] [이름 ...])";;
  *) NAMES+=("$a");; esac; done
detect_docker
if [ $GPU = 1 ]; then
  [ ${#NAMES[@]} -gt 0 ] || NAMES=(model-serving-gpu)   # --gpu 단독: GPU 이미지만
  case " ${NAMES[*]} " in *" model-serving-gpu "*) ;; *) NAMES+=(model-serving-gpu);; esac
fi
ONLY=" ${NAMES[*]:-} "
want() { [ "$ONLY" = "  " ] || [[ "$ONLY" == *" $1 "* ]]; }
want_gpu() { [[ "$ONLY" == *" model-serving-gpu "* ]]; }   # 기본(전부) 빌드에는 들어가지 않는다
if want_gpu; then
  echo "== GPU 이미지(model-serving-gpu) 빌드 전 도커 디스크 사용량"
  "$DOCKER" system df || true
  echo "!! 이 빌드는 이미지 약 13GB(측정 전, model-runtime 안내값)를 추가한다. 도커 디스크 위치의 여유를 먼저 확인하라 (docs/RUN.md)."
  if [ $YES_LARGE = 1 ]; then :
  elif [ -t 0 ]; then printf '계속하려면 y: '; read -r ans; [ "$ans" = y ] || { echo "취소했다." >&2; exit 1; }
  else die "비대화형이다. 약 13GB 빌드를 진행하려면 --yes-large 를 명시하라"; fi
fi
if [ "$ONLY" = "  " ]; then
  # 기본(전부) 빌드는 8개 기록을 새로 쓴다. 따로 빌드한 GPU 이미지 기록(model-serving-gpu)은 지우지 않는다(13GB를 다시 빌드하지 않게)
  # 단, 이미지가 실제로 있고 현재 기준 model-runtime 태그와 같은 커밋일 때만 유지한다(아니면 이유를 알리고 기록을 버린다: gpu_record_valid, lib.sh)
  GPU_KEEP=$(gpu_record_valid "$DEPLOY_ROOT/build/images.env" || true)
  rm -rf "$CTX" "$DEPLOY_ROOT/build/images.env"
  if [ -n "$GPU_KEEP" ]; then mkdir -p "$DEPLOY_ROOT/build"; printf '%s\n' "$GPU_KEEP" > "$DEPLOY_ROOT/build/images.env"; fi
fi
mkdir -p "$CTX"
PY="$VENV/bin/python"; PIP="$VENV/bin/pip"
BC="$DEPLOY_BC_TAG"; MR="$DEPLOY_MR_TAG"   # 태그는 lib.sh 한 곳에서 정한다(도장 bc=,mr= 에도 쓴다)
SS_VER="${DEPLOY_SS_TAG#survey-schema-}"     # 문진 스키마 버전 vX.Y.Z (계약 versions.survey_schema)
# 공유 라이브러리의 기준표 버전 소스(deploy 가 알아도 되는 것: boundary-contracts, model-runtime, 문진 스키마). 영역은 이웃 리포 경로나 빌드 중 네트워크 대신 이 경로를 쓴다
DEP="$CTX/dep"; rm -rf "$DEP"; mkdir -p "$DEP/boundary" "$DEP/model_runtime" "$DEP/survey_schema"
git -C "$WORKSPACE/boundary-contracts" archive "$BC" | tar -x -C "$DEP/boundary"
git -C "$WORKSPACE/model-runtime" archive "$MR" | tar -x -C "$DEP/model_runtime"
git -C "$WORKSPACE/survey-service" archive "$DEPLOY_SS_TAG" schema | tar -x -C "$DEP/survey_schema"
touch "$DEPLOY_ROOT/build/images.env"
# 요청·결과 검증은 기준표 태그의 계약 소스(dependency_sources.boundary)로 한다: 호스트 venv 에 설치된 계약 버전이 낡아도 표의 계약으로 본다
PYB() { "$PY" "$@"; }   # 서비스 빌드 전에 venv 의 계약을 기준표 태그로 맞춘다(아래)
# 네 번째 열(의존 태그 도장)은 e2e.sh --reuse-build 가 이미지를 다시 써도 되는지 판정하는 데 쓴다(verify_area.py).
# 라벨 검사는 BuildImageResult 검증(계약, labels 는 ImageLabels) 하나다. 게시 때(publish-image.sh)는 이미지 라벨을 한 번 더 계약으로 본다(다른 시점의 다른 입력이다)
record() { set -- "$1" "$(apply_test_label "$2")" "$3"   # 시험 ID 가 있으면 새 이미지 이름(<이름>-<ID>)을 쓴다. 원래 이미지는 그대로 둔다
  sed -i "/^$1 /d" "$DEPLOY_ROOT/build/images.env"; echo "$1 $2 $3 bc=$BC,mr=$MR" >> "$DEPLOY_ROOT/build/images.env"; echo "빌드: $2"; }

# 한 서비스를 빌드한다: build_one <서비스>. 영역 리포 루트에서 진입점만 부른다. 진입점이 요청을 계약 validator 로 검증하므로 PYTHON(deploy venv, 기준표 태그의 계약으로 맞춰 둠)을 준다.
build_one() {
  local svc=$1 repo variant tagref commit src img req out rc
  repo=$(service_repo "$svc"); variant=$(service_variant "$svc")
  if [ "$repo" = model-runtime ]; then   # 추론 서버는 기준표 태그 시점의 소스다(이미지 버전 == 기준표): 태그의 git archive 사본
    src="$CTX/src/$svc"; rm -rf "$src"; mkdir -p "$src"; tagref="$MR^{commit}"; git -C "$WORKSPACE/$repo" archive "$MR" | tar -x -C "$src"
  else
    # 영역 자신의 리포 루트에서 진입점을 부른다(계약 BuildImageRequest: source_dir = 영역 리포 루트). 영역의 빌드가 자기 시험 환경(node_modules 등 setup-env 가 준비한 것)을 쓸 수 있어야 하므로
    # git archive 사본(환경이 없다)이 아니다. 대신 이미지가 HEAD 와 같도록 추적 파일에 커밋 안 된 변경이 있으면 멈춘다(BUILD_ALLOW_DIRTY=1 로만 허용).
    src="$WORKSPACE/$repo"; tagref=HEAD
    if [ "${BUILD_ALLOW_DIRTY:-0}" != 1 ] && [ -n "$(git -C "$src" status --porcelain --untracked-files=no)" ]; then die "$svc: $repo 에 커밋 안 된 변경이 있다(이미지는 HEAD 커밋 $(git -C "$src" rev-parse --short HEAD)로 표시되므로 먼저 커밋한다. 개발 중에만 BUILD_ALLOW_DIRTY=1)"; fi
  fi
  commit=$(git -C "$WORKSPACE/$repo" rev-parse --short "$tagref")
  img="deploy-build/$svc:$commit"; req="$CTX/req-$svc.json"
  PYB - "$req" "$src" "$commit" "$BC" "$MR" "$SS_VER" "$DEP" "$variant" "$img" <<'PY'
import json, sys
path, src, rev, bc, mr, ss, dep, variant, tag = sys.argv[1:10]
req = {"source_dir": src, "revision": rev, "versions": {"boundary": bc, "model_runtime": mr, "survey_schema": ss},
       "dependency_sources": {"boundary": f"{dep}/boundary", "model_runtime": f"{dep}/model_runtime", "survey_schema": f"{dep}/survey_schema/schema"}, "image_tag": tag}
if variant: req["variant"] = variant
from boundary_contracts import validator
errs = list(validator("BuildImageRequest").iter_errors(req))
if errs: sys.exit("BuildImageRequest 위반: " + errs[0].message[:200])
json.dump(req, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
PY
  [ -f "$src/scripts/build-image.sh" ] || die "$svc: 영역 진입점이 없다($repo/scripts/build-image.sh). 영역이 U42 진입점을 아직 내지 않았다"
  echo "== 빌드 $svc <- $repo @ $commit"
  rc=0; out=$(cd "$src" && DOCKER="$DOCKER" PYTHON="$PY" bash scripts/build-image.sh "$req" 2>"$CTX/build-$svc.err") || rc=$?
  [ $rc = 0 ] || { tail -15 "$CTX/build-$svc.err" >&2; die "$svc: 영역 진입점이 실패했다(종료 코드 $rc, 전체 기록 ${CTX#$DEPLOY_ROOT/}/build-$svc.err)"; }
  # 결과: 표준 출력 마지막 줄이 BuildImageResult. 계약 validator 로 검증(labels 는 ImageLabels)하고 image 가 요청한 것인지 본다
  printf '%s\n' "$out" | tail -1 | PYB -c '
import json, sys
from boundary_contracts import validator
r = json.loads(sys.stdin.read())
errs = list(validator("BuildImageResult").iter_errors(r))
if errs: sys.exit("BuildImageResult 위반: /" + "/".join(map(str, errs[0].absolute_path)) + ": " + errs[0].message[:200])
if r["image"] != sys.argv[1]: sys.exit("결과의 image(%s)가 요청한 %s 와 다르다" % (r["image"], sys.argv[1]))
# 이미지 라벨 io.openit.service 는 deploy 의 서비스 이름(게시·compose 가 쓰는 이름)과 같아야 한다: 영역 이름(예: model-runtime)이나 다른 값이면 게시된 이미지가 어느 서비스인지 라벨로 알 수 없다
if r["labels"].get("io.openit.service") != sys.argv[2]: sys.exit("라벨 io.openit.service(%s)가 서비스 이름 %s 와 다르다" % (r["labels"].get("io.openit.service"), sys.argv[2]))
print(r["image_id"])' "$img" "$svc" > "$CTX/id-$svc.txt" || die "$svc: 영역 진입점의 결과(BuildImageResult)가 계약을 어긴다"
  [ "$("$DOCKER" image inspect "$img" --format '{{.Id}}' | tr -d '\r')" = "$(cat "$CTX/id-$svc.txt")" ] || die "$svc: 결과의 image_id 가 로컬 이미지의 ID 와 다르다: $img"
  record "$svc" "$img" "$commit"
}

# 호스트에서 쓰는 wheel: E2E 클라이언트·검증기와 synthetic-data 잡용(같은 기준 태그의 boundary-contracts). 영역 진입점이 요청·결과를 계약 validator 로 검증하므로(영역은 PYTHON 의 계약을 쓴다)
# 서비스를 빌드하기 **전에** deploy venv 의 계약을 기준표 태그로 맞춘다(낡은 계약이면 요청 검증이 어긋난다).
mkdir -p "$DEPLOY_ROOT/build/hostwheels"; rm -f "$DEPLOY_ROOT/build/hostwheels"/*.whl
d="$DEPLOY_ROOT/build/hostsrc-$BC"; rm -rf "$d"; mkdir -p "$d"; cp -a "$DEP/boundary/." "$d/"
mkdir -p "$DEPLOY_ROOT/build/hostwheels/$BC"; "$PIP" wheel -q --no-deps --no-build-isolation -w "$DEPLOY_ROOT/build/hostwheels/$BC" "$d" >/dev/null 2>&1 || die "계약 $BC 의 호스트 wheel 을 만들지 못했다"
mkdir -p "$DEPLOY_ROOT/build/hostwheels/survey-schema"; "$PIP" wheel -q --no-deps --no-build-isolation -w "$DEPLOY_ROOT/build/hostwheels/survey-schema" "$DEP/survey_schema/schema" >/dev/null 2>&1 || die "문진 스키마 호스트 wheel 을 만들지 못했다(E2E 검증기용)"
"$PIP" install -q --force-reinstall --no-deps "$DEPLOY_ROOT"/build/hostwheels/"$BC"/boundary_contracts-*.whl >/dev/null 2>&1 || die "deploy venv 에 계약 $BC 를 설치하지 못했다"

for svc in $SERVICES; do want "$svc" && build_one "$svc"; done

if want_gpu; then
  echo "== model-serving-gpu 빌드 (variant gpu, model-runtime $MR)"
  build_one model-serving-gpu
  echo "== GPU 이미지 빌드 후 도커 디스크 사용량"; "$DOCKER" system df || true
  OLD=$("$DOCKER" image ls --format '{{.Repository}}:{{.Tag}} {{.Size}}' "deploy-build/model-serving-gpu" 2>/dev/null | grep -v "^$(grep '^model-serving-gpu ' "$DEPLOY_ROOT/build/images.env" | cut -d' ' -f2) " || true)
  if [ -n "$OLD" ]; then
    echo "!! 이전 GPU 이미지가 태그를 가진 채 남아 있다(커밋이 다르면 태그도 다르다). 디스크 회수는 사용자가 판단해 지운다:"
    printf '%s\n' "$OLD" | sed 's/^/     docker rmi /'
  fi
fi
