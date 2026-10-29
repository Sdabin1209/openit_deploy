#!/usr/bin/env bash
# config/Caddyfile 을 영역 이미지의 노출 선언(라벨 io.openit.exposure, 계약 Exposure)과 대조한다(U47, ADR 0043).
# 입력: build/images.env 의 이미지(build-images.sh 가 쓴다). 각 이미지의 라벨·ExposedPorts·User 는 docker inspect 로 읽는다.
# 종료 코드: 0 일치, 1 어긋남, 3 검증하지 못함(images.env 없음·라벨 없는 서비스 있음: 통과가 아니다).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/lib.sh"
ENVF=${IMAGES_ENV:-$DEPLOY_ROOT/build/images.env}
[ -s "$ENVF" ] || { echo "검증 못 함: $ENVF 가 없다(먼저 scripts/build-images.sh)"; exit 3; }
PY=${LABELS_PYTHON:-$DEPLOY_ROOT/.venv/bin/python}; [ -x "$PY" ] || PY=python3
J=$(mktemp); trap 'rm -f "$J"' EXIT
"$PY" -W ignore - "$ENVF" "$DOCKER" > "$J" <<'P' || exit 3
import json, subprocess, sys
env, docker = sys.argv[1], sys.argv[2]
out = {}
for line in open(env):
    t = line.split()
    if len(t) < 2 or t[0].startswith("#"): continue
    r = subprocess.run([docker, "image", "inspect", t[1]], capture_output=True, text=True)
    if r.returncode != 0: print(f"검증 못 함: 이미지 {t[1]} 를 읽지 못했다", file=sys.stderr); sys.exit(1)
    c = json.loads(r.stdout)[0]["Config"]
    out[t[0]] = {"labels": c.get("Labels") or {}, "exposed_ports": list((c.get("ExposedPorts") or {}).keys()), "user": c.get("User", "")}
json.dump(out, sys.stdout)
P
"$PY" -W ignore "$HERE/check_exposure.py" --inspect "$J" "$@"
