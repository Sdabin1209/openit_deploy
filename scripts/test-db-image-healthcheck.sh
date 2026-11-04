#!/usr/bin/env bash
# 영역 DB 이미지(<영역>-db, identity-db)는 자기 Dockerfile 에 HEALTHCHECK 를 둔다(Docker 표준): compose 의 DB 서비스는 healthcheck 를 쓰지 않고 이미지 것을 쓴다(구조 규칙 1: 준비 상태는 이미지가 안다).
# 정적(compose 에 healthcheck 가 없다) + 이미지(build/images.env 의 로컬 이미지에 Healthcheck 가 있다). 이미지가 없으면 77(건너뜀, 통과로 세지 않는다).
set -uo pipefail
cd "$(dirname "$0")/.."; DEPLOY_NO_DOCKER=1; source scripts/lib.sh; detect_docker
bad=0
python3 - <<'PY' || bad=1
import yaml, sys
c = yaml.safe_load(open("compose.yaml", encoding="utf-8"))
b = [n for n in c["services"] if n.endswith("-db") and "healthcheck" in c["services"][n]]
if b: print("FAIL compose 의 DB 서비스가 healthcheck 를 쓴다:", b); sys.exit(1)
print("OK compose 의 DB 서비스에는 healthcheck 가 없다(이미지 것을 쓴다)")
PY
miss=0
for s in survey-db question-authoring-db ops-feedback-db release-gate-db identity-db; do
  tag=$(awk -v s=$s '$1==s{print $2}' build/images.env 2>/dev/null); [ -n "$tag" ] || { echo "SKIP: $s 이미지 기록이 없다"; exit 77; }
  h=$("$DOCKER" image inspect "$tag" --format '{{json .Config.Healthcheck}}' 2>/dev/null) || { echo "SKIP: 이미지 $tag 가 없다"; exit 77; }
  case "$h" in null|"") echo "FAIL $s ($tag): 이미지에 HEALTHCHECK 가 없다"; miss=1;; *) echo "OK $s: 이미지 HEALTHCHECK";; esac
done
[ $bad = 0 ] && [ $miss = 0 ]
