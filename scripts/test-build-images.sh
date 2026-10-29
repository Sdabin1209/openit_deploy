#!/usr/bin/env bash
# build-images.sh 자체 시험(Docker 불필요, 가짜 영역 진입점·가짜 docker, U42). 사용: bash scripts/test-build-images.sh
# 확인: 서비스마다 BuildImageRequest 를 쓰고 영역 리포 루트에서 scripts/build-image.sh <요청> 만 부른다 / 요청 값(revision, versions, dependency_sources, variant, source_dir) /
#       서비스 -> 리포 대응 / 결과(BuildImageResult) 검증 실패·진입점 실패·진입점 없음·image_id 불일치는 빌드 실패.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; N=0; F=0
ok() { N=$((N+1)); local name=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $name"; else echo "  FAIL $name :: $(echo "$out" | tail -2 | tr '\n' ' ' | cut -c1-200)"; F=$((F+1)); fi; }
no() { N=$((N+1)); local name=$1; shift; if out=$("$@" 2>&1); then echo "  FAIL $name :: 성공하면 안 된다"; F=$((F+1)); else echo "  PASS $name"; fi; }
D="$T/deploy"; mkdir -p "$D/build"; cp -r "$HERE" "$D/scripts"; cp -r "$HERE/../locks" "$D/locks" 2>/dev/null; VS="$HERE/../.venv"; [ -x "$VS/bin/python" ] || VS="$(git -C "$HERE" rev-parse --git-common-dir 2>/dev/null)/../.venv"   # worktree 에는 .venv 가 없다: 주 작업 트리의 것을 쓴다
ln -s "$(cd "$VS" 2>/dev/null && pwd)" "$D/.venv" 2>/dev/null
[ -x "$D/.venv/bin/python" ] || { echo "SKIP: deploy .venv 가 없다(계약 validator 필요)"; exit 0; }
DEPLOY_NO_DOCKER=1; source "$D/scripts/lib.sh"; BC=$DEPLOY_BC_TAG; MR=$DEPLOY_MR_TAG; SSTAG=$DEPLOY_SS_TAG
G='git -c user.name=t -c user.email=t@t'
mkrepo() { local n=$1; mkdir -p "$T/$n"; ( cd "$T/$n" && git init -q && echo "$n" > REPO_MARKER && mkdir -p scripts && git add -A && $G commit -q -m init ); }
# 가짜 영역 진입점: 요청을 $T/req/<리포>[-variant].json 으로 복사하고 BuildImageResult 한 줄을 낸다. FAKE_MODE 로 실패 모양을 고른다(리포 이름이 FAKE_BAD 와 같을 때만)
cat > "$T/entry.sh" <<'EN'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
REQ=$1; REPO=$(cat REPO_MARKER); mkdir -p "$FAKE_OUT"
python3 - "$REQ" "$REPO" "$FAKE_OUT" "$(pwd)" <<'PY'
import json, sys, os
req = json.load(open(sys.argv[1])); repo, out, cwd = sys.argv[2:5]
assert os.path.realpath(req["source_dir"]) == os.path.realpath(cwd), ("source_dir != 리포 루트", req["source_dir"], cwd)
open(f"{out}/{repo}{'-' + req['variant'] if 'variant' in req else ''}.json", "w").write(json.dumps(req))
PY
bad=${FAKE_BAD:-}; mode=${FAKE_MODE:-}
if [ "$bad" = "$REPO" ]; then case "$mode" in
  fail) echo "빌드 실패(가짜)" >&2; exit 1;;
  nolabels) echo '{"image":"'$(python3 -c "import json;print(json.load(open('$REQ'))['image_tag'])")'","image_id":"sha256:'$(printf 'a%.0s' $(seq 64))'","labels":{}}'; exit 0;;
  otherimage) echo '{"image":"x/other:1","image_id":"sha256:'$(printf 'a%.0s' $(seq 64))'","labels":{"io.openit.service":"x","io.openit.revision":"abc1234","io.openit.contracts.boundary":"v2.0.0","io.openit.contracts.survey-schema":"n/a"}}'; exit 0;;
  badid) ID=sha256:$(printf 'b%.0s' $(seq 64));;
