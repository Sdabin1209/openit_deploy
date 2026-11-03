#!/usr/bin/env bash
# 실행 중인 컨테이너의 실제 격리 상태 점검(docker inspect 로 읽기만 한다; 값·환경 변수는 보지 않는다). 사용: check-containers.sh [프로젝트 ...]   (기본: deploy deploy-registry)
# compose 파일에 적은 것이 아니라 **떠 있는 컨테이너가 실제로** 갖고 있는지 본다(감사 F1): 비root 사용자, 읽기 전용 루트, cap_drop ALL(추가 capability는 목록으로 보여 준다),
# no-new-privileges, privileged 아님, docker.sock 마운트 없음, host network/pid 아님, 메모리·pid 한도 있음, 호스트 포트는 127.0.0.1 만(아니면 WARN).
# 종료 코드 0 통과(WARN 은 통과), 1 FAIL 있음, 2 점검할 컨테이너가 없음. 한계: 이미지 안 파일 권한이나 취약점은 보지 않는다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
PROJECTS=("$@"); [ ${#PROJECTS[@]} -gt 0 ] || PROJECTS=(deploy deploy-registry)
FAILS=0; WARNS=0; N=0
for P in "${PROJECTS[@]}"; do
  ids=$("$DOCKER" ps -q --filter "label=com.docker.compose.project=$P" | tr -d '\r')
  [ -n "$ids" ] || { echo "-- $P: 떠 있는 컨테이너가 없다"; continue; }
  for id in $ids; do
    N=$((N+1))
    insp=$("$DOCKER" inspect "$id" --format '{{.Name}}|{{.Config.User}}|{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.Privileged}}|{{.HostConfig.NetworkMode}}|{{.HostConfig.PidMode}}|{{.HostConfig.Memory}}|{{.HostConfig.PidsLimit}}|{{.HostConfig.CapDrop}}|{{.HostConfig.CapAdd}}|{{.HostConfig.SecurityOpt}}|{{range .Mounts}}{{.Source}} {{end}}|{{range $p,$b := .HostConfig.PortBindings}}{{range $b}}{{.HostIp}}:{{.HostPort}} {{end}}{{end}}|{{index .Config.Labels "com.docker.compose.service"}}' | tr -d '\r')
    IFS='|' read -r name user ro priv net pidm mem pids capdrop capadd secopt mounts ports svc <<<"$insp"
    name=${name#/}; probs=(); warns=()
    uid=$("$DOCKER" exec "$id" id -u 2>/dev/null | tr -d '\r'); [ -n "$uid" ] || uid=${user%%:*}
    case "$uid" in ""|0|root) probs+=("root 로 실행 중이다(uid ${uid:-?}, Config.User='${user}')");; esac
    [ "$ro" = true ] || probs+=("루트 파일시스템이 쓰기 가능하다")
    [ "$priv" = false ] || probs+=("privileged 이다")
    case "$capdrop" in *ALL*) ;; *) probs+=("cap_drop ALL 이 아니다(CapDrop=$capdrop)");; esac
    [ "$capadd" = "[]" ] || warns+=("추가 capability: $capadd")
    case "$secopt" in *no-new-privileges*) ;; *) probs+=("no-new-privileges 가 없다");; esac
    case "$mounts" in *docker.sock*) probs+=("docker.sock 을 마운트했다");; esac
    [ "$net" != host ] || probs+=("host 네트워크이다"); [ -z "$pidm" ] || probs+=("pid 네임스페이스를 공유한다(PidMode=$pidm)")
    [ "${mem:-0}" -gt 0 ] 2>/dev/null || warns+=("메모리 한도가 없다")
    { [ "${pids:-0}" != "<nil>" ] && [ "${pids:-0}" != 0 ] && [ "${pids:-0}" != -1 ]; } 2>/dev/null || warns+=("pids 한도가 없다")
    for hp in $ports; do case "$hp" in 127.0.0.1:*) ;; *) warns+=("호스트 포트가 127.0.0.1 이 아닌 곳에 열려 있다: $hp");; esac; done
    if [ ${#probs[@]} -eq 0 ]; then echo "  OK   $name (uid $uid, 읽기 전용, cap_drop ALL)"; else for x in "${probs[@]}"; do echo "  FAIL $name: $x"; FAILS=$((FAILS+1)); done; fi
    for x in "${warns[@]+"${warns[@]}"}"; do echo "  WARN $name: $x"; WARNS=$((WARNS+1)); done
  done
done
[ $N -gt 0 ] || { echo "점검할 컨테이너가 없다"; exit 2; }
echo "-- 컨테이너 $N개: FAIL $FAILS, WARN $WARNS"; [ $FAILS = 0 ]
