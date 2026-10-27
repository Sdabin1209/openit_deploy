#!/usr/bin/env bash
# 정기 복원 시험(스케줄러 잡 backup-restore-test, 주 1회). 사용: backup-restore-test.sh [데이터베이스 ...]   환경: DEPLOY_PROJECT(기본 deploy)
# 백업은 복원해 보기 전에는 백업이 아니다(D88 U6). 서버에는 복호 개인키가 없으므로 이 시험은 두 가지를 한다.
#  1) 도구 사슬 왕복(키 필요 없음): 시험용 키쌍을 임시로 만들어 현재 운영 데이터를 pg-backup.sh 로 암호화 백업 -> 시험용 키로 복호 -> 임시 데이터베이스(rt_*)에
#     pg_restore -> 원본과 행 지문(스키마 해시 + 정렬한 INSERT 행 해시 + 행 수)을 대조. 운영 데이터베이스는 읽기만 한다. 끝나면 임시 DB·키·파일을 지운다.
#     원본이 시험 중에 바뀌면 지문이 어긋날 수 있어 최대 3번 다시 한다(그래도 다르면 FAIL).
#  2) 실제 백업 무결성(키 필요 없음): BACKUP_DIR 의 최신 스냅샷마다 MANIFEST 의 stored_file 해시를 다시 계산해 대조한다.
# 실제 개인키로 푸는 전체 복원 시험은 사람이 분기마다 한다(docs/runbook.md 4절). 이 시험은 그것을 대신하지 않는다.
# 종료 코드: 0 통과, 1 시험 실패(복원 사슬이 깨졌거나 지문 불일치), 2 설정 문제(CRIT). check-health 가 잡 상태로 읽는다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/backup-lib.sh"
P=${DEPLOY_PROJECT:-deploy}; DBS=${*:-$PG_DBS}
CFG=${BACKUP_CONFIG:-$DEPLOY_ROOT/config/backup.env}
[ -f "$CFG" ] || { echo "CRIT: 백업 설정 파일이 없다: $CFG" >&2; exit 2; }
( source "$CFG"; [ -n "${BACKUP_DIR:-}" ] ) || { echo "CRIT: BACKUP_DIR 이 비어 있다" >&2; exit 2; }
REAL_DIR=$( source "$CFG"; echo "$BACKUP_DIR" )
C=$(pg_container "$P"); [ -n "$C" ] || { echo "FAIL: 프로젝트 $P 의 postgres 컨테이너가 떠 있지 않다" >&2; exit 1; }
T=$(mktemp -d); chmod 700 "$T"; RT=""
cleanup() { for d in $RT; do "$DOCKER" exec "$C" psql -U postgres -d postgres -qc "DROP DATABASE IF EXISTS $d" >/dev/null 2>&1; done; rm -rf "$T"; }
trap cleanup EXIT
FAILS=0; fail() { echo "FAIL: $*" >&2; FAILS=$((FAILS+1)); }

# 시험용 키쌍(age 우선, 없으면 gpg). 서버 키링을 쓰지 않고 임시 폴더에만 둔다.
if command -v age >/dev/null 2>&1 && command -v age-keygen >/dev/null 2>&1; then
  TOOL=age; age-keygen -o "$T/key.txt" >/dev/null 2>&1; age-keygen -y "$T/key.txt" > "$T/recipient.pub"
  decrypt() { age -d -i "$T/key.txt" -o "$2" "$1"; }
elif command -v gpg >/dev/null 2>&1; then
  TOOL=gpg; export GNUPGHOME="$T/gnupg"; mkdir -m 700 "$GNUPGHOME"
  gpg --batch --quiet --passphrase '' --quick-generate-key "openit-restore-test" default default never >/dev/null 2>&1 || { echo "FAIL: 시험용 gpg 키 생성 실패" >&2; exit 1; }
  gpg --batch --armor --export > "$T/recipient.pub" 2>/dev/null
  decrypt() { gpg --batch --quiet --yes -o "$2" -d "$1" 2>/dev/null; }
else echo "CRIT: age 도 gpg 도 없다: 복원 시험을 할 수 없다" >&2; exit 2; fi
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=1\nBACKUP_ENCRYPT_RECIPIENTS=%s\nBACKUP_ENCRYPT_TOOL=%s\n' "$T/out" "$T/recipient.pub" "$TOOL" > "$T/backup.env"

