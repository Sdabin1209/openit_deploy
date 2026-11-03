#!/usr/bin/env bash
# 영역 DB(<서비스>-db) 단독 자체 시험(서비스 컨테이너·E2E 없이). 사용: bash scripts/test-postgres.sh
# 임시 프로젝트(deploy-pgtest-*)에서 postgres 만 띄워 확인한다: 기동·초기화·최소 권한·비밀 비노출·백업·복구 왕복·볼륨을 잃은 뒤의 복구.
# 암호 값은 출력하지 않는다. 끝나면 컨테이너·볼륨·임시 폴더를 지운다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
ID=$$; P=deploy-pgtest-$ID; W="$DEPLOY_ROOT/state/pgtest-$ID"; mkdir -p "$W/backups"
export DEPLOY_PROJECT=$P SECRETS_DIR="$W/secrets" DEPLOY_REGISTRY_ENV="$W/registry.env"
echo "DEPLOY_REGISTRY=127.0.0.1:1" > "$DEPLOY_REGISTRY_ENV"
source "$(dirname "$0")/testlib.sh"; test_lock_copy "$W/images.lock"; export DEPLOY_LOCK="$W/images.lock"   # 커밋된 잠금이 불완전해도 compose 가 해석되게(scripts/testlib.sh)   # compose 전체 해석에 필요한 자리 채움(이 시험은 postgres 만 쓴다)
( umask 077; echo "pgtest-password-$ID-not-a-secret" > "$W/backup.pass" ); printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=7\nBACKUP_PASSWORD_FILE=%s\n' "$W/backups" "$W/backup.pass" > "$W/backup.env"; export BACKUP_CONFIG="$W/backup.env"
cleanup() { dc "$P" down -v --remove-orphans >/dev/null 2>&1; rm -rf "$W"; }
trap cleanup EXIT
FAILS=0; N=0
ok() { N=$((N+1)); local name=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $name"; else echo "  FAIL $name :: $(echo "$out" | tail -2 | tr '\n' ' ' | cut -c1-200 | sed -E 's/[0-9a-f]{32,}/<값>/g')"; FAILS=$((FAILS+1)); fi; }
no() { N=$((N+1)); local name=$1; shift; if out=$("$@" 2>&1); then echo "  FAIL $name :: 성공하면 안 된다"; FAILS=$((FAILS+1)); else echo "  PASS $name"; fi; }
C() { pg_container "$P" "$(pg_service_of "${1:-survey}")"; }   # 영역마다 자기 DB 컨테이너: 계정(데이터베이스) 이름으로 그 컨테이너를 고른다
pw() { cat "$SECRETS_DIR/tokens/db-${1//_/-}-password"; }
sql() { local role=$1 db=$2 q=$3; "$DOCKER" exec -e PGPASSWORD="$(pw "$role")" "$(C "${role%_app}")" psql -h 127.0.0.1 -U "$role" -d "$db" -Atqc "$q"; }   # TCP + 암호(서비스가 접속하는 방식)
fp() { sql "$1" "$1" "SELECT md5(string_agg(id::text || v, ',' ORDER BY id)) || ':' || count(*) FROM items"; }

export P DOCKER SECRETS_DIR PG_DBS; roles_of() { sql_su "$1" "SELECT string_agg(rolname, ',' ORDER BY rolname) FROM pg_roles WHERE rolcanlogin AND rolname <> 'postgres'"; }
sql_su() { "$DOCKER" exec "$(C "$1")" psql -U postgres -d postgres -Atqc "$2" | tr -d "\r"; }   # 영역 DB 의 슈퍼유저(컨테이너 안 소켓)
export -f pg_container pg_service_of C pw sql fp sql_su roles_of
echo "== 비밀 생성 (--db-only)"
ok "gen-secrets.sh --db-only (소유자와 앱 계정 비밀)" bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --db-only "$SECRETS_DIR"
ok "DSN 파일이 규칙대로 (survey/qa/ops_log/ops_failure/gate, 호스트는 영역 DB)" bash -c 'for a in survey qa ops_log ops_failure gate; do n=${a//_/-}; f="$1/tokens/db-$n-dsn"; [[ "$(cat $f)" == "postgresql://$a:$(cat $1/tokens/db-$n-password)@$(pg_service_of $a):5432/$a?sslmode=verify-full&sslrootcert=/etc/openit/pki/root_ca.crt" ]] || exit 1; [ "$(stat -c %a $f)" = 640 ]; done' _ "$SECRETS_DIR"
echo "== 기동·초기화"
dc "$P" config --format json > "$W/cfg.json" 2>"$W/cfg.err"; ok "compose 해석: 호스트 포트 없음, 환경 변수에 암호 없음, 네트워크 db-* 넷만" python3 -I -c 'import json,sys;S=json.load(open(sys.argv[1]))["services"];own={"survey-db":"db-survey","question-authoring-db":"db-qa","ops-feedback-db":"db-ops","release-gate-db":"db-gate","keycloak-db":"db-keycloak"}
for n,net in own.items():
    s=S[n];assert not s.get("ports"),n;assert sorted(s["networks"])==sorted([net,"reload-"+n]),(n,list(s["networks"]));assert all("PASSWORD" not in k or k.endswith("_FILE") for k in s["environment"]),n' "$W/cfg.json"
dc "$P" up -d --wait --wait-timeout 120 $PG_SERVICES >"$W/up.log" 2>&1; ok "영역 DB 5개가 healthy 로 기동" test -n "$(C survey)" -a -n "$(C qa)" -a -n "$(C ops_log)" -a -n "$(C gate)" -a -n "$(C keycloak)"
# test -n "$(C)"
ok "호스트 포트를 게시하지 않음" bash -c "[ -z \"\$('$DOCKER' port '$(C)')\" ]"
ok "비루트(uid 999)로 실행" bash -c "[ \"\$('$DOCKER' exec '$(C)' id -u | tr -d '\r')\" = 999 ]"
ok "환경 변수에 POSTGRES_PASSWORD 평문 없음, *_FILE 만" bash -c "e=\$('$DOCKER' inspect '$(C)' --format '{{range .Config.Env}}{{println .}}{{end}}'); echo \"\$e\" | grep -q '^POSTGRES_PASSWORD_FILE=/run/secrets/pg-superuser-survey\$' && ! echo \"\$e\" | grep -q '^POSTGRES_PASSWORD='"
ok "초기화 로그에 암호 값이 없음" bash -c "! '$DOCKER' logs '$(C)' 2>&1 | grep -qF \"\$(cat $SECRETS_DIR/tokens/pg-superuser-survey)\" && ! '$DOCKER' logs '$(C)' 2>&1 | grep -qF \"\$(cat $SECRETS_DIR/tokens/db-survey-password)\""
ok "check-secrets-hidden 정적+동적 검사" bash "$DEPLOY_ROOT/scripts/check-secrets-hidden.sh" "$P"
ok "check-containers.sh: 떠 있는 영역 DB 가 실제로 비root·읽기 전용·cap_drop ALL·한도 있음" bash "$DEPLOY_ROOT/scripts/check-containers.sh" "$P"
for a in $PG_DBS; do want=$a; case $a in ops_log|ops_failure) want="ops_failure,ops_failure_app,ops_log,ops_log_app";; esac
  ok "$a 의 DB 컨테이너에는 자기 영역의 로그인 계정($want)만 있다(다른 영역의 DB 계정이 없다)" bash -c "[ \"\$(roles_of $a)\" = '$want' ]"; done
