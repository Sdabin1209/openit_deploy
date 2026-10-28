#!/usr/bin/env bash
# 상태 점검(읽기 전용): 스케줄러/잡 실패, 디스크 사용률, 외부 감시 대상(gateway /healthz·/readyz)을 읽는다. 종료 코드 0 OK, 1 WARN, 2 CRIT.
# 사용: scripts/check-health.sh [--monitor F] [--disk-path P]... [--disk-warn N] [--disk-crit N] [--project deploy | --readyz release-gate=URL --readyz model-serving=URL]   (docs/runbook.md 상태 감시)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=python3
python3 -c 'import yaml' 2>/dev/null || { [ -x "$HERE/../.venv/bin/python" ] && PY="$HERE/../.venv/bin/python"; }
exec "$PY" -I "$HERE/check_health.py" "$@"
