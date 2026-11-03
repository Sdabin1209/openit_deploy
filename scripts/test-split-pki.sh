#!/usr/bin/env bash
# 분리 배치의 인증서 경로 시험(ADR 0060, 0061): test-tls-sidecar.sh 에 "토큰을 다른 서버 볼륨으로 전달해 그 토큰으로 인증서를 받는" 단계를 더한 것. 사용: bash scripts/test-tls-sidecar.sh   (Docker 필요, 다른 영역·이미지 빌드 필요 없음, 고정 호스트 포트 없음)
# step-ca(잠금 이미지) + 일회용 토큰(OTT) 발급 + 인증서 컨테이너(step ca certificate --token, renew 데몬) + 서비스 사이드카(config/tls-sidecar.caddy, 잠금 GATEWAY_IMAGE) + 앱 하나를 만든다.
# 확인: (1) 토큰으로 서비스 이름 인증서를 받고 https 로 앱 응답을 넘긴다 (2) 루트를 지정한 호출자는 통과, 다른 루트·시스템 저장소·평문은 거부
# (3) 앱은 loopback 에만 바인드: 다른 컨테이너에서 앱 포트는 거부 (4) 서버를 나눈 배치: 서로 다른 Docker 망의 호출자가 extra_hosts(<서비스 이름>:host-gateway)와 게시 포트로 https 검증에 성공하고, 다른 이름은 거부된다
# (5) 사이드카는 비루트·읽기 전용·cap_drop ALL·추가 capability 없음. 실패하면 정리하기 전에 컨테이너 로그를 남긴다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
LOCK=${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}
CA_IMG=$(sed -n 's/^STEP_CA_IMAGE=//p' "$LOCK"); SC_IMG=$(sed -n 's/^GATEWAY_IMAGE=//p' "$LOCK"); UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$LOCK")
[ -n "$CA_IMG" ] && [ -n "$SC_IMG" ] && [ -n "$UTIL" ] || { echo "잠금 파일에 STEP_CA_IMAGE/GATEWAY_IMAGE/UTIL_IMAGE 가 없다"; exit 1; }
ID=splitpki-$$; NET=$ID-net; NETC=$ID-netc; T=$(mktemp -d); chmod 755 "$T"; FAILS=0; NAME=svc-under-test
PW="$T/pw"; ( umask 077; python3 -c 'import secrets;print(secrets.token_hex(24),end="")' > "$PW" ); chmod 644 "$PW"   # 시험 임시 비밀(출력하지 않는다)
CAARGS="--ca-url https://step-ca:9000 --root /etc/openit/pki/root_ca.crt"
cleanup() {
  if [ "$FAILS" != 0 ]; then for c in $ID-ca $ID-app $ID-cert $ID-sc; do echo "--- 로그 $c (끝 15줄)"; docker logs --tail 15 "$c" 2>&1 | cut -c1-240; done; fi
  docker rm -f $ID-ca $ID-app $ID-cert $ID-sc >/dev/null 2>&1; docker volume rm -f $ID-ca $ID-root $ID-tok $ID-certs $ID-tokB $ID-rootB >/dev/null 2>&1; docker network rm $NET $NETC >/dev/null 2>&1; rm -rf "$T"
}
trap cleanup EXIT
ok() { local n=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $n"; else echo "  FAIL $n"; FAILS=$((FAILS+1)); fi; }
docker network create $NET >/dev/null && docker network create $NETC >/dev/null && for v in ca root tok certs tokB rootB; do docker volume create $ID-$v >/dev/null; done || { echo "네트워크/볼륨 생성 실패"; exit 1; }
# 1) 인증기관: 제품 compose 의 step-ca 와 같은 명령(처음 기동에 키를 1회 만든다, 비밀번호는 로그에 찍지 않는다)
INIT='test -f /home/step/config/ca.json || step ca init --name OpenIt --dns step-ca --address :9000 --provisioner admin --acme --password-file /run/secrets/step-ca-password --provisioner-password-file /run/secrets/step-ca-password >/dev/null 2>&1; cp /usr/local/bin/step-ca /tmp/step-ca && exec /tmp/step-ca /home/step/config/ca.json --password-file /run/secrets/step-ca-password'
docker run -d --name $ID-ca --network $NET --network-alias step-ca --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges:true --read-only --tmpfs /tmp:exec \
  -v $ID-ca:/home/step -v "$PW:/run/secrets/step-ca-password:ro" --entrypoint sh "$CA_IMG" -c "$INIT" >/dev/null
for i in $(seq 1 60); do [ "$(docker inspect -f '{{.State.Health.Status}}' $ID-ca 2>/dev/null)" = healthy ] && break; sleep 1; done
ok "step-ca 가 healthy" bash -c '[ "$(docker inspect -f "{{.State.Health.Status}}" $1)" = healthy ]' _ $ID-ca
# 2) 루트 인증서(공개)만 pki-root 볼륨으로 복사(제품 compose 의 pki-root 잡과 같은 명령)
docker run --rm --user 1000:1000 --cap-drop ALL --read-only -v $ID-ca:/ca:ro -v $ID-root:/home/step --entrypoint sh "$CA_IMG" -c 'cp /ca/certs/root_ca.crt /home/step/root_ca.crt && chmod 644 /home/step/root_ca.crt'
ok "루트 인증서가 공개 볼륨에 있다 (키는 없다)" bash -c 'docker run --rm -v $1:/r:ro --entrypoint sh "$2" -c "test -s /r/root_ca.crt && [ \$(ls /r | wc -l) = 1 ]"' _ $ID-root "$CA_IMG"
# 3) 일회용 토큰(OTT): 프로비저너 비밀번호는 이 컨테이너만 읽는다(제품 compose 의 pki-tokens 잡과 같은 명령)
ok "서비스 이름 일회용 토큰이 발급된다" bash -c 'docker run --rm --network $1 --user 1000:1000 --cap-drop ALL --read-only --tmpfs /tmp -e STEPPATH=/tmp -v $2:/home/step -v $3:/etc/openit/pki:ro -v "$4:/run/secrets/step-ca-password:ro" --entrypoint sh "$5" -c "step ca token $6 --provisioner admin --provisioner-password-file /run/secrets/step-ca-password $7 > /home/step/$6.ott && chmod 644 /home/step/$6.ott && test -s /home/step/$6.ott"' _ $NET $ID-tok $ID-root "$PW" "$CA_IMG" $NAME "$CAARGS"
# 4) 앱(loopback 8080) + 인증서 컨테이너(토큰으로 1회 발급 + renew 데몬) + 사이드카(같은 네트워크 네임스페이스). 앱의 443 만 호스트에 게시한다(서버를 나눈 배치의 게시 포트)
docker run -d --name $ID-app --network $NET --network-alias $NAME --sysctl net.ipv4.ip_unprivileged_port_start=0 -p 127.0.0.1::443 "$SC_IMG" caddy respond --listen 127.0.0.1:8080 "hello-from-app" >/dev/null
# 3b) 다른 서버로 토큰 전달(ADR 0061, 플레이북과 같은 명령): step-ca 서버 쪽 볼륨에서 토큰과 루트(공개)만 JSON 으로 읽어 지휘 기계를 거쳐 다른 서버의 볼륨에 쓴다(640). 프로비저너 비밀은 CA 쪽에만 있다
docker run --rm --network none -v $ID-tok:/t:ro -v $ID-root:/r:ro "$UTIL" python -c 'import json,sys;import base64;print(base64.b64encode(json.dumps({"root":open("/r/root_ca.crt").read(),"tokens":{n:open("/t/%s.ott"%n).read().strip() for n in sys.argv[1:]}}).encode()).decode())' $NAME > "$T/tokens.json"
docker run -i --rm --network none --user 0 -v $ID-tokB:/t -v $ID-rootB:/r -v "$DEPLOY_ROOT/ansible/files/put-tokens.py:/p.py:ro" "$UTIL" python /p.py < "$T/tokens.json" >/dev/null
rm -f "$T/tokens.json"
ok "다른 서버의 토큰 볼륨에 토큰이 640 으로 있고 소유자는 인증서 컨테이너 uid 다" bash -c '[ "$(docker run --rm --network none -v $1:/t:ro "$3" sh -c "stat -c %a:%u /t/$2.ott")" = 640:1000 ]' _ $ID-tokB $NAME "$UTIL"
ok "다른 서버 볼륨에는 프로비저너 비밀·CA 키가 없다" bash -c '! docker run --rm --network none -v $1:/t:ro -v $2:/r:ro "$3" sh -c "ls /t /r | grep -Eq \"password|\\.key|ca.json\""' _ $ID-tokB $ID-rootB "$UTIL"
docker run -d --name $ID-cert --network $NET --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges:true --read-only --tmpfs /tmp -e STEPPATH=/tmp -v $ID-certs:/home/step -v $ID-rootB:/etc/openit/pki:ro -v $ID-tokB:/tokens:ro --entrypoint sh "$CA_IMG" -c \
  "[ -s /home/step/tls.crt ] || step ca certificate $NAME /home/step/tls.crt /home/step/tls.key --token \"\$(cat /tokens/$NAME.ott)\" $CAARGS --force >/dev/null; exec step ca renew --daemon --force --expires-in 12h /home/step/tls.crt /home/step/tls.key $CAARGS" >/dev/null
for i in $(seq 1 30); do docker exec $ID-cert test -s /home/step/tls.crt 2>/dev/null && break; sleep 1; done
RUN='cp /usr/bin/caddy /tmp/caddy && until [ -s /certs/tls.crt ]; do sleep 1; done && touch /tmp/stamp && /tmp/caddy run --config /etc/caddy/Caddyfile & p=$!; while sleep 60; do kill -0 $p 2>/dev/null || exit 1; [ /certs/tls.crt -nt /tmp/stamp ] && touch /tmp/stamp && /tmp/caddy reload --config /etc/caddy/Caddyfile --address unix//tmp/caddy.sock >/dev/null 2>&1; done'
docker run -d --name $ID-sc --network container:$ID-app --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges:true --read-only --tmpfs /tmp:exec --tmpfs /data:uid=1000,gid=1000 --entrypoint sh \
  -e TLS_NAME=$NAME -e TLS_UPSTREAM=127.0.0.1:8080 -v "$DEPLOY_ROOT/config/tls-sidecar.caddy:/etc/caddy/Caddyfile:ro" -v $ID-certs:/certs:ro "$SC_IMG" -c "$RUN" >/dev/null
for i in $(seq 1 40); do docker exec $ID-sc nc -z 127.0.0.1 443 2>/dev/null && break; sleep 1; done
ok "인증서 컨테이너가 토큰으로 서비스 이름 인증서를 받았다 (ACME 도전 없음)" bash -c 'docker exec $1 test -s /home/step/tls.crt && ! docker logs $2 2>&1 | grep -qi "acme"' _ $ID-cert $ID-sc
CLIENT='import urllib.request,sys;print(urllib.request.urlopen("https://'$NAME'/",timeout=5).read().decode())'
ok "step-ca 루트를 아는 호출자(SSL_CERT_FILE)는 https 로 앱 응답을 받는다" bash -c '[ "$(docker run --rm --network $1 -e SSL_CERT_FILE=/pki/root_ca.crt -v $2:/pki:ro "$3" python -c "$4")" = hello-from-app ]' _ $NET $ID-root "$UTIL" "$CLIENT"
# 5) 검증 실패 거부
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$T/x.key" -out "$T/other_root.crt" -subj "/CN=other-root" -days 1 >/dev/null 2>&1; chmod 644 "$T/other_root.crt"
ok "다른 루트만 아는 호출자는 검증 실패로 거부된다" bash -c '! docker run --rm --network $1 -e SSL_CERT_FILE=/pki/other_root.crt -v $2:/pki:ro "$3" python -c "$4"' _ $NET "$T" "$UTIL" "$CLIENT"
ok "루트를 지정하지 않은 호출자(시스템 신뢰 저장소)도 거부된다" bash -c '! docker run --rm --network $1 "$2" python -c "$3"' _ $NET "$UTIL" "$CLIENT"
ok "평문 http 로 사이드카 443 을 부르면 거부된다" bash -c '! docker run --rm --network $1 "$2" python -c "import urllib.request;urllib.request.urlopen(\"http://$3:443/\",timeout=5)"' _ $NET "$UTIL" $NAME
ok "다른 컨테이너에서 앱 포트(8080)는 연결 거부된다 (앱은 loopback 에 바인드, 사이드카만 닿는다)" bash -c '! docker run --rm --network $1 "$2" python -c "import urllib.request;urllib.request.urlopen(\"http://$3:8080/\",timeout=5)"' _ $NET "$UTIL" $NAME
# 6) 서버를 나눈 배치: 호출자는 다른 Docker 망에 있고, 서비스 이름을 extra_hosts(host-gateway)로 서버 쪽으로 돌려 <이름>:<게시 포트> 로 부른다
HP=$(docker port $ID-app 443/tcp | head -1 | sed 's/.*://')
SPLIT='import urllib.request,sys;print(urllib.request.urlopen("https://"+sys.argv[1]+":'$HP'/",timeout=5).read().decode())'
ok "다른 망의 호출자가 extra_hosts 로 돌린 서비스 이름 + 게시 포트로 https 검증에 성공한다" bash -c '[ "$(docker run --rm --network $1 --add-host $2:host-gateway -e SSL_CERT_FILE=/pki/root_ca.crt -v $3:/pki:ro "$4" python -c "$5" $2)" = hello-from-app ]' _ $NETC $NAME $ID-root "$UTIL" "$SPLIT"
ok "다른 이름으로 같은 서버를 부르면 인증서 이름 불일치로 거부된다" bash -c '! docker run --rm --network $1 --add-host other-name:host-gateway -e SSL_CERT_FILE=/pki/root_ca.crt -v $2:/pki:ro "$3" python -c "$4" other-name' _ $NETC $ID-root "$UTIL" "$SPLIT"
# 7) 사이드카 격리 상태(check-containers 와 같은 항목)
ok "사이드카는 비루트, 읽기 전용, cap_drop ALL, 추가 capability 없음" bash -c 'r=$(docker inspect -f "{{.Config.User}}|{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.CapDrop}}|{{.HostConfig.CapAdd}}" $1); [ "$r" = "1000:1000|true|[ALL]|[]" ]' _ $ID-sc
[ "$FAILS" = 0 ] && echo "통과: TLS 사이드카 단독 시험" || echo "실패: $FAILS건"
exit $FAILS