echo "== 최소 권한"
for a in $PG_DBS; do
  ok "$a 계정이 자기 데이터베이스에 접속·쓰기" sql "$a" "$a" "CREATE TABLE items(id int PRIMARY KEY, v text); INSERT INTO items SELECT g, md5(g::text) FROM generate_series(1,2000) g"
  ok "$a 계정이 슈퍼유저·DB생성·역할생성 권한 없음" bash -c "[ \"\$(sql $a $a \"SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication FROM pg_roles WHERE rolname=current_user\")\" = f ]"
  no "$a 계정이 postgres 데이터베이스에 접속 못 함" sql "$a" postgres "SELECT 1"
  for b in $PG_DBS; do [ "$a" = "$b" ] || no "$a 계정이 $b 데이터베이스에 접속 못 함" sql "$a" "$b" "SELECT 1"; done
done
echo "== 앱 계정(L08): DML만, 스키마 변경 불가"
for a in $PG_APP_DBS; do
  app=${a}_app
  ok "$app 앱 계정이 소유자가 만든 표를 읽고 쓴다(DML)" sql "$app" "$a" "INSERT INTO items VALUES (-1, 'app'); UPDATE items SET v='app2' WHERE id=-1; SELECT count(*) FROM items; DELETE FROM items WHERE id=-1"
  no "$app 앱 계정은 표를 만들 수 없다(CREATE)" sql "$app" "$a" "CREATE TABLE app_made(x int)"
  no "$app 앱 계정은 표를 바꿀 수 없다(ALTER)" sql "$app" "$a" "ALTER TABLE items ADD COLUMN z int"
  no "$app 앱 계정은 표를 지울 수 없다(DROP)" sql "$app" "$a" "DROP TABLE items"
  no "$app 앱 계정은 표를 비울 수 없다(TRUNCATE)" sql "$app" "$a" "TRUNCATE items"
  ok "$app 앱 계정이 슈퍼유저·DB생성·역할생성 권한 없음" bash -c "[ \"\$(sql $app $a \"SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication FROM pg_roles WHERE rolname=current_user\")\" = f ]"
  ok "소유자가 나중에 만든 표·시퀀스에도 앱 권한이 자동으로 붙는다(ALTER DEFAULT PRIVILEGES)" bash -c "sql $a $a 'CREATE TABLE later(id serial PRIMARY KEY, v text)' && sql $app $a \"INSERT INTO later(v) VALUES ('x'); SELECT count(*) FROM later\" && sql $a $a 'DROP TABLE later'"
  no "$app 앱 계정이 다른 데이터베이스에 접속 못 함" sql "$app" survey "SELECT 1"
