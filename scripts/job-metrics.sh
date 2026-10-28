#!/usr/bin/env bash
# 주기 잡 한 번의 결과를 node_exporter textfile collector 형식(.prom)으로 남긴다(ADR 0037). systemd 서비스의 ExecStopPost 가 부른다.
# 사용: job-metrics.sh <잡 이름> <주기 초>        환경(systemd 가 ExecStopPost 에 넣는다): SERVICE_RESULT(success|...), EXIT_STATUS
#  openit_job_last_exit_status{job_name}             0 = 성공, 1 = 실패(SERVICE_RESULT 가 success 가 아님: 종료 코드, 신호, 제한 시간 초과 모두)
#  openit_job_last_run_timestamp_seconds{job_name}   이 실행이 끝난 시각
#  openit_job_last_success_timestamp_seconds    마지막 성공 시각(실패하면 이전 값을 유지한다. 한 번도 성공 안 했으면 쓰지 않는다 -> 경보 규칙은 값이 없으면 판정하지 않는다)
#  openit_job_interval_seconds{job_name}             경보의 '주기의 2배' 기준(.timer 의 OnUnitActiveSec 과 같은 값. test-systemd-units.sh 가 대조한다)
# 왜 textfile collector 인가: 배치 잡은 스크랩 시점에 살아 있지 않다. Prometheus 문서가 권하는 방식이다(node_exporter textfile, Pushgateway 보다 단순).
# 원자적 쓰기: 임시 파일에 쓰고 mv 한다(스크랩이 반쯤 쓴 파일을 읽지 않게).
set -euo pipefail
job=${1:?잡 이름}; iv=${2:?주기 초}
[[ "$job" =~ ^[a-z][a-z0-9-]*$ ]] || { echo "잡 이름 형식 오류: $job" >&2; exit 2; }
[[ "$iv" =~ ^[0-9]+$ ]] || { echo "주기는 정수 초: $iv" >&2; exit 2; }
dir=${METRICS_DIR:-$(cd "$(dirname "$0")/.." && pwd)/state/metrics}
mkdir -p "$dir"; f="$dir/openit_job_$job.prom"
now=$(date +%s); status=1; [ "${SERVICE_RESULT:-}" = success ] && status=0
last_ok=""
if [ "$status" = 0 ]; then last_ok=$now
else last_ok=$(sed -n 's/^openit_job_last_success_timestamp_seconds{job_name="'"$job"'"} //p' "$f" 2>/dev/null | head -1 || true); fi
tmp=$(mktemp "$dir/.openit_job_$job.XXXXXX")
{
  echo "# HELP openit_job_last_exit_status 주기 잡의 마지막 실행 결과(0 성공, 1 실패)"; echo "# TYPE openit_job_last_exit_status gauge"
  echo "openit_job_last_exit_status{job_name=\"$job\"} $status"
  echo "# TYPE openit_job_last_run_timestamp_seconds gauge"; echo "openit_job_last_run_timestamp_seconds{job_name=\"$job\"} $now"
  if [ -n "$last_ok" ]; then echo "# TYPE openit_job_last_success_timestamp_seconds gauge"; echo "openit_job_last_success_timestamp_seconds{job_name=\"$job\"} $last_ok"; fi
  echo "# TYPE openit_job_interval_seconds gauge"; echo "openit_job_interval_seconds{job_name=\"$job\"} $iv"
} > "$tmp"
chmod 644 "$tmp"; mv "$tmp" "$f"
