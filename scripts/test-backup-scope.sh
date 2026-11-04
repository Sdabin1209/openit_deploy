#!/usr/bin/env bash
# deploy 의 백업·복구 범위(계약 3.4.16, RUNTIME R10.1): deploy 는 자기 데이터(registry-data, secrets/)만 백업·복구한다. 영역 데이터(영역 볼륨·영역 DB)는 영역의 백업·복구 잡이 한다.
# 확인: (1) backup.sh·restore.sh 가 영역 저장소 이름을 거부한다 (2) 영역 데이터를 직접 꺼내는 스크립트(pg_dump·pg_restore·복원 시험)가 없다 (3) backup-all.sh 는 영역 DB 백업을 부르지 않는다. 변이: 거부를 빼면 (1)이 실패한다. Docker 불필요.
set -uo pipefail
cd "$(dirname "$0")/.."; ID=$$; MUT="scripts/.backup.mut-$ID.sh"; trap 'rm -f "$MUT"' EXIT
FAILS=0; ok() { echo "  [PASS] $1"; }; ng() { echo "  [FAIL] $1"; FAILS=$((FAILS+1)); }
for s in gate-data models-data datasets-data gateway-data pki-ca; do
  out=$(bash scripts/backup.sh $s 2>&1); rc=$?
  [ $rc != 0 ] && grep -q "registry-data 뿐" <<<"$out" && ok "backup.sh 는 영역 저장소 $s 를 거부한다" || ng "backup.sh 가 $s 를 거부하지 않았다(rc=$rc)"
  out=$(bash scripts/restore.sh $s latest --yes 2>&1); rc=$?
  [ $rc != 0 ] && grep -q "registry-data 뿐" <<<"$out" && ok "restore.sh 는 영역 저장소 $s 를 거부한다" || ng "restore.sh 가 $s 를 거부하지 않았다(rc=$rc)"
done
for f in pg-backup.sh pg-restore.sh backup-restore-test.sh; do [ ! -e scripts/$f ] && ok "영역 데이터를 직접 꺼내는 scripts/$f 가 없다" || ng "scripts/$f 가 남아 있다"; done
grep -q "pg-backup\|pg_dump" scripts/backup-all.sh && ng "backup-all.sh 가 영역 DB 를 백업한다" || ok "backup-all.sh 는 영역 DB 백업을 부르지 않는다"
sed 's|^for s in $STORES; do \[ "$s" = registry-data \].*$|:|' scripts/backup.sh > "$MUT"
out=$(bash "$MUT" gate-data 2>&1); grep -q "registry-data 뿐" <<<"$out" && ng "변이가 같은 결과를 냈다(시험이 껍데기다)" || ok "변이 확인: 거부를 빼면 영역 저장소가 통과한다(위 단언이 실패하게 된다)"
[ $FAILS = 0 ] && { echo "test-backup-scope: 전부 통과"; exit 0; } || { echo "test-backup-scope: 실패 $FAILS건"; exit 1; }
