#!/usr/bin/env bash
# TLS 사이드카 단독 시험(ADR 0060). 사용: bash scripts/test-tls-sidecar.sh   (Docker 필요, 다른 영역·이미지 빌드 필요 없음, 호스트 포트 없음)
# step-ca(잠금 이미지) + 서비스 사이드카(config/tls-sidecar.caddy, 잠금 GATEWAY_IMAGE) + 앱 하나(같은 Caddy 이미지의 `respond`)를 임시 네트워크에 띄워
#  (1) 사이드카가 ACME 로 서비스 이름 인증서를 받고 https 로 앱 응답을 넘긴다
#  (2) 루트 인증서를 지정한 호출자는 검증을 통과한다 (파이썬 urllib + SSL_CERT_FILE, 제품 클라이언트와 같은 방식)
#  (3) 다른 루트(시험용 일회용 CA)만 아는 호출자는 거부된다
#  (4) 앱 포트(8080)는 사이드카가 아니라 앱이 연다: 사이드카 컨테이너는 비루트 + cap_drop ALL + 읽기 전용이다
# 실패하면 정리하기 전에 컨테이너 상태와 로그를 남긴다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
LOCK=${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}
CA_IMG=$(sed -n 's/^STEP_CA_IMAGE=//p' "$LOCK"); SC_IMG=$(sed -n 's/^GATEWAY_IMAGE=//p' "$LOCK"); UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$LOCK")
[ -n "$CA_IMG" ] && [ -n "$SC_IMG" ] && [ -n "$UTIL" ] || { echo "잠금 파일에 STEP_CA_IMAGE/GATEWAY_IMAGE/UTIL_IMAGE 가 없다"; exit 1; }
ID=tlssc-$$; NET=$ID-net; T=$(mktemp -d); chmod 755 "$T"; FAILS=0; NAME=svc-under-test
PW="$T/pw"; ( umask 077; python3 -c 'import secrets;print(secrets.token_hex(24),end="")' > "$PW" ); chmod 644 "$PW"   # 시험 임시 비밀(출력하지 않는다)
cleanup() {
  if [ "$FAILS" != 0 ]; then for c in $ID-ca $ID-app $ID-sc; do echo "--- 로그 $c (끝 15줄)"; docker logs --tail 15 "$c" 2>&1 | cut -c1-240; done; fi
  docker rm -f $ID-ca $ID-app $ID-sc $ID-rootx >/dev/null 2>&1; docker volume rm -f $ID-ca $ID-root >/dev/null 2>&1; docker network rm $NET >/dev/null 2>&1; rm -rf "$T"
}
trap cleanup EXIT
ok() { local n=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $n"; else echo "  FAIL $n"; FAILS=$((FAILS+1)); fi; }
docker network create $NET >/dev/null && docker volume create $ID-ca >/dev/null && docker volume create $ID-root >/dev/null || { echo "네트워크/볼륨 생성 실패"; exit 1; }
# 1) 인증기관: 제품 compose 의 step-ca 와 같은 명령(처음 기동에 키를 1회 만든다, 비밀번호는 로그에 찍지 않는다)
docker run -d --name $ID-ca --network $NET --network-alias step-ca --user 1000:1000 --cap-drop ALL --cap-add NET_BIND_SERVICE --security-opt no-new-privileges:true --read-only --tmpfs /tmp \
  -v $ID-ca:/home/step -v "$PW:/run/secrets/step-ca-password:ro" --entrypoint sh "$CA_IMG" -c 'test -f /home/step/config/ca.json || step ca init --name OpenIt --dns step-ca --address :9000 --provisioner admin --acme --password-file /run/secrets/step-ca-password --provisioner-password-file /run/secrets/step-ca-password >/dev/null 2>&1; exec step-ca /home/step/config/ca.json --password-file /run/secrets/step-ca-password' >/dev/null
for i in $(seq 1 60); do [ "$(docker inspect -f '{{.State.Health.Status}}' $ID-ca 2>/dev/null)" = healthy ] && break; sleep 1; done
ok "step-ca 가 healthy (ACME 공급자 활성)" bash -c '[ "$(docker inspect -f "{{.State.Health.Status}}" $1)" = healthy ] && docker run --rm -v $2:/h:ro --entrypoint grep "$3" -q ACME /h/config/ca.json' _ $ID-ca $ID-ca "$CA_IMG"
# 2) 루트 인증서(공개)만 pki-root 볼륨으로 복사(제품 compose 의 pki-root 잡과 같은 명령)
docker run --rm --user 1000:1000 --cap-drop ALL --read-only -v $ID-ca:/ca:ro -v $ID-root:/home/step --entrypoint sh "$CA_IMG" -c 'cp /ca/certs/root_ca.crt /home/step/root_ca.crt && chmod 644 /home/step/root_ca.crt'
ok "루트 인증서가 공개 볼륨에 있다 (키는 없다)" bash -c 'docker run --rm -v $1:/r:ro --entrypoint sh "$2" -c "test -s /r/root_ca.crt && [ \$(ls /r | wc -l) = 1 ]"' _ $ID-root "$CA_IMG"
# 3) 앱(8080, 평문, 컨테이너 안) + 사이드카(같은 네트워크 네임스페이스)
docker run -d --name $ID-app --network $NET --network-alias $NAME "$SC_IMG" caddy respond --listen :8080 "hello-from-app" >/dev/null
docker run -d --name $ID-sc --network container:$ID-app --user 65532:65532 --cap-drop ALL --cap-add NET_BIND_SERVICE --security-opt no-new-privileges:true --read-only --tmpfs /tmp --tmpfs /data:uid=65532,gid=65532 \
  -e TLS_NAME=$NAME -e TLS_UPSTREAM=127.0.0.1:8080 -v "$DEPLOY_ROOT/config/tls-sidecar.caddy:/etc/caddy/Caddyfile:ro" -v $ID-root:/etc/openit/pki:ro "$SC_IMG" >/dev/null
for i in $(seq 1 40); do docker logs $ID-sc 2>&1 | grep -q "certificate obtained successfully" && break; sleep 1; done
ok "사이드카가 ACME 로 서비스 이름 인증서를 받았다" bash -c 'docker logs $1 2>&1 | grep -q "certificate obtained successfully"' _ $ID-sc
CLIENT='import urllib.request,sys;print(urllib.request.urlopen("https://'$NAME'/",timeout=5).read().decode())'
ok "step-ca 루트를 아는 호출자(SSL_CERT_FILE)는 https 로 앱 응답을 받는다" bash -c '[ "$(docker run --rm --network $1 -e SSL_CERT_FILE=/pki/root_ca.crt -v $2:/pki:ro "$3" python -c "$4")" = hello-from-app ]' _ $NET $ID-root "$UTIL" "$CLIENT"
# 4) 검증 실패 거부: 일회용 다른 루트만 아는 호출자
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$T/x.key" -out "$T/other_root.crt" -subj "/CN=other-root" -days 1 >/dev/null 2>&1; chmod 644 "$T/other_root.crt"
ok "다른 루트만 아는 호출자는 검증 실패로 거부된다" bash -c '! docker run --rm --network $1 -e SSL_CERT_FILE=/pki/other_root.crt -v $2:/pki:ro "$3" python -c "$4"' _ $NET "$T" "$UTIL" "$CLIENT"
ok "루트를 지정하지 않은 호출자(시스템 신뢰 저장소)도 거부된다" bash -c '! docker run --rm --network $1 "$2" python -c "$3"' _ $NET "$UTIL" "$CLIENT"
ok "평문 http 로 사이드카 443 을 부르면 TLS 가 아니라 거부된다" bash -c '! docker run --rm --network $1 "$2" python -c "import urllib.request;urllib.request.urlopen(\"http://$3:443/\",timeout=5)"' _ $NET "$UTIL" $NAME
# 5) 사이드카 격리 상태(check-containers 와 같은 항목)
ok "사이드카는 비루트, 읽기 전용, cap_drop ALL" bash -c 'r=$(docker inspect -f "{{.Config.User}}|{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.CapDrop}}" $1); [ "$r" = "65532:65532|true|[ALL]" ]' _ $ID-sc
[ "$FAILS" = 0 ] && echo "통과: TLS 사이드카 단독 시험" || echo "실패: $FAILS건"
exit $FAILS
