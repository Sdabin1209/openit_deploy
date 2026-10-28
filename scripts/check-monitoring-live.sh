#!/usr/bin/env bash
# 떠 있는 감시 스택(compose.monitoring.yaml)이 실제 서비스를 보고 있는지 Prometheus API 로 확인한다(ADR 0037). 읽기 전용.
# 사용: check-monitoring-live.sh <compose 프로젝트>     통과 조건: gateway /healthz, release-gate /readyz, model-serving /readyz 탐침이 성공(1),
#   release-gate 판정 루프 지표가 읽히고(연속 실패 3 미만), node_exporter 디스크 지표가 있으며, Alertmanager 가 살아 있다. 최대 180초 기다린다(첫 스크랩 1분 주기).
set -uo pipefail
DEPLOY_NO_DOCKER=1; source "$(dirname "$0")/lib.sh"; detect_docker
P=${1:?compose 프로젝트}
PP=$(port_of "${P}-prometheus-1" 9090) || true; AP=$(port_of "${P}-alertmanager-1" 9093) || true
[ -n "$PP" ] && [ -n "$AP" ] || die "프로젝트 $P 에 prometheus/alertmanager 컨테이너의 호스트 포트가 없다(COMPOSE_EXTRA=compose.monitoring.yaml 로 올렸나?)"
q(){ curl -s --max-time 5 "http://127.0.0.1:$PP/api/v1/query" --data-urlencode "query=$1" | python3 -c 'import json,sys;d=json.load(sys.stdin);r=d["data"]["result"];print(r[0]["value"][1] if r else "")' 2>/dev/null; }
want(){ local expr=$1 pred=$2 i v; for i in $(seq 1 60); do v=$(q "$expr"); [ -n "$v" ] && python3 -c "import sys;v=float(sys.argv[1]);sys.exit(0 if $pred else 1)" "$v" && { echo "  ok   $expr = $v"; return 0; }; sleep 3; done; echo "  FAIL $expr (마지막 값 '${v:-없음}', 조건 $pred)"; return 1; }
rc=0
want 'probe_success{instance="http://gateway:8080/healthz"}' 'v==1' || rc=1
want 'probe_success{instance="http://release-gate:8080/readyz"}' 'v==1' || rc=1
want 'probe_success{instance="http://model-serving:8080/readyz"}' 'v==1' || rc=1
want 'openit_gate_judging_consecutive_failures' 'v<3' || rc=1
want 'max(node_filesystem_size_bytes)' 'v>0' || rc=1
[ "$(curl -s --max-time 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$AP/-/healthy")" = 200 ] && echo "  ok   Alertmanager healthy" || { echo "  FAIL Alertmanager"; rc=1; }
exit $rc
