#!/usr/bin/env bash
# postgres 서비스 단독 자체 시험(서비스 컨테이너·E2E 없이). 사용: bash scripts/test-postgres.sh
# 임시 프로젝트(deploy-pgtest-*)에서 postgres 만 띄워 확인한다: 기동·초기화·최소 권한·비밀 비노출·백업·복구 왕복·볼륨을 잃은 뒤의 복구.
# 암호 값은 출력하지 않는다. 끝나면 컨테이너·볼륨·임시 폴더를 지운다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
ID=$$; P=deploy-pgtest-$ID; W="$DEPLOY_ROOT/state/pgtest-$ID"; mkdir -p "$W/backups"
export DEPLOY_PROJECT=$P SECRETS_DIR="$W/secrets" DEPLOY_REGISTRY_ENV="$W/registry.env"
echo "DEPLOY_REGISTRY=127.0.0.1:1" > "$DEPLOY_REGISTRY_ENV"   # compose 전체 해석에 필요한 자리 채움(이 시험은 postgres 만 쓴다)
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=7\n' "$W/backups" > "$W/backup.env"; export BACKUP_CONFIG="$W/backup.env"
cleanup() { dc "$P" down -v --remove-orphans >/dev/null 2>&1; rm -rf "$W"; }
trap cleanup EXIT
FAILS=0; N=0
ok() { N=$((N+1)); local name=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $name"; else echo "  FAIL $name :: $(echo "$out" | tail -2 | tr '\n' ' ' | cut -c1-200 | sed -E 's/[0-9a-f]{32,}/<값>/g')"; FAILS=$((FAILS+1)); fi; }
no() { N=$((N+1)); local name=$1; shift; if out=$("$@" 2>&1); then echo "  FAIL $name :: 성공하면 안 된다"; FAILS=$((FAILS+1)); else echo "  PASS $name"; fi; }
C() { pg_container "$P"; }
pw() { cat "$SECRETS_DIR/tokens/db-${1//_/-}-password"; }
sql() { local role=$1 db=$2 q=$3; "$DOCKER" exec -e PGPASSWORD="$(pw "$role")" "$(C)" psql -h 127.0.0.1 -U "$role" -d "$db" -Atqc "$q"; }   # TCP + 암호(서비스가 접속하는 방식)
fp() { sql "$1" "$1" "SELECT md5(string_agg(id::text || v, ',' ORDER BY id)) || ':' || count(*) FROM items"; }

export P DOCKER SECRETS_DIR PG_DBS; export -f pg_container C pw sql fp
echo "== 비밀 생성 (--db-only)"
ok "gen-secrets.sh --db-only" bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --db-only "$SECRETS_DIR"
ok "DSN 파일이 규칙대로 (survey/qa/ops_log/ops_failure/gate)" bash -c 'for a in survey qa ops_log ops_failure gate; do n=${a//_/-}; f="$1/tokens/db-$n-dsn"; [[ "$(cat $f)" == "postgresql://$a:$(cat $1/tokens/db-$n-password)@postgres:5432/$a" ]] || exit 1; [ "$(stat -c %a $f)" = 644 ]; done' _ "$SECRETS_DIR"
echo "== 기동·초기화"
dc "$P" config --format json > "$W/cfg.json" 2>"$W/cfg.err"; ok "compose 해석: 호스트 포트 없음, 환경 변수에 암호 없음, 네트워크 db-* 넷만" python3 -I -c 'import json,sys;s=json.load(open(sys.argv[1]))["services"]["postgres"];assert not s.get("ports");assert sorted(s["networks"])==["db-gate","db-ops","db-qa","db-survey"];assert all("PASSWORD" not in k or k.endswith("_FILE") for k in s["environment"])' "$W/cfg.json"
dc "$P" up -d --wait --wait-timeout 120 postgres >"$W/up.log" 2>&1; ok "postgres 가 healthy 로 기동" test -n "$(C)"
ok "호스트 포트를 게시하지 않음" bash -c "[ -z \"\$('$DOCKER' port '$(C)')\" ]"
ok "비루트(uid 999)로 실행" bash -c "[ \"\$('$DOCKER' exec '$(C)' id -u | tr -d '\r')\" = 999 ]"
ok "환경 변수에 POSTGRES_PASSWORD 평문 없음, *_FILE 만" bash -c "e=\$('$DOCKER' inspect '$(C)' --format '{{range .Config.Env}}{{println .}}{{end}}'); echo \"\$e\" | grep -q '^POSTGRES_PASSWORD_FILE=/run/secrets/postgres-password\$' && ! echo \"\$e\" | grep -q '^POSTGRES_PASSWORD='"
ok "초기화 로그에 암호 값이 없음" bash -c "! '$DOCKER' logs '$(C)' 2>&1 | grep -qF \"\$(cat $SECRETS_DIR/tokens/postgres-password)\" && ! '$DOCKER' logs '$(C)' 2>&1 | grep -qF \"\$(cat $SECRETS_DIR/tokens/db-survey-password)\""
ok "check-secrets-hidden 정적+동적 검사" bash "$DEPLOY_ROOT/scripts/check-secrets-hidden.sh" "$P"
echo "== 최소 권한"
for a in $PG_DBS; do
  ok "$a 계정이 자기 데이터베이스에 접속·쓰기" sql "$a" "$a" "CREATE TABLE items(id int PRIMARY KEY, v text); INSERT INTO items SELECT g, md5(g::text) FROM generate_series(1,2000) g"
  ok "$a 계정이 슈퍼유저·DB생성·역할생성 권한 없음" bash -c "[ \"\$(sql $a $a \"SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication FROM pg_roles WHERE rolname=current_user\")\" = f ]"
  no "$a 계정이 postgres 데이터베이스에 접속 못 함" sql "$a" postgres "SELECT 1"
  for b in $PG_DBS; do [ "$a" = "$b" ] || no "$a 계정이 $b 데이터베이스에 접속 못 함" sql "$a" "$b" "SELECT 1"; done
done
no "틀린 암호로는 접속 못 함" bash -c "'$DOCKER' exec -e PGPASSWORD=wrong '$(C)' psql -h 127.0.0.1 -U survey -d survey -Atqc 'SELECT 1'"
echo "== 백업·복구 왕복"
for a in survey gate; do eval "FP_$a=\$(fp $a)"; done
PF_before=$(bash "$DEPLOY_ROOT/scripts/pg-fingerprint.sh" survey)
ok "백업 (survey gate)" bash "$DEPLOY_ROOT/scripts/pg-backup.sh" survey gate
SN_S=$(ls -d "$W"/backups/pg-survey/2* | tail -1); SN_G=$(ls -d "$W"/backups/pg-gate/2* | tail -1)
ok "MANIFEST 에 해시·크기" bash -c "grep -q '\"sha256\": \"sha256:[0-9a-f]\{64\}\"' '$SN_S/MANIFEST.json' && [ \"\$(stat -c %a '$SN_S/survey.dump')\" = 600 ]"
sql survey survey "DELETE FROM items WHERE id % 2 = 0; DROP SCHEMA IF EXISTS junk" >/dev/null 2>&1
N=$((N+1)); if [ "$(fp survey)" != "$FP_survey" ]; then echo "  PASS 데이터를 지운 뒤 지문이 달라졌다"; else echo "  FAIL 지문이 같다"; FAILS=$((FAILS+1)); fi
"$DOCKER" exec -d -e PGPASSWORD="$(pw survey)" "$(C)" psql -h 127.0.0.1 -U survey -d survey -c 'SELECT pg_sleep(60)' >/dev/null 2>&1; sleep 2
no "다른 접속이 있으면 복구 거부" bash "$DEPLOY_ROOT/scripts/pg-restore.sh" survey "$SN_S" --yes
"$DOCKER" exec "$(C)" psql -U postgres -d postgres -Atqc "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='survey' AND pid<>pg_backend_pid()" >/dev/null; sleep 1
cp -r "$SN_S" "$W/bad"; printf 'x' >> "$W/bad/survey.dump"
no "해시가 다르면 복구 거부(종료 3)" bash -c "bash '$DEPLOY_ROOT/scripts/pg-restore.sh' survey '$W/bad' --yes; [ \$? = 3 ] && exit 1 || exit 0" 
no "--yes 없이는 거부" bash "$DEPLOY_ROOT/scripts/pg-restore.sh" survey "$SN_S"
ok "복구 survey" bash "$DEPLOY_ROOT/scripts/pg-restore.sh" survey "$SN_S" --yes
N=$((N+1)); if [ "$(fp survey)" = "$FP_survey" ] && [ "$(bash "$DEPLOY_ROOT/scripts/pg-fingerprint.sh" survey)" = "$PF_before" ]; then echo "  PASS 복구 후 지문 일치 survey (행 지문 pg-fingerprint.sh 포함)"; else echo "  FAIL 복구 후 지문 불일치 survey"; FAILS=$((FAILS+1)); fi
echo "== 볼륨을 잃은 뒤 복구 (down -v -> 새 볼륨 -> 초기화 -> 복구)"
dc "$P" down -v >/dev/null 2>&1
dc "$P" up -d --wait --wait-timeout 120 postgres >"$W/up2.log" 2>&1; ok "새 볼륨에서 다시 기동·초기화" test -n "$(C)"
no "새 볼륨에는 데이터가 없다" fp survey
for a in survey gate; do SN=$(ls -d "$W"/backups/pg-$a/2* | tail -1); ok "복구 $a" bash "$DEPLOY_ROOT/scripts/pg-restore.sh" $a "$SN" --yes; done
for a in survey gate; do want=FP_$a; N=$((N+1)); if [ "$(fp $a)" = "${!want}" ]; then echo "  PASS 볼륨 상실 후 지문 일치 $a"; else echo "  FAIL 지문 불일치 $a"; FAILS=$((FAILS+1)); fi; done
ok "pg-roles.sh sync 멱등" bash "$DEPLOY_ROOT/scripts/pg-roles.sh" sync
ok "sync 뒤에도 접속" sql survey survey "SELECT 1"
echo "== 서버 설정, 계정 연결 상한 (점검 C4·G2)"
ok "오류 로그에 SQL 값이 남지 않는 설정(log_min_error_statement=panic, terse, 파라미터 길이 0)" bash -c "[ \"\$('$DOCKER' exec '$(C)' psql -U postgres -Atqc 'SHOW log_min_error_statement')\" = panic ] && [ \"\$('$DOCKER' exec '$(C)' psql -U postgres -Atqc 'SHOW log_error_verbosity')\" = terse ] && [ \"\$('$DOCKER' exec '$(C)' psql -U postgres -Atqc 'SHOW log_parameter_max_length_on_error')\" = 0 ]"
ok "max_connections 100, idle_in_transaction_session_timeout 1min" bash -c "[ \"\$('$DOCKER' exec '$(C)' psql -U postgres -Atqc 'SHOW max_connections')\" = 100 ] && [ \"\$('$DOCKER' exec '$(C)' psql -U postgres -Atqc 'SHOW idle_in_transaction_session_timeout')\" = 1min ]"
ok "서비스 계정마다 연결 상한(CONNECTION LIMIT 18)" bash -c "[ \"\$('$DOCKER' exec '$(C)' psql -U postgres -Atqc \"SELECT count(*) FROM pg_roles WHERE rolname IN ('survey','qa','ops_log','ops_failure','gate') AND rolconnlimit = 18\")\" = 5 ]"
ok "pg_hba: 루프백 TCP도 scram-sha-256, trust 는 소켓(local)뿐" bash -c "h=\$('$DOCKER' exec '$(C)' psql -U postgres -Atqc 'SHOW hba_file'); ! '$DOCKER' exec '$(C)' grep -E '^host.*trust' \$h"
echo "== 백업 암호화(gpg 시험용 키쌍)와 복원 시험 (D88/U6)"
G="$W/gpg"; mkdir -p "$G"; chmod 700 "$G"
gpg --homedir "$G" --batch --quiet --passphrase '' --quick-generate-key "backup-test@example.invalid" default default never >/dev/null 2>&1
gpg --homedir "$G" --batch --armor --export backup-test@example.invalid > "$W/recipient.pub.asc"
printf 'BACKUP_DIR=%s/enc\nBACKUP_RETENTION_DAYS=14\nBACKUP_ENCRYPT=gpg\nBACKUP_RECIPIENT_FILE=%s/recipient.pub.asc\n' "$W" "$W" > "$W/backup-enc.env"
ok "암호화 백업(gpg 공개키만 서버에 둔다)" env BACKUP_CONFIG="$W/backup-enc.env" bash "$DEPLOY_ROOT/scripts/pg-backup.sh" survey gate
ENC=$(ls -d "$W"/enc/pg-survey/2* | tail -1)
ok "암호화 파일이 .dump.enc 이고 평문 .dump 가 없으며 모드 600" bash -c "[ -f '$ENC/survey.dump.enc' ] && [ ! -f '$ENC/survey.dump' ] && [ \"\$(stat -c %a '$ENC/survey.dump.enc')\" = 600 ]"
no "암호문에 평문 PGDMP 머리가 없다(복호화 없이 읽히지 않는다)" bash -c "head -c 5 '$ENC/survey.dump.enc' | grep -q PGDMP"
ok "같은 백업 세트·시작/끝 시각이 MANIFEST 에 있다" grep -q '"backup_set": "set-' "$ENC/MANIFEST.json"
sql survey survey "DELETE FROM items WHERE id % 3 = 0" >/dev/null 2>&1
no "복호화 명령 없이 복구하면 거부" env BACKUP_CONFIG="$W/backup-enc.env" bash "$DEPLOY_ROOT/scripts/pg-restore.sh" survey "$ENC" --yes
ok "시험용 비밀키로 복호화해 복구(BACKUP_DECRYPT_CMD)" env BACKUP_DECRYPT_CMD="gpg --homedir '$G' --batch --quiet --decrypt" bash "$DEPLOY_ROOT/scripts/pg-restore.sh" survey "$ENC" --yes
N=$((N+1)); if [ "$(fp survey)" = "$FP_survey" ]; then echo "  PASS 암호화 백업에서 복구한 뒤 지문이 원래와 같다"; else echo "  FAIL 복구 후 지문 불일치(암호화)"; FAILS=$((FAILS+1)); fi
ok "복원 시험: 복호화 키가 없으면 해시만 확인한다고 낸다" bash -c "BACKUP_CONFIG='$W/backup-enc.env' bash '$DEPLOY_ROOT/scripts/restore-test.sh' survey gate 2>&1 | grep -q '해시만 확인 survey'"
ok "복원 시험: 임시 데이터베이스로 되살려 테이블 목록 대조(복호화 키 있음)" bash -c "BACKUP_DECRYPT_CMD=\"gpg --homedir '$G' --batch --quiet --decrypt\" BACKUP_CONFIG='$W/backup-enc.env' bash '$DEPLOY_ROOT/scripts/restore-test.sh' survey gate > '$W/rt.out' 2>&1; cat '$W/rt.out'; grep -q '통과 survey' '$W/rt.out' && grep -q '통과 gate' '$W/rt.out'"
ok "복원 시험 뒤 임시 데이터베이스가 남지 않는다" bash -c "[ \"\$('$DOCKER' exec '$(C)' psql -U postgres -Atqc \"SELECT count(*) FROM pg_database WHERE datname LIKE 'restoretest_%'\")\" = 0 ]"
ok "최신 백업이 기준보다 오래되면 복원 시험이 실패한다" bash -c "! BACKUP_CONFIG='$W/backup-enc.env' bash '$DEPLOY_ROOT/scripts/restore-test.sh' --max-age-seconds -1 survey >/dev/null 2>&1"
echo; [ $FAILS = 0 ] && echo "통과: postgres 자체 시험 $N건" || { echo "실패: $FAILS건 (시험 $N건)"; exit 1; }
