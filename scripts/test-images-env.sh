#!/usr/bin/env bash
# build/images.env 의 GPU(선택 이미지) 기록 처리 자체 시험(Docker 불필요: 가짜 docker·curl 을 쓴다). 사용: bash scripts/test-images-env.sh
# 재현한 결함: 존재하지 않거나 옛 model-runtime 커밋인 model-serving-gpu 기록이 남아 있으면 기본 publish 가 "No such image" 로 실패했다(E2E 준비 단계 중단).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(dirname "$HERE")"; WS="$(dirname "$ROOT")"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
N=0; F=0
ok() { N=$((N+1)); local name=$1; shift; if "$@" >/dev/null 2>&1; then echo "  PASS $name"; else echo "  FAIL $name"; F=$((F+1)); fi; }
no() { N=$((N+1)); local name=$1; shift; if "$@" >/dev/null 2>&1; then echo "  FAIL $name (성공하면 안 된다)"; F=$((F+1)); else echo "  PASS $name"; fi; }
# 임시 deploy 사본(실제 build/, locks/, state/ 를 건드리지 않는다). model-runtime 은 읽기 전용으로 링크한다
mkdir -p "$T/deploy/build" && cp -r "$HERE" "$T/deploy/scripts" && cp -r "$ROOT/locks" "$T/deploy/locks" && ln -s "$WS/model-runtime" "$T/model-runtime"
D="$T/deploy"; source "$D/scripts/lib.sh" 2>/dev/null
CUR=$(git -C "$WS/model-runtime" rev-parse --short "$DEPLOY_MR_TAG^{commit}") || { echo "model-runtime $DEPLOY_MR_TAG 태그가 이 워크스페이스에 없다: 시험할 수 없다"; exit 1; }
# 가짜 docker: image inspect 는 FAKE_HAVE(공백으로 구분한 이미지 이름)에 있을 때만 성공, tag 는 기록, push 는 digest 를 낸다
cat > "$T/docker" <<'SH'
#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
case "$1" in
  image) [ "$2" = inspect ] && { case " $FAKE_HAVE " in *" $3 "*) exit 0;; esac; echo "Error: No such image: $3" >&2; exit 1; };;
  tag) case " $FAKE_HAVE " in *" $2 "*) exit 0;; esac; echo "Error response from daemon: No such image: $2" >&2; exit 1;;
  push) echo "latest: digest: sha256:$(printf 'a%.0s' $(seq 64)) size: 1"; exit 0;;