fp() { # fp <컨테이너 안 접속 계정> <db>: 스키마 해시 + 행 해시 + 행 수 (pg-fingerprint.sh 와 같은 방식, 행 내용은 출력하지 않는다)
  local u=$1 db=$2 s r n
  s=$("$DOCKER" exec "$C" pg_dump -U "$u" -d "$db" --schema-only --no-owner --no-acl | grep -v '^--\|^\\restrict\|^\\unrestrict' | sha256sum | cut -c1-64)
  r=$("$DOCKER" exec "$C" pg_dump -U "$u" -d "$db" --data-only --inserts --no-owner | { grep '^INSERT' || true; } | sort | sha256sum | cut -c1-64)
  n=$("$DOCKER" exec "$C" pg_dump -U "$u" -d "$db" --data-only --inserts --no-owner | { grep -c '^INSERT' || true; })
  echo "$s $r $n"
}
echo "== 1) 도구 사슬 왕복 ($TOOL, 시험용 키쌍, 임시 데이터베이스)"
for db in $DBS; do
  ok=0
  for try in 1 2 3; do
    before=$(fp "$db" "$db")
    BACKUP_CONFIG="$T/backup.env" DEPLOY_PROJECT="$P" bash "$DEPLOY_ROOT/scripts/pg-backup.sh" "$db" >/dev/null 2>"$T/err" || { fail "$db 백업 실패: $(tail -1 "$T/err")"; break; }
    snap=$(ls -d "$T/out/pg-$db"/2* | tail -1); enc=$(ls "$snap/$db.dump".* 2>/dev/null | head -1)
    [ -n "$enc" ] || { fail "$db 암호화 파일이 없다"; break; }
    [ "$(stat -c %a "$enc")" = 600 ] || { fail "$db 백업 파일 권한이 600 이 아니다"; break; }
    decrypt "$enc" "$T/$db.dump" || { fail "$db 복호 실패"; break; }
    want=$(python3 -I -c 'import json,sys;print(json.load(open(sys.argv[1]+"/MANIFEST.json"))["files"][sys.argv[2]+".dump"]["sha256"])' "$snap" "$db")
    [ "sha256:$(sha256sum "$T/$db.dump" | cut -d' ' -f1)" = "$want" ] || { fail "$db 복호한 덤프의 해시가 MANIFEST 와 다르다"; break; }
    rt="rt_${db}_$$"; RT="$RT $rt"
    "$DOCKER" exec "$C" psql -U postgres -d postgres -qc "CREATE DATABASE $rt" >/dev/null 2>&1 || { fail "$db 임시 데이터베이스를 만들지 못했다"; break; }
    "$DOCKER" exec -i "$C" pg_restore -U postgres -d "$rt" --no-owner --exit-on-error --single-transaction < "$T/$db.dump" >/dev/null 2>"$T/err" || { fail "$db pg_restore 실패: $(tail -1 "$T/err")"; break; }
    after=$(fp "$db" "$db"); got=$(fp postgres "$rt")
    if [ "$before" = "$after" ] && [ "$got" = "$before" ]; then ok=1; echo "  PASS $db: 행 지문 일치 (행 수 ${got##* })"; break; fi
    if [ "$before" != "$after" ]; then echo "  재시도 $try/3: $db 원본이 시험 중에 바뀌었다"; "$DOCKER" exec "$C" psql -U postgres -d postgres -qc "DROP DATABASE $rt" >/dev/null 2>&1; rm -rf "$T/out/pg-$db"; continue; fi
    fail "$db 복원본의 행 지문이 원본과 다르다 (원본 ${before##* }행, 복원본 ${got##* }행)"; break
  done
  [ $ok = 1 ] || { [ $FAILS -gt 0 ] || fail "$db 원본이 계속 바뀌어 대조하지 못했다(3회)"; }
  rm -f "$T/$db.dump"
done
echo "== 2) 실제 백업 무결성 ($REAL_DIR, 키 필요 없음)"
n=0
for db in $DBS; do
  snap=$(ls -d "$REAL_DIR/pg-$db"/2* 2>/dev/null | tail -1)
  [ -n "$snap" ] || { fail "$db 실제 백업이 없다: $REAL_DIR/pg-$db"; continue; }
  sf=$(python3 -I -c 'import json,sys;d=json.load(open(sys.argv[1]+"/MANIFEST.json"));print(d["stored_file"]["name"],d["stored_file"]["sha256"])' "$snap" 2>/dev/null) || { fail "$db MANIFEST 를 읽지 못했다: $snap"; continue; }
  name=${sf% *}; h=${sf#* }
  if [ "sha256:$(sha256sum "$snap/$name" 2>/dev/null | cut -d' ' -f1)" = "$h" ]; then n=$((n+1)); echo "  PASS $db: $(basename "$snap") $name 해시 일치"; else fail "$db 백업 파일 해시가 MANIFEST 와 다르다: $snap/$name"; fi
done
[ $FAILS = 0 ] && { echo "통과: 복원 시험 (도구 사슬 $(echo $DBS | wc -w)개, 실제 백업 무결성 $n개)"; exit 0; } || { echo "실패: $FAILS건" >&2; exit 1; }