esac; fi
ID=${ID:-sha256:$(printf 'a%.0s' $(seq 64))}
IMG=$(python3 -c "import json;print(json.load(open('$REQ'))['image_tag'])"); REV=$(python3 -c "import json;print(json.load(open('$REQ'))['revision'])")
echo "진행 기록(표준 오류)" >&2
echo '{"image":"'$IMG'","image_id":"'$ID'","labels":{"io.openit.service":"'$REPO'","io.openit.revision":"'$REV'","io.openit.contracts.boundary":"'$(python3 -c "import json;print(json.load(open('$REQ'))['versions']['boundary'])")'","io.openit.contracts.survey-schema":"n/a"}}'
EN
for r in boundary-contracts model-runtime survey-service question-authoring ops-feedback release-gate model-lab synthetic-data kiosk-frontend admin-console; do mkrepo "$r"; done
for r in model-runtime survey-service question-authoring ops-feedback release-gate model-lab synthetic-data kiosk-frontend admin-console; do ( cd "$T/$r" && cp "$T/entry.sh" scripts/build-image.sh && git add -A && $G commit -q -m entry ); done
REAL_BC="$(cd "$(git -C "$HERE" rev-parse --git-common-dir)/../.." && pwd)/boundary-contracts"
[ -d "$REAL_BC" ] && git -C "$REAL_BC" rev-parse "$BC" >/dev/null 2>&1 || { echo "SKIP: 계약 리포($REAL_BC)에 태그 $BC 가 없다"; exit 0; }
git -C "$REAL_BC" archive "$BC" | tar -x -C "$T/boundary-contracts"   # 실제 계약 소스(요청·결과 검증기가 여기서 온다)
( cd "$T/boundary-contracts" && echo bc-src > SRC_BC && git add -A && $G commit -q -m s && git tag "$BC" ); ( cd "$T/model-runtime" && echo mr-src > SRC_MR && git add -A && $G commit -q -m s && git tag "$MR" )
( cd "$T/survey-service" && mkdir -p schema/survey_schema && echo '{}' > schema/x.json && touch schema/survey_schema/__init__.py && printf '[build-system]\nrequires=["setuptools>=61"]\nbuild-backend="setuptools.build_meta"\n[project]\nname="openit-survey-schema"\nversion="0.0.1"\n[tool.setuptools]\npackages=["survey_schema"]\n' > schema/pyproject.toml && git add -A && $G commit -q -m s && git tag "$SSTAG" )
# 가짜 docker: info 성공, image inspect --format {{.Id}} 는 항상 a*64 (진입점이 내는 image_id 와 같다), system df 는 아무것도 안 한다
cat > "$T/docker" <<'FD'
#!/usr/bin/env bash
case "$1" in info) exit 0;; image) [ "$2" = inspect ] && { case "$*" in *"{{.Id}}"*) echo "sha256:$(printf 'a%.0s' $(seq 64))"; exit 0;; esac; }; exit 0;; system) exit 0;; esac; exit 0
FD
chmod +x "$T/docker"; mkdir -p "$D/state"
export DOCKER="$T/docker" FAKE_OUT="$T/req"
run() { ( cd "$D" && env DEPLOY_ROOT="" bash scripts/build-images.sh "$@" ) ; }
echo "== 전체 빌드"
ok "build-images.sh (서비스 9개)" bash -c "cd '$D' && bash scripts/build-images.sh >/dev/null 2>&1"
ok "images.env 에 서비스 9개가 기록됐다" bash -c "[ \$(grep -vc '^model-serving-gpu ' '$D/build/images.env') = 9 ]"
ok "서비스 -> 리포 대응(요청을 받은 리포: survey-service question-authoring ops-feedback release-gate model-lab synthetic-data model-runtime kiosk-frontend admin-console)" bash -c "cd '$T/req' && ls | sed 's/.json//' | sort | tr '\n' ' ' | grep -q '^admin-console kiosk-frontend model-lab model-runtime ops-feedback question-authoring release-gate survey-service synthetic-data \$'"
rq() { python3 -c "import json,sys;d=json.load(open('$T/req/$1.json'));print(eval(sys.argv[1]))" "$2"; }
ok "요청: revision 은 리포 HEAD(model-runtime 은 기준표 태그) 짧은 해시" bash -c "[ \"\$(python3 -c \"import json;print(json.load(open('$T/req/survey-service.json'))['revision'])\")\" = \"\$(git -C $T/survey-service rev-parse --short HEAD)\" ] && [ \"\$(python3 -c \"import json;print(json.load(open('$T/req/model-runtime.json'))['revision'])\")\" = \"\$(git -C $T/model-runtime rev-parse --short $MR^{commit})\" ]"
ok "요청: versions 가 lib.sh 기준표(boundary, model_runtime, survey_schema=vX.Y.Z)다" bash -c "[ \"\$(python3 -c \"import json;d=json.load(open('$T/req/survey-service.json'))['versions'];print(d['boundary'],d['model_runtime'],d['survey_schema'])\")\" = '$BC $MR ${SSTAG#survey-schema-}' ]"
ok "요청: dependency_sources 는 기준표 태그에서 꺼낸 절대 경로(boundary 에 태그 시점 파일, 문진 스키마는 schema/ 디렉터리)" bash -c "python3 - <<PY
import json
d=json.load(open('$T/req/survey-service.json'))['dependency_sources']
assert all(v.startswith('/') for v in d.values())
assert open(d['boundary']+'/SRC_BC').read().strip()=='bc-src' and open(d['model_runtime']+'/SRC_MR').read().strip()=='mr-src' and open(d['survey_schema']+'/x.json').read().strip()=='{}'
PY"
ok "요청: model-registry 의 source_dir 는 model-lab 리포 루트다" bash -c "[ \"\$(cat \$(python3 -c \"import json;print(json.load(open('$T/req/model-lab.json'))['source_dir'])\")/REPO_MARKER)\" = model-lab ]"
ok "요청: 기본 이미지는 variant 가 없다" bash -c "! grep -q variant '$T/req/model-runtime.json'"
ok "진입점 진행 기록(표준 오류)은 파일로 가고 결과 JSON 만 읽는다" bash -c "ls '$D/build/ctx/build-survey-service.err' >/dev/null"
echo "== GPU variant"
ok "build-images.sh --gpu --yes-large (variant gpu, model-runtime)" bash -c "cd '$D' && bash scripts/build-images.sh --gpu --yes-large >/dev/null 2>&1"
ok "GPU 요청은 variant=gpu 이고 model-runtime 소스다" bash -c "[ \"\$(python3 -c \"import json;print(json.load(open('$T/req/model-runtime-gpu.json'))['variant'])\")\" = gpu ]"
echo "== 실패 처리"
bad() { local repo=$1 mode=$2 svc=$3 pat=$4; N=$((N+1)); local o; o=$(cd "$D" && FAKE_BAD=$repo FAKE_MODE=$mode bash scripts/build-images.sh "$svc" 2>&1); local rc=$?
  if [ $rc != 0 ] && grep -q -- "$pat" <<<"$o"; then echo "  PASS $repo/$mode -> 빌드 실패 ($pat)"; else echo "  FAIL $repo/$mode (종료 $rc) $(echo "$o" | tail -2 | tr '\n' ' ' | cut -c1-160)"; F=$((F+1)); fi; }
