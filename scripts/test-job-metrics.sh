#!/usr/bin/env bash
# job-metrics.sh 시험(Docker 불필요): 성공/실패 기록, 실패해도 마지막 성공 시각 유지, 잘못된 인자 거부, 임시 파일이 남지 않음.
HERE="$(cd "$(dirname "$0")" && pwd)"; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; rc=0; n=0
export METRICS_DIR="$T/m"; J="$HERE/job-metrics.sh"; F="$T/m/openit_job_x.prom"
ok(){ echo "  ok   $*"; n=$((n+1)); }; no(){ echo "  FAIL $*"; rc=1; }
SERVICE_RESULT=success bash "$J" x 600 && grep -q '^openit_job_last_exit_status{job_name="x"} 0$' "$F" && grep -q '^openit_job_last_success_timestamp_seconds{job_name="x"} [0-9]' "$F" && grep -q '^openit_job_interval_seconds{job_name="x"} 600$' "$F" && ok "성공: 상태 0, 성공 시각, 주기" || no "성공 기록"
ts=$(sed -n 's/^openit_job_last_success_timestamp_seconds{job_name="x"} //p' "$F"); sleep 1
SERVICE_RESULT=exit-code EXIT_STATUS=3 bash "$J" x 600 && grep -q '^openit_job_last_exit_status{job_name="x"} 1$' "$F" && [ "$(sed -n 's/^openit_job_last_success_timestamp_seconds{job_name="x"} //p' "$F")" = "$ts" ] && ok "실패: 상태 1, 마지막 성공 시각은 그대로" || no "실패 기록"
rm -f "$F"; SERVICE_RESULT=timeout bash "$J" x 600 && ! grep -q last_success "$F" && ok "한 번도 성공 안 했으면 성공 시각을 쓰지 않는다(경보는 값이 없으면 판정하지 않음)" || no "첫 실패"
bash "$J" 'Bad Name' 600 2>/dev/null; [ $? = 2 ] && ok "잘못된 잡 이름 거부(2)" || no "이름 검사"
bash "$J" x abc 2>/dev/null; [ $? = 2 ] && ok "정수가 아닌 주기 거부(2)" || no "주기 검사"
[ -z "$(ls -A "$T/m" | grep '^\.' || true)" ] && ok "임시 파일이 남지 않는다" || no "임시 파일 잔존"
# textfile collector 형식 검증: promtool 이 있으면 지표를 파싱해 본다(없으면 SKIP)
if command -v docker >/dev/null 2>&1 && docker image inspect "$(sed -n 's/^PROMETHEUS_IMAGE=//p' "$HERE/../locks/images.lock")" >/dev/null 2>&1; then
  docker run --rm -v "$F:/m.prom:ro" --entrypoint promtool "$(sed -n 's/^PROMETHEUS_IMAGE=//p' "$HERE/../locks/images.lock")" check metrics < "$F" >/dev/null 2>&1 && ok "promtool check metrics 통과" || no "promtool check metrics"
else echo "  SKIP promtool(PROMETHEUS_IMAGE)이 없어 형식을 검증하지 못했다(통과 아님)"; fi
[ $rc = 0 ] && echo "통과: job-metrics 자체 시험 ${n}건" || echo "실패"; exit $rc
