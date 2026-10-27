#!/usr/bin/env bash
# 영역 개발용 일회용 PostgreSQL. 사용: dev-postgres.sh up <데이터베이스> | down <데이터베이스> | status
#   up   : 공식 postgres:16(잠금 파일의 digest) 컨테이너를 띄우고 <데이터베이스>와 같은 이름의 계정·데이터베이스를 만든다(운영과 같은 초기화 스크립트).
#          호스트 포트는 Docker가 배정한다(127.0.0.1 만). 접속 문자열을 stdout 에 한 줄로 낸다(암호는 일회용 임의값). 나머지 안내는 stderr.
#          이미 떠 있으면 같은 접속 문자열을 다시 낸다(멱등). 데이터는 메모리(tmpfs)라 down 하면 사라진다.
#   down : 컨테이너와 임시 비밀 폴더를 지운다.     status : 떠 있는 개발용 서버 목록.
#   데이터베이스 이름: survey qa ops_log ops_failure gate 중 하나(다른 이름도 소문자·숫자·_ 면 된다).
#   환경: DEV_PG_SUFFIX(같은 데이터베이스를 여러 개 띄울 때 구분 이름), DEV_PG_IMAGE(이미지 직접 지정)
# 사용 예(영역 시험): export SURVEY_DATABASE_URL=$(bash <deploy>/scripts/dev-postgres.sh up survey)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
CMD=${1:-}; DB=${2:-}
case "$CMD" in
  up|down) [[ "$DB" =~ ^[a-z][a-z0-9_]{0,30}$ ]] || die "데이터베이스 이름이 필요하다(소문자 시작, 소문자·숫자·_): '$DB'";;
  status) ;;
  *) die "사용: dev-postgres.sh up|down <데이터베이스> | status";;
esac
NAME="deploy-devpg-${DB:-x}${DEV_PG_SUFFIX:+-$DEV_PG_SUFFIX}"
SD="$DEPLOY_ROOT/state/dev-postgres/$NAME"   # state/ 는 gitignore
IMG=${DEV_PG_IMAGE:-$(sed -n 's/^POSTGRES_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")}
dsn() { local pw port; pw=$(cat "$SD/db-${DB//_/-}-password"); port=$("$DOCKER" port "$NAME" 5432/tcp | head -1 | tr -d '\r' | sed 's/.*://'); printf 'postgresql://%s:%s@127.0.0.1:%s/%s\n' "$DB" "$pw" "$port" "$DB"; }
case "$CMD" in
  status) "$DOCKER" ps --filter label=io.openit.dev-postgres=1 --format '{{.Names}}\t{{.Status}}\t{{.Ports}}';;
  down)
    "$DOCKER" rm -f "$NAME" >/dev/null 2>&1 || true
    rm -rf "$SD"; echo "내렸다: $NAME" >&2;;
  up)
    [ -n "$IMG" ] || die "POSTGRES_IMAGE 가 잠금 파일에 없다(scripts/lock-third-party.sh) 또는 DEV_PG_IMAGE 를 준다"
    if [ "$("$DOCKER" inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null | tr -d '\r')" = true ] && [ -s "$SD/db-${DB//_/-}-password" ]; then dsn; exit 0; fi
    "$DOCKER" rm -f "$NAME" >/dev/null 2>&1 || true; rm -rf "$SD"
    mkdir -p "$SD"; chmod 711 "$SD"   # 컨테이너(uid 999)가 읽어야 한다. 호스트의 다른 사용자는 목록을 못 본다
    for f in postgres-password "db-${DB//_/-}-password"; do ( umask 022; python3 -c 'import secrets;print(secrets.token_hex(24))' > "$SD/$f" ); done
    "$DOCKER" run -d --name "$NAME" --label io.openit.dev-postgres=1 --user 999:999 --cap-drop ALL --security-opt no-new-privileges:true \
      --tmpfs /tmp --tmpfs /var/run/postgresql:uid=999,gid=999 --tmpfs /var/lib/postgresql/data:uid=999,gid=999,mode=700 \
      -p 127.0.0.1::5432 -v "$DEPLOY_ROOT/config/postgres/initdb:/docker-entrypoint-initdb.d:ro" -v "$SD:/run/secrets:ro" \
      -e POSTGRES_PASSWORD_FILE=/run/secrets/postgres-password -e PG_INIT_ACCOUNTS="$DB" "$IMG" >/dev/null
    for i in $(seq 1 60); do "$DOCKER" exec "$NAME" pg_isready -q -h 127.0.0.1 -U postgres && break; sleep 1; [ "$i" = 60 ] && { "$DOCKER" logs "$NAME" 2>&1 | tail -5 >&2; die "60초 안에 준비되지 않았다"; }; done
    echo "준비됨: $NAME (메모리 데이터, 'dev-postgres.sh down $DB' 로 지운다)" >&2
    dsn;;
esac
