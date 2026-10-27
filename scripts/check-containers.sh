#!/usr/bin/env bash
# 떠 있는 상시 서비스 컨테이너의 격리 설정을 docker inspect·exec 로 실제로 확인한다(읽기 전용; 환경 변수는 읽지 않는다).
# 항목: 비루트로 실행(exec id -u != 0), 읽기 전용 루트, cap_drop ALL(추가 capability는 gateway 의 NET_BIND_SERVICE 하나만 허용), no-new-privileges, privileged 아님, 호스트 네트워크·PID 아님,
#       docker 소켓 마운트 없음, mem_limit·pids_limit 설정됨(0 = 무제한이면 실패), 로그 회전(max-size) 설정됨.
# 사용: scripts/check-containers.sh [프로젝트]   (기본 DEPLOY_PROJECT 또는 deploy). 종료 코드 0 = 모두 통과, 1 = 하나라도 실패, 2 = 컨테이너 없음.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
P=${1:-${DEPLOY_PROJECT:-deploy}}
mapfile -t CS < <("$DOCKER" ps --filter "label=com.docker.compose.project=$P" --format '{{.Names}}' | tr -d '\r' | sort)
[ ${#CS[@]} -gt 0 ] || { echo "프로젝트 $P 의 실행 중 컨테이너가 없다"; exit 2; }
FAIL=0; N=0; BAD=()
for c in "${CS[@]}"; do
  N=$((N+1)); probs=""
  insp=$("$DOCKER" inspect "$c" --format '{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.Privileged}}|{{.HostConfig.NetworkMode}}|{{.HostConfig.PidMode}}|{{json .HostConfig.CapDrop}}|{{json .HostConfig.CapAdd}}|{{json .HostConfig.SecurityOpt}}|{{.HostConfig.Memory}}|{{.HostConfig.PidsLimit}}|{{index .HostConfig.LogConfig.Config "max-size"}}|{{range .Mounts}}{{.Source}} {{end}}' | tr -d '\r')
  IFS='|' read -r ro priv net pid capdrop capadd secopt mem pids logmax mounts <<<"$insp"
  uid=$("$DOCKER" exec "$c" id -u 2>/dev/null | tr -d '\r')
  [ -n "$uid" ] && [ "$uid" != 0 ] || probs="$probs 루트로 실행(uid=${uid:-?})"
  [ "$ro" = true ] || probs="$probs 읽기 전용 루트 아님"
  [ "$priv" = false ] || probs="$probs privileged"
  case "$net" in host) probs="$probs 호스트 네트워크";; esac
  [ -z "$pid" ] || probs="$probs PID 공유($pid)"
  [[ "$capdrop" == *ALL* ]] || probs="$probs cap_drop ALL 아님"
  case "$capadd" in null|"[]") ;; '["NET_BIND_SERVICE"]'|'["CAP_NET_BIND_SERVICE"]') case "$c" in *-gateway-*) ;; *) probs="$probs 추가 capability $capadd";; esac;; *) probs="$probs 추가 capability $capadd";; esac
  [[ "$secopt" == *no-new-privileges* ]] || probs="$probs no-new-privileges 없음"
  [ "${mem:-0}" -gt 0 ] 2>/dev/null || probs="$probs 메모리 한도 없음"
  [ "${pids:-0}" -gt 0 ] 2>/dev/null || probs="$probs pids 한도 없음"
  [ -n "$logmax" ] || probs="$probs 로그 회전 없음"
  case "$mounts" in *docker.sock*) probs="$probs docker 소켓 마운트";; esac
  if [ -n "$probs" ]; then FAIL=$((FAIL+1)); BAD+=("$c:$probs"); fi
done
if [ $FAIL = 0 ]; then echo "컨테이너 $N개 모두 통과: 비루트, 읽기 전용 루트, cap_drop ALL, no-new-privileges, privileged·호스트 네트워크·PID 공유·docker 소켓 없음, 메모리·pids 한도, 로그 회전"; exit 0; fi
printf '실패 %s/%s:\n' "$FAIL" "$N"; printf '  %s\n' "${BAD[@]}"; exit 1
