#!/usr/bin/env bash
# doctor.sh 자기 점검: 영역 목록(head/shared/areas.json)을 읽지 못하면 '통과'가 아니라 '확인 못 함'이고 종료 코드가 실패이며 "0개"를 세지 않는다.
# 읽을 수 있으면 '확인 못 함'이 나오지 않는다. (이 호스트의 다른 FAIL/WARN 은 판정하지 않는다)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rc=0
out=$(AREAS_FILE=/nonexistent/areas.json bash "$HERE/doctor.sh" 2>&1); r=$?
[ $r != 0 ] && echo "  ok   목록을 못 읽으면 종료 코드가 실패($r)" || { echo "  FAIL 못 읽었는데 종료 코드 0"; rc=1; }
grep -q '\[확인 못 함\] 영역 목록' <<<"$out" && echo "  ok   '확인 못 함'으로 알린다" || { echo "  FAIL '확인 못 함' 표시가 없다"; rc=1; }
grep -q 'doctor: 통과' <<<"$out" && { echo "  FAIL 못 읽었는데 '통과'로 끝났다"; rc=1; } || echo "  ok   '통과'로 끝나지 않는다"
grep -q '형제 리포 0개' <<<"$out" && { echo "  FAIL 형제 리포를 0개로 셌다"; rc=1; } || echo "  ok   형제 리포 '0개'를 세지 않는다"
out=$(bash "$HERE/doctor.sh" 2>&1)
grep -q '\[확인 못 함\]' <<<"$out" && { echo "  FAIL 읽을 수 있는데 '확인 못 함'이 나왔다"; rc=1; } || echo "  ok   읽을 수 있으면 '확인 못 함'이 없다"
[ $rc = 0 ] && echo "통과: doctor 영역 목록 자체 시험" || exit 1
