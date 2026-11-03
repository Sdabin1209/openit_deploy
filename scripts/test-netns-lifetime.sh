#!/usr/bin/env bash
# 네트워크 공간 수명 단독 시험(RUNTIME.md R3.1·R3.2·R4.1·R4.2, ADR 0060). 사용: bash scripts/test-netns-lifetime.sh   (Docker 필요, 고정 호스트 포트 없음)
# 서비스마다 네트워크 공간만 갖는 pause 컨테이너(<서비스>-net)가 있고, 앱·사이드카가 network_mode: container:<net> 으로 붙는다. 이 구조에서 제품 설정 그대로
# (config/tls-sidecar.caddy, 게이트웨이 config/Caddyfile 의 handle_errors)로 다음 경우의 응답을 상태 코드 + 본문 + 헤더로 단언한다:
#  (1) 정상 200  (2) 앱 컨테이너 stop: 사이드카가 살아 있고 연결을 끊고 게이트웨이는 503 {"code":"UPSTREAM_UNAVAILABLE"} + Retry-After  (3) 앱 start 뒤 200 (같은 공간에 다시 붙음)
#  (4) 사이드카 stop: 게이트웨이 503, start 뒤 200  (5) 앱 프로세스만 죽임(컨테이너는 유지, R3.1): 게이트웨이 503  (6) 앱이 공간을 소유하던 옛 구조는 앱 재시작 뒤 사이드카가 못 붙는다(대조)
# 실패하면 정리하기 전에 컨테이너 로그를 남긴다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
LOCK=${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}
CA_IMG=$(sed -n 's/^STEP_CA_IMAGE=//p' "$LOCK"); SC_IMG=$(sed -n 's/^GATEWAY_IMAGE=//p' "$LOCK"); UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$LOCK"); PAUSE=$(sed -n 's/^PAUSE_IMAGE=//p' "$LOCK")
[ -n "$CA_IMG" ] && [ -n "$SC_IMG" ] && [ -n "$UTIL" ] && [ -n "$PAUSE" ] || { echo "잠금 파일에 STEP_CA_IMAGE/GATEWAY_IMAGE/UTIL_IMAGE/PAUSE_IMAGE 가 없다"; exit 1; }
ID=nsl-$$; NET=$ID-net; T=$(mktemp -d); chmod 755 "$T"; FAILS=0
PW="$T/pw"; python3 -c 'import secrets;print(secrets.token_hex(24),end="")' > "$PW"; chmod 644 "$PW"
CAARGS="--ca-url https://step-ca:9000 --root /etc/openit/pki/root_ca.crt"
RUN='cp /usr/bin/caddy /tmp/caddy && until [ -s /certs/tls.crt ]; do sleep 1; done && touch /tmp/stamp && /tmp/caddy run --config /etc/caddy/Caddyfile & p=$!; while sleep 60; do kill -0 $p 2>/dev/null || exit 1; [ /certs/tls.crt -nt /tmp/stamp ] && touch /tmp/stamp && /tmp/caddy reload --force --config /etc/caddy/Caddyfile --address unix//tmp/caddy.sock >/dev/null 2>&1; done'
cleanup() {
  if [ "$FAILS" != 0 ]; then for c in $ID-ca $ID-n1 $ID-a1 $ID-s1 $ID-gw $ID-gw2 $ID-a2 $ID-s2; do echo "--- 로그 $c (끝 10줄)"; docker logs --tail 10 "$c" 2>&1 | cut -c1-220; done; fi
  docker ps -aq --filter "name=^$ID-" | xargs -r docker rm -f >/dev/null 2>&1; docker volume ls -q --filter "name=^$ID-" | xargs -r docker volume rm >/dev/null 2>&1; docker network rm $NET >/dev/null 2>&1; rm -rf "$T"
}
trap cleanup EXIT
ok() { local n=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $n"; else echo "  FAIL $n :: $(echo "$out" | tail -1 | cut -c1-200)"; FAILS=$((FAILS+1)); fi; }
docker network create $NET >/dev/null && for v in ca root c1 c2; do docker volume create $ID-$v >/dev/null; done || { echo "준비 실패"; exit 1; }
docker run -d --name $ID-ca --network $NET --network-alias step-ca --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges:true --read-only --tmpfs /tmp:exec -v $ID-ca:/home/step -v "$PW:/run/secrets/step-ca-password:ro" --entrypoint sh "$CA_IMG" -c 'step ca init --name Nsl --dns step-ca --address :9000 --provisioner admin --acme --password-file /run/secrets/step-ca-password --provisioner-password-file /run/secrets/step-ca-password >/dev/null 2>&1; cp /usr/local/bin/step-ca /tmp/step-ca && exec /tmp/step-ca /home/step/config/ca.json --password-file /run/secrets/step-ca-password' >/dev/null
for i in $(seq 1 60); do [ "$(docker inspect -f '{{.State.Health.Status}}' $ID-ca 2>/dev/null)" = healthy ] && break; sleep 1; done
docker run --rm --user 1000:1000 --cap-drop ALL --read-only -v $ID-ca:/ca:ro -v $ID-root:/home/step --entrypoint sh "$CA_IMG" -c 'cp /ca/certs/root_ca.crt /home/step/root_ca.crt && chmod 644 /home/step/root_ca.crt'
issue() { # issue <이름> <볼륨>
  local tok; tok=$(docker run --rm --network $NET --user 1000:1000 --cap-drop ALL --read-only --tmpfs /tmp -e STEPPATH=/tmp -v $ID-root:/etc/openit/pki:ro -v "$PW:/run/secrets/step-ca-password:ro" --entrypoint step "$CA_IMG" ca token "$1" --provisioner admin --provisioner-password-file /run/secrets/step-ca-password $CAARGS 2>/dev/null)
  docker run --rm --network $NET --user 1000:1000 --cap-drop ALL --read-only --tmpfs /tmp -e STEPPATH=/tmp -v $ID-root:/etc/openit/pki:ro -v $2:/home/step --entrypoint step "$CA_IMG" ca certificate "$1" /home/step/tls.crt /home/step/tls.key --token "$tok" $CAARGS --force >/dev/null 2>&1; }
issue app1 $ID-c1; issue app2 $ID-c2
app() { docker run -d --name $1 --network "$2" ${3:-} --cap-drop ALL --read-only --tmpfs /tmp:exec --entrypoint sh "$SC_IMG" -c 'cp /usr/bin/caddy /tmp/caddy && { /tmp/caddy respond --listen 127.0.0.1:8080 "'$4'" & exec sleep 36000; }' >/dev/null; }   # 앱 프로세스(caddy)는 PID 1 이 아니다: 프로세스만 죽여도 컨테이너는 남는다(R3.1)
sidecar() { docker run -d --name $1 --network "$2" --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges:true --read-only --tmpfs /tmp:exec --tmpfs /data:uid=1000,gid=1000 --restart unless-stopped --entrypoint sh -e TLS_NAME=$3 -e TLS_UPSTREAM=127.0.0.1:8080 -v "$DEPLOY_ROOT/config/tls-sidecar.caddy:/etc/caddy/Caddyfile:ro" -v $4:/certs:ro "$SC_IMG" -c "$RUN" >/dev/null; }
# 게이트웨이: 실제 config/Caddyfile 의 handle_errors 블록 그대로
sed -n '/^	handle_errors {/,/^	}/p' "$DEPLOY_ROOT/config/Caddyfile" > "$T/he.txt"
cat > "$T/gw.caddy" <<EOF
{
	admin off
	auto_https off
}
:8081 {
	reverse_proxy https://app1 {
		header_up Host {upstream_hostport}
		lb_try_duration 0
		transport http {
			tls_trusted_ca_certs /pki/root_ca.crt
			dial_timeout 1s
			response_header_timeout 5s
		}
	}
$(cat "$T/he.txt")
}
EOF
docker run -d --name $ID-n1 --network $NET --network-alias app1 --sysctl net.ipv4.ip_unprivileged_port_start=0 --read-only --cap-drop ALL --security-opt no-new-privileges:true --user 65535:65535 --restart unless-stopped "$PAUSE" >/dev/null
app $ID-a1 container:$ID-n1 "" hello-from-app
sidecar $ID-s1 container:$ID-n1 app1 $ID-c1
docker run -d --name $ID-gw --network $NET --user 1000:1000 --cap-drop ALL --read-only --tmpfs /tmp:exec --tmpfs /data:uid=1000,gid=1000 -v "$T/gw.caddy:/etc/caddy/Caddyfile:ro" -v $ID-root:/pki:ro --entrypoint sh "$SC_IMG" -c 'cp /usr/bin/caddy /tmp/caddy && exec /tmp/caddy run --config /etc/caddy/Caddyfile' >/dev/null
for i in $(seq 1 30); do docker exec $ID-s1 nc -z 127.0.0.1 443 2>/dev/null && break; sleep 1; done; sleep 2
# 게이트웨이 호출: "상태|Retry-After|Content-Type|본문" 한 줄
gw() { docker run --rm --network $NET "$UTIL" python -c '
import urllib.request,urllib.error
try:
    r=urllib.request.urlopen("http://'$ID'-gw:8081/",timeout=10); print("|".join(["%d"%r.status,r.headers.get("Retry-After") or "-",r.headers.get("Content-Type") or "-",r.read().decode()[:40]]))
except urllib.error.HTTPError as e: print("|".join(["%d"%e.code,e.headers.get("Retry-After") or "-",e.headers.get("Content-Type") or "-",e.read().decode()[:60]]))
except Exception as e: print("ERR|-|-|"+type(e).__name__)' 2>&1 | tail -1; }
want200() { [ "$(gw)" = "200|-|text/plain; charset=utf-8|hello-from-app" ] || [ "$(gw | cut -d'|' -f1,4)" = "200|hello-from-app" ]; }
want503() { [ "$(gw)" = '503|2|application/json|{"code":"UPSTREAM_UNAVAILABLE"}' ]; }
ok "(1) 정상: 게이트웨이 -> 사이드카 -> 앱 200 + 본문" want200
docker stop $ID-a1 >/dev/null; sleep 1
ok "(2) 앱 컨테이너 stop: pause·사이드카는 살아 있다" bash -c '[ "$(docker inspect -f "{{.State.Status}}" $1)" = running ] && [ "$(docker inspect -f "{{.State.Status}}" $2)" = running ]' _ $ID-n1 $ID-s1
ok "(2) 앱 stop: 게이트웨이는 503 + Retry-After 2 + application/json + {\"code\":\"UPSTREAM_UNAVAILABLE\"}" want503
docker start $ID-a1 >/dev/null; sleep 2
ok "(3) 앱 start 뒤: 같은 공간에 다시 붙어 200" want200
docker stop $ID-s1 >/dev/null; sleep 1
ok "(4) 사이드카 stop: 게이트웨이 503 (본문·헤더까지)" want503
docker start $ID-s1 >/dev/null; for i in $(seq 1 30); do docker exec $ID-s1 nc -z 127.0.0.1 443 2>/dev/null && break; sleep 1; done; sleep 1
ok "(4) 사이드카 start 뒤 200" want200
docker exec $ID-a1 sh -c 'kill $(pidof caddy)' >/dev/null 2>&1; sleep 1
ok "(5) 앱 프로세스만 죽임(컨테이너 유지, R3.1): 게이트웨이 503 (본문·헤더까지)" bash -c '[ "$(docker inspect -f "{{.State.Status}}" $1)" = running ]' _ $ID-a1
ok "(5) 같은 경우의 응답" want503
# (6) 대조: 앱이 공간을 소유(옛 구조): 앱 재시작 뒤 사이드카는 옛 공간에 남는다
docker run -d --name $ID-a2 --network $NET --network-alias app2 --sysctl net.ipv4.ip_unprivileged_port_start=0 --cap-drop ALL --read-only --tmpfs /tmp:exec --entrypoint sh "$SC_IMG" -c 'cp /usr/bin/caddy /tmp/caddy && exec /tmp/caddy respond --listen 127.0.0.1:8080 hello2' >/dev/null
sidecar $ID-s2 container:$ID-a2 app2 $ID-c2; sleep 5
docker stop $ID-a2 >/dev/null; docker start $ID-a2 >/dev/null; sleep 3
ok "(6) 대조: 앱이 공간을 소유하면 앱 재시작 뒤 사이드카와 앱의 네트워크 공간이 달라진다" bash -c '[ "$(docker exec $1 readlink /proc/self/ns/net)" != "$(docker exec $2 readlink /proc/self/ns/net)" ]' _ $ID-s2 $ID-a2
# (7) R3.8: 게이트웨이가 서비스 인증서를 모르는 루트로 보면(신뢰 묶음에 없음) 503 UPSTREAM_UNAVAILABLE (평문으로 물러서거나 검증을 끄지 않는다)
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$T/other.key" -out "$T/other_root.crt" -subj "/CN=other-root" -days 1 >/dev/null 2>&1; chmod 644 "$T/other_root.crt"
sed 's#/pki/root_ca.crt#/other/other_root.crt#' "$T/gw.caddy" > "$T/gw2.caddy"
docker run -d --name $ID-gw2 --network $NET --user 1000:1000 --cap-drop ALL --read-only --tmpfs /tmp:exec --tmpfs /data:uid=1000,gid=1000 -v "$T/gw2.caddy:/etc/caddy/Caddyfile:ro" -v "$T/other_root.crt:/other/other_root.crt:ro" --entrypoint sh "$SC_IMG" -c 'cp /usr/bin/caddy /tmp/caddy && exec /tmp/caddy run --config /etc/caddy/Caddyfile' >/dev/null; sleep 3
# 왜 sleep 3: busybox nc 는 입력이 끝나면 곧바로 닫혀 응답을 못 읽는다. 응답을 읽을 때까지 입력을 열어 둔다(준비 대기가 아니다)
O7=$( { printf 'GET / HTTP/1.0\r\n\r\n'; sleep 3; } | docker exec -i $ID-gw2 nc 127.0.0.1 8081 2>&1)   # 게이트웨이 컨테이너 안 loopback 으로 호출한다(원시 응답: 상태 줄 + 머리글 + 본문)
ok "(7) R3.8 서비스 인증서가 신뢰 묶음 밖의 루트면 게이트웨이는 503 + Retry-After 2 + application/json + {\"code\":\"UPSTREAM_UNAVAILABLE\"}" bash -c 'echo "$1" | grep -q "^HTTP/1.[01] 503" && echo "$1" | grep -qi "^Retry-After: 2" && echo "$1" | grep -qi "^Content-Type: application/json" && echo "$1" | grep -q "{\"code\":\"UPSTREAM_UNAVAILABLE\"}"' _ "$O7"
[ "$FAILS" = 0 ] && echo "통과: 네트워크 공간 수명 단독 시험" || echo "실패: $FAILS건"
exit $FAILS