esac
exit 0
SH
cat > "$T/curl" <<'SH'
#!/usr/bin/env bash
echo "Docker-Content-Digest: sha256:$(printf 'a%.0s' $(seq 64))"
SH
chmod +x "$T/docker" "$T/curl"; export FAKE_LOG="$T/log"
BASE="survey-service question-authoring ops-feedback release-gate model-registry model-serving kiosk-frontend admin-console"
mkenv() { : > "$D/build/images.env"; for a in $BASE; do echo "$a deploy-build/$a:abc1234 abc1234" >> "$D/build/images.env"; done; [ -z "${1:-}" ] || echo "model-serving-gpu deploy-build/model-serving-gpu:$1 $1" >> "$D/build/images.env"; }
HAVE_BASE=""; for a in $BASE; do HAVE_BASE="$HAVE_BASE deploy-build/$a:abc1234"; done
echo "== gpu_record_valid (lib.sh)"
mkenv "$CUR"; export DOCKER="$T/docker"
FAKE_HAVE="deploy-build/model-serving-gpu:$CUR" ok "현재 태그의 커밋이고 이미지가 있으면 유지" bash -c "source '$D/scripts/lib.sh'; gpu_record_valid '$D/build/images.env' | grep -q '^model-serving-gpu '"
FAKE_HAVE="" no "이미지가 없으면 버린다" bash -c "source '$D/scripts/lib.sh'; gpu_record_valid '$D/build/images.env'"
FAKE_HAVE="" ok "버리는 이유와 재빌드 안내를 낸다(이미지 없음)" bash -c "source '$D/scripts/lib.sh'; gpu_record_valid '$D/build/images.env' 2>&1 | grep -q 'build-images.sh --gpu'"
mkenv 3992156
FAKE_HAVE="deploy-build/model-serving-gpu:3992156" no "이미지가 있어도 옛 model-runtime 커밋이면 버린다(재현: v0.7.1 기록)" bash -c "source '$D/scripts/lib.sh'; gpu_record_valid '$D/build/images.env'"
FAKE_HAVE="deploy-build/model-serving-gpu:3992156" ok "옛 커밋의 이유에 기준 태그가 나온다" bash -c "source '$D/scripts/lib.sh'; gpu_record_valid '$D/build/images.env' 2>&1 | grep -q \"$DEPLOY_MR_TAG\""
mkenv ""; no "기록이 없으면 아무것도 내지 않고 1" bash -c "source '$D/scripts/lib.sh'; gpu_record_valid '$D/build/images.env'"
echo "== publish-images.sh"
reg() { echo "DEPLOY_REGISTRY=127.0.0.1:1" > "$T/reg.env"; cp "$D/locks/images.lock" "$T/lock"; }
pub() { ( cd "$D" && PATH="$T:$PATH" DOCKER="$T/docker" DEPLOY_REGISTRY_ENV="$T/reg.env" DEPLOY_LOCK="$T/lock" bash scripts/publish-images.sh "$@" ); }
mkenv 3992156; reg; : > "$T/log"; export FAKE_HAVE="$HAVE_BASE"
ok "재현: 존재하지 않는 옛 GPU 기록이 남아 있어도 기본 publish 는 성공한다" pub
no "기본 publish 가 GPU 이미지를 tag 하지 않는다" grep -q "model-serving-gpu" "$T/log"
no "잠금에 GPU digest 가 들어가지 않는다" grep -q '^MODEL_SERVING_GPU_' "$T/lock"
ok "기본 영역 8개의 digest 는 잠금에 들어간다" bash -c "[ \$(grep -c '_DIGEST=sha256:' '$T/lock') -ge 8 ] && grep -q '^MODEL_SERVING_DIGEST=' '$T/lock'"
reg; no "이름을 줘서 GPU 를 올리려는데 기록이 유효하지 않으면 거부한다" pub model-serving-gpu
reg; ( pub model-serving-gpu 2>&1 || true ) | grep -q "build-images.sh --gpu" && { N=$((N+1)); echo "  PASS 거부 메시지에 재빌드 안내가 있다"; } || { N=$((N+1)); echo "  FAIL 거부 메시지에 재빌드 안내"; F=$((F+1)); }
mkenv "$CUR"; reg; export FAKE_HAVE="$HAVE_BASE deploy-build/model-serving-gpu:$CUR"; ok "유효한 GPU 기록은 이름을 줄 때 올라간다" pub model-serving-gpu
mkenv ""; reg; export FAKE_HAVE="$HAVE_BASE"; : > "$T/log"; pub model-serving >/dev/null 2>&1; ok "이름을 준 영역만 올린다(model-serving)" bash -c "grep -q 'model-serving:build-abc1234' '$T/log' && ! grep -q 'survey-service:build' '$T/log'"
mkenv ""; rm "$D/build/images.env"; mkenv ""; no "이미지가 로컬에 없으면 'No such image' 대신 안내하고 거부" bash -c "FAKE_HAVE='' ; export FAKE_HAVE; cd '$D' && PATH='$T:\$PATH' DOCKER='$T/docker' DEPLOY_REGISTRY_ENV='$T/reg.env' DEPLOY_LOCK='$T/lock' bash scripts/publish-images.sh"
echo "== 연결(정적 확인)"
ok "build-images.sh 는 GPU 기록을 gpu_record_valid 로 걸러 유지한다" grep -q 'GPU_KEEP=$(gpu_record_valid' "$HERE/build-images.sh"
ok "e2e.sh 정리는 model-serving-gpu 이미지를 지우지 않는다" grep -q "grep -v '^deploy-build/model-serving-gpu:'" "$HERE/e2e.sh"
ok "e2e.sh have_images 는 GPU 기록을 보지 않는다" grep -q "grep -vc '^model-serving-gpu '" "$HERE/e2e.sh"
[ $F = 0 ] && echo "통과: images.env GPU 기록 자체 시험 $N건" || { echo "실패: $F/$N건"; exit 1; }