bad survey-service fail survey-service "영역 진입점이 실패했다"
bad survey-service nolabels survey-service "BuildImageResult"
bad ops-feedback otherimage ops-feedback "요청한"
bad question-authoring badid question-authoring "image_id"
N=$((N+1)); echo "# dirty" >> "$T/ops-feedback/scripts/build-image.sh"; o=$(cd "$D" && bash scripts/build-images.sh ops-feedback 2>&1); [ $? != 0 ] && grep -q "커밋 안 된 변경" <<<"$o" && echo "  PASS 영역 리포에 커밋 안 된 추적 파일 변경이 있으면 멈춘다" || { echo "  FAIL dirty 감지"; F=$((F+1)); }
N=$((N+1)); o=$(cd "$D" && BUILD_ALLOW_DIRTY=1 bash scripts/build-images.sh ops-feedback 2>&1); [ $? = 0 ] && echo "  PASS BUILD_ALLOW_DIRTY=1 이면 허용" || { echo "  FAIL BUILD_ALLOW_DIRTY"; F=$((F+1)); }
( cd "$T/ops-feedback" && git checkout -q scripts/build-image.sh )
N=$((N+1)); rm -f "$T/synthetic-data/scripts/build-image.sh"; ( cd "$T/synthetic-data" && git add -A && $G commit -q -m rm ); o=$(cd "$D" && bash scripts/build-images.sh dataset-store 2>&1); [ $? != 0 ] && grep -q "진입점이 없다" <<<"$o" && echo "  PASS 영역 진입점이 없으면 이유를 말하고 실패" || { echo "  FAIL 진입점 없음"; F=$((F+1)); }
echo; [ $F = 0 ] && echo "통과: build-images 자체 시험 ${N}건" || { echo "실패: $F건 ($N건)"; exit 1; }
