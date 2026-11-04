#!/usr/bin/env bash
# test-egress-edges.sh 의 변이 확인: 첫 연결의 받는 쪽 이름을 부르는 쪽 egress 에서 빼면(EGRESS_MUTATE=1) 그 연결이 막혀 시험이 rc=1 로 실패해야 한다(실패 사유가 그 연결의 허용 호출 결과여야 한다).
# 변이로 통과하면 시험이 껍데기라는 뜻이다. 이미지가 없으면 77(건너뜀).
cd "$(dirname "$0")/.."
out=$(EGRESS_MUTATE=1 EGRESS_LIMIT=1 bash scripts/test-egress-edges.sh 2>&1); rc=$?
[ $rc = 77 ] && { echo "$out"; exit 77; }
if [ $rc = 1 ] && printf '%s' "$out" | grep -q "FAIL 연결 .*허용 호출 결과 'CONNECT 403 EGRESS_DENIED'"; then echo "OK: egress 에서 받는 쪽을 빼면 연결이 막혀 시험이 실패한다(변이 확인)"; exit 0; fi
echo "FAIL: 변이(egress 에서 받는 쪽 제거)가 시험을 실패시키지 못했다 rc=$rc" >&2; printf '%s\n' "$out" | tail -5 >&2; exit 1
