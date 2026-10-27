#!/usr/bin/env bash
# 영역 하나가 바뀌었을 때 전체 E2E 없이 (영역 시험 + check-all + 연결된 E2E 단계 --only)를 돌린다. 대응표: config/verify-areas.yaml
# 사용: scripts/verify-area.sh <영역> [--dry-run] [--tests-only] [--no-e2e 이유] [--since REF] [--allow-dirty] | --list
# 환경: VERIFY_WORKSPACE (영역 리포지토리들이 있는 폴더, 기본은 deploy 의 상위)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=python3
python3 -c 'import yaml' 2>/dev/null || { [ -x "$HERE/../.venv/bin/python" ] && PY="$HERE/../.venv/bin/python"; }
exec "$PY" "$HERE/verify_area.py" "$@"
