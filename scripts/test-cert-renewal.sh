#!/usr/bin/env bash
# 인증서 갱신·복구 단독 시험(RUNTIME.md R4.4, 실험 C6·S8, ADR 0060). 사용: bash scripts/test-cert-renewal.sh   (Docker 필요, 약 10~12분: 수명 5분 인증서가 실제로 만료되길 기다린다)
# 제품 compose.yaml 의 survey-service-cert 시작 명령을 그대로 꺼내(수명만 5분으로) 쓰고 사이드카도 제품 설정(config/tls-sidecar.caddy, 감시 루프 `caddy reload --force`)이다.
#  (A) renew 데몬이 인증서를 갱신하면 사이드카가 서빙하는 인증서 serial 이 바뀐다 (reload 가 설정 그대로라도 새 파일을 읽는다)
#  (B) 서비스 전체를 인증서 수명보다 오래 멈췄다 pki-tokens 재실행(새 토큰)과 함께 다시 시작하면 사람 손 없이 새 인증서를 받아 https 가 다시 검증된다 (만료 뒤 renew 는 거부되므로 검증 실패면 토큰 발급 경로)
# 실패하면 정리하기 전에 컨테이너 로그를 남긴다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
LOCK=${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}
CA_IMG=$(sed -n 's/^STEP_CA_IMAGE=//p' "$LOCK"); SC_IMG=$(sed -n 's/^GATEWAY_IMAGE=//p' "$LOCK"); UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$LOCK"); PAUSE=$(sed -n 's/^PAUSE_IMAGE=//p' "$LOCK")
[ -n "$CA_IMG" ] && [ -n "$SC_IMG" ] && [ -n "$UTIL" ] && [ -n "$PAUSE" ] || { echo "잠금 파일에 STEP_CA_IMAGE/GATEWAY_IMAGE/UTIL_IMAGE/PAUSE_IMAGE 가 없다"; exit 1; }
ID=crn-$$; NET=$ID-net; T=$(mktemp -d); chmod 755 "$T"; FAILS=0; NAME=survey-service
PW="$T/pw"; python3 -c 'import secrets;print(secrets.token_hex(24),end="")' > "$PW"; chmod 644 "$PW"
CAARGS="--ca-url https://step-ca:9000 --root /etc/openit/pki/root_ca.crt"
RUN='cp /usr/bin/caddy /tmp/caddy && until [ -s /certs/tls.crt ]; do sleep 1; done && touch /tmp/stamp && /tmp/caddy run --config /etc/caddy/Caddyfile & p=$!; while sleep 60; do kill -0 $p 2>/dev/null || exit 1; [ /certs/tls.crt -nt /tmp/stamp ] && touch /tmp/stamp && /tmp/caddy reload --force --config /etc/caddy/Caddyfile --address unix//tmp/caddy.sock >/dev/null 2>&1; done'
# 제품의 인증서 컨테이너 시작 명령(compose.yaml)을 그대로 꺼내 수명만 시험용으로 줄인다: 발급 --not-after 5m, 갱신 --expires-in 4m(수명 1분 뒤 갱신)
CERTCMD=$(DEPLOY_ROOT="$DEPLOY_ROOT" python3 - "$NAME" <<'PY'
import os, sys, yaml
svc = yaml.safe_load(open(os.path.join(os.environ["DEPLOY_ROOT"], "compose.yaml"), encoding="utf-8"))["services"][sys.argv[1] + "-cert"]
cmd = svc["entrypoint"][2].replace("$$", "$").replace("${STEP_CA_PORT:-9000}", "9000")
assert "step certificate verify" in cmd and "--expires-in 12h" in cmd, cmd
print(cmd.replace("--expires-in 12h", "--expires-in 4m").replace("--force >/dev/null;", "--not-after 5m --force >/dev/null;", 1))
PY
) || { echo "제품 compose 에서 인증서 컨테이너 시작 명령을 꺼내지 못했다"; exit 1; }
cleanup() {
  if [ "$FAILS" != 0 ]; then for c in $ID-ca $ID-n $ID-a $ID-s $ID-cert; do echo "--- 로그 $c (끝 12줄)"; docker logs --tail 12 "$c" 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | cut -c1-240; done; fi
  docker ps -aq --filter "name=^$ID-" | xargs -r docker rm -f >/dev/null 2>&1; docker volume ls -q --filter "name=^$ID-" | xargs -r docker volume rm >/dev/null 2>&1; docker network rm $NET >/dev/null 2>&1; rm -rf "$T"
}
trap cleanup EXIT
ok() { local n=$1; shift; if out=$("$@" 2>&1); then echo "  PASS $n"; else echo "  FAIL $n :: $(echo "$out" | tail -1 | cut -c1-220)"; FAILS=$((FAILS+1)); fi; }
docker network create $NET >/dev/null && for v in ca root tok certs; do docker volume create $ID-$v >/dev/null; done || { echo "준비 실패"; exit 1; }
docker run -d --name $ID-ca --network $NET --network-alias step-ca --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges:true --read-only --tmpfs /tmp:exec -v $ID-ca:/home/step -v "$PW:/run/secrets/step-ca-password:ro" --entrypoint sh "$CA_IMG" -c 'step ca init --name Crn --dns step-ca --address :9000 --provisioner admin --acme --password-file /run/secrets/step-ca-password --provisioner-password-file /run/secrets/step-ca-password >/dev/null 2>&1; cp /usr/local/bin/step-ca /tmp/step-ca && exec /tmp/step-ca /home/step/config/ca.json --password-file /run/secrets/step-ca-password' >/dev/null
for i in $(seq 1 60); do [ "$(docker inspect -f '{{.State.Health.Status}}' $ID-ca 2>/dev/null)" = healthy ] && break; sleep 1; done
docker run --rm --user 1000:1000 --cap-drop ALL --read-only -v $ID-ca:/ca:ro -v $ID-root:/home/step --entrypoint sh "$CA_IMG" -c 'cp /ca/certs/root_ca.crt /home/step/root_ca.crt && chmod 644 /home/step/root_ca.crt'
tokjob() { docker run --rm --network $NET --user 1000:1000 --cap-drop ALL --read-only --tmpfs /tmp -e STEPPATH=/tmp -v $ID-tok:/home/step -v $ID-root:/etc/openit/pki:ro -v "$PW:/run/secrets/step-ca-password:ro" --entrypoint sh "$CA_IMG" -c "step ca token $NAME --provisioner admin --provisioner-password-file /run/secrets/step-ca-password $CAARGS > /home/step/$NAME.ott && chmod 644 /home/step/$NAME.ott"; }
tokjob
docker run -d --name $ID-n --network $NET --network-alias $NAME --sysctl net.ipv4.ip_unprivileged_port_start=0 --read-only --cap-drop ALL --security-opt no-new-privileges:true --user 65535:65535 -p 127.0.0.1::443 "$PAUSE" >/dev/null
docker run -d --name $ID-a --network container:$ID-n --cap-drop ALL --read-only --tmpfs /tmp:exec --entrypoint sh "$SC_IMG" -c 'cp /usr/bin/caddy /tmp/caddy && { /tmp/caddy respond --listen 127.0.0.1:8080 hello & exec sleep 36000; }' >/dev/null
docker run -d --name $ID-cert --network $NET --user 1000:1000 --cap-drop ALL --read-only --tmpfs /tmp -e STEPPATH=/tmp -v $ID-certs:/home/step -v $ID-root:/etc/openit/pki:ro -v $ID-tok:/tokens:ro --entrypoint sh "$CA_IMG" -c "$CERTCMD" >/dev/null
sidecar() { docker run -d --name $ID-s --network container:$ID-n --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges:true --read-only --tmpfs /tmp:exec --tmpfs /data:uid=1000,gid=1000 --entrypoint sh -e TLS_NAME=$NAME -e TLS_UPSTREAM=127.0.0.1:8080 -v "$DEPLOY_ROOT/config/tls-sidecar.caddy:/etc/caddy/Caddyfile:ro" -v $ID-certs:/certs:ro "$SC_IMG" -c "$RUN" >/dev/null; }
sidecar
for i in $(seq 1 40); do docker exec $ID-s nc -z 127.0.0.1 443 2>/dev/null && break; sleep 1; done
HP=$(docker port $ID-n 443/tcp | head -1 | sed 's/.*://')
served() { echo | openssl s_client -connect 127.0.0.1:$HP -servername $NAME 2>/dev/null | openssl x509 -noout -serial 2>/dev/null | sed 's/serial=//'; }
probe() { docker run --rm --network $NET -e SSL_CERT_FILE=/pki/root_ca.crt -v $ID-root:/pki:ro "$UTIL" python -c '
import urllib.request,urllib.error,sys
try: r=urllib.request.urlopen("https://'$NAME'/",timeout=5); print("RESPONSE",r.status,r.read().decode()[:20])
except urllib.error.HTTPError as e: print("HTTP",e.code)
except Exception as e: print("FAIL",type(e).__name__)' 2>&1 | tail -1; }
S0=$(served); echo "  처음 서빙 serial: ${S0:0:16}…"
ok "처음: https 200 + 본문" bash -c '[ "$1" = "RESPONSE 200 hello" ]' _ "$(probe)"
# (A) 갱신 뒤 서빙 serial 이 바뀐다(수명 1분 뒤 갱신, 사이드카 감시 루프 60초 이내)
CHANGED=0; for i in $(seq 1 30); do sleep 10; S1=$(served); [ -n "$S1" ] && [ "$S1" != "$S0" ] && { CHANGED=1; break; }; done
ok "(A) renew 데몬이 갱신하면 사이드카가 서빙하는 인증서 serial 이 바뀐다 (caddy reload --force)" bash -c '[ "$1" = 1 ]' _ $CHANGED
ok "(A) 갱신 뒤에도 https 200" bash -c '[ "$1" = "RESPONSE 200 hello" ]' _ "$(probe)"
# (B) 전체 정지 -> 만료를 기다림 -> 새 토큰과 함께 재시작
docker stop $ID-cert $ID-s $ID-a >/dev/null
echo "  (B) 전체 정지, 인증서 만료까지 대기(최대 약 5분)"
for i in $(seq 1 45); do docker run --rm -v $ID-certs:/h:ro -v $ID-root:/pki:ro --entrypoint step "$CA_IMG" certificate verify /h/tls.crt --roots /pki/root_ca.crt >/dev/null 2>&1 || break; sleep 10; done   # 검증이 실패할 때(= 만료) 까지
ok "(B) 인증서가 실제로 만료됐다(만료된 인증서는 검증 실패)" bash -c '! docker run --rm -v $1:/h:ro -v $2:/pki:ro --entrypoint step "$3" certificate verify /h/tls.crt --roots /pki/root_ca.crt' _ $ID-certs $ID-root "$CA_IMG"
tokjob   # pki-tokens 재실행(새 토큰)
docker start $ID-a >/dev/null; docker start $ID-cert >/dev/null; sleep 5; docker start $ID-s >/dev/null
REC=0; for i in $(seq 1 24); do sleep 5; [ "$(probe)" = "RESPONSE 200 hello" ] && { REC=1; break; }; done
ok "(B) 만료 뒤 전체 재시작(새 토큰): 사람 손 없이 새 인증서를 받아 https 200 으로 복구된다 (검증 실패면 토큰 발급 경로)" bash -c '[ "$1" = 1 ]' _ $REC
[ "$FAILS" = 0 ] && echo "통과: 인증서 갱신·복구 단독 시험" || echo "실패: $FAILS건"
exit $FAILS
