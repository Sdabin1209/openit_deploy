#!/usr/bin/env bash
# 영역 DB 마다 이미지 라벨 io.openit.database(계약 DatabaseDeclaration)대로 계정 암호·접속 URI 파일을 만든다(계약 3.4.12). 일은 scripts/gen-db-secrets.py.
# 사용: gen-db-secrets-all.sh [DB 서비스 ...]   (기본 5개). 결과: $SECRETS_DIR/db-accounts/<DB 서비스>/<계정>, $SECRETS_DIR/db-urls/<DB 서비스>/<계정>/<환경 변수 이름>
# 왜 이미지가 있어야 하나: 계정·데이터베이스·권한은 DB 이미지(데이터 주인 영역)가 선언한다. 선언 없이 deploy 가 짐작하지 않는다(구조 규칙 1·4).
# 왜 640+그룹: DB 컨테이너·영역 컨테이너는 비루트 사용자라 호스트 소유 600 을 못 읽는다. 컨테이너가 group_add 로 SECRETS_GID 를 받는다(lib.sh secret_fix 와 같은 규칙).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
D=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}
set -a; . "$DEPLOY_ROOT/locks/images.lock"; [ -f "$DEPLOY_ROOT/state/registry.env" ] && . "$DEPLOY_ROOT/state/registry.env"; set +a
DBS=("$@"); [ ${#DBS[@]} -gt 0 ] || DBS=(survey-db question-authoring-db ops-feedback-db release-gate-db identity-db)
for svc in "${DBS[@]}"; do
  var=$(echo "$svc" | tr 'a-z-' 'A-Z_')_DIGEST; digest=${!var:-}
  [ -n "$digest" ] || die "$var 가 locks/images.lock 에 없다(영역이 $svc 이미지를 낸 뒤 publish-images.sh)"
  "$DEPLOY_PY" -W ignore -I "$DEPLOY_ROOT/scripts/gen-db-secrets.py" --image "${DEPLOY_REGISTRY:?state/registry.env}/openit/$svc@$digest" --db-host "$svc" \
    --accounts-dir "$D/db-accounts/$svc" --urls-dir "$D/db-urls/$svc"
  for d in "$D/db-accounts/$svc" "$D/db-urls/$svc"; do
    find "$d" -type d -exec chmod 750 {} +; find "$d" -type f -exec chmod 640 {} +
    find "$d" -exec chgrp "${SECRETS_GID:-$(id -g)}" {} + 2>/dev/null || true
  done
done