done
no "틀린 암호로는 접속 못 함" bash -c "'$DOCKER' exec -e PGPASSWORD=wrong '$(C)' psql -h 127.0.0.1 -U survey -d survey -Atqc 'SELECT 1'"
echo "== 서버 설정: 로그에 SQL 값이 남지 않음, 연결 상한, pg_hba"
ok "pg-config-check.sh (log_* 설정, 계정별 연결 상한, host 줄에 trust 없음)" bash -c "bash $DEPLOY_ROOT/scripts/pg-config-check.sh || { bash $DEPLOY_ROOT/scripts/pg-config-check.sh | grep -E \"FAIL|어긋남\" >&2; exit 1; }"
no "중복 키 오류를 일으킨다(값을 담은 문장)" sql survey survey "INSERT INTO items VALUES (1, 'LOGLEAK_probe_value')"
sleep 1
ok "오류 로그에 문장과 값(LOGLEAK_probe_value)·DETAIL(Key (id)=)이 없다" bash -c "L=\$('$DOCKER' logs '$(C)' 2>&1); echo \"\$L\" | grep -q 'duplicate key' && ! echo \"\$L\" | grep -q 'LOGLEAK_probe_value' && ! echo \"\$L\" | grep -q 'Key (id)='"
ok "계정별 연결 상한(기본 20)" bash -c "[ \"\$('$DOCKER' exec '$(C)' psql -U postgres -d postgres -Atqc \"SELECT rolconnlimit FROM pg_roles WHERE rolname='survey'\" | tr -d '\\r')\" = 20 ]"
echo "== 백업·복구 왕복"
for a in survey gate; do eval "FP_$a=\$(fp $a)"; done
PF_before=$(bash "$DEPLOY_ROOT/scripts/pg-fingerprint.sh" survey)
ok "백업 (survey gate)" bash "$DEPLOY_ROOT/scripts/pg-backup.sh" survey gate
ok "restic 저장소에 스냅샷이 생겼고 저장소 파일에 덤프 평문 표지(PGDMP)가 없다" bash -c "[ -f '$W/backups/restic/config' ] && ! grep -rqa PGDMP '$W/backups/restic'"
sql survey survey "DELETE FROM items WHERE id % 2 = 0; DROP SCHEMA IF EXISTS junk" >/dev/null 2>&1
N=$((N+1)); if [ "$(fp survey)" != "$FP_survey" ]; then echo "  PASS 데이터를 지운 뒤 지문이 달라졌다"; else echo "  FAIL 지문이 같다"; FAILS=$((FAILS+1)); fi
"$DOCKER" exec -d -e PGPASSWORD="$(pw survey)" "$(C)" psql -h 127.0.0.1 -U survey -d survey -c 'SELECT pg_sleep(60)' >/dev/null 2>&1; sleep 2
no "다른 접속이 있으면 복구 거부" bash "$DEPLOY_ROOT/scripts/pg-restore.sh" survey latest --yes
"$DOCKER" exec "$(C)" psql -U postgres -d postgres -Atqc "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='survey' AND pid<>pg_backend_pid()" >/dev/null; sleep 1
no "스냅샷 ID 형식이 아니면 거부" bash "$DEPLOY_ROOT/scripts/pg-restore.sh" survey "../etc" --yes
no "--yes 없이는 거부" bash "$DEPLOY_ROOT/scripts/pg-restore.sh" survey latest
ok "복구 survey" bash "$DEPLOY_ROOT/scripts/pg-restore.sh" survey latest --yes
N=$((N+1)); if [ "$(fp survey)" = "$FP_survey" ] && [ "$(bash "$DEPLOY_ROOT/scripts/pg-fingerprint.sh" survey)" = "$PF_before" ]; then echo "  PASS 복구 후 지문 일치 survey (행 지문 pg-fingerprint.sh 포함)"; else echo "  FAIL 복구 후 지문 불일치 survey"; FAILS=$((FAILS+1)); fi
echo "== 볼륨을 잃은 뒤 복구 (down -v -> 새 볼륨 -> 초기화 -> 복구)"
dc "$P" down -v >/dev/null 2>&1
dc "$P" up -d --wait --wait-timeout 120 $PG_SERVICES >"$W/up2.log" 2>&1; ok "새 볼륨에서 다시 기동·초기화" test -n "$(C)"
no "새 볼륨에는 데이터가 없다" fp survey
for a in survey gate; do ok "복구 $a" bash "$DEPLOY_ROOT/scripts/pg-restore.sh" $a latest --yes; done
for a in survey gate; do want=FP_$a; N=$((N+1)); if [ "$(fp $a)" = "${!want}" ]; then echo "  PASS 볼륨 상실 후 지문 일치 $a"; else echo "  FAIL 지문 불일치 $a"; FAILS=$((FAILS+1)); fi; done
ok "pg-roles.sh sync 멱등" bash "$DEPLOY_ROOT/scripts/pg-roles.sh" sync
ok "sync 뒤에도 접속" sql survey survey "SELECT 1"
echo; [ $FAILS = 0 ] && echo "통과: 영역 DB 자체 시험 $N건" || { echo "실패: $FAILS건 (시험 $N건)"; exit 1; }
