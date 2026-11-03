#!/usr/bin/env bash
# 떠 있는 postgres 에 데이터베이스·계정 초기화를 다시 돌린다(멱등). 사용: pg-roles.sh sync   환경: DEPLOY_PROJECT(기본 deploy), PG_INIT_ACCOUNTS
# 용도: 암호 파일을 바꾼 뒤 계정 암호 교체. 새 계정을 더했다면 compose 의 postgres secrets 에 암호 파일을 더하고 서비스를 다시 만든(up -d) 뒤 실행한다.
# 최초 초기화는 공식 이미지가 빈 볼륨에서 자동으로 돌린다(/docker-entrypoint-initdb.d).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
[ "${1:-}" = sync ] || die "사용: pg-roles.sh sync"
for db in ${PG_INIT_ACCOUNTS:-$PG_DBS}; do   # 영역마다 자기 DB 컨테이너: 계정마다 그 영역의 컨테이너에서만 돌린다
  svc=$(pg_service_of "$db") || die "알 수 없는 데이터베이스: $db"
  C=$(pg_container "${DEPLOY_PROJECT:-deploy}" "$svc"); [ -n "$C" ] || die "$svc 컨테이너가 떠 있지 않다"
  app=""; case " $PG_APP_DBS " in *" $db "*) app=$db;; esac
  "$DOCKER" exec -u postgres -e PG_INIT_ACCOUNTS="$db" -e PG_APP_ACCOUNTS="$app" "$C" bash /docker-entrypoint-initdb.d/10-roles.sh
done
