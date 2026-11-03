# 0060. 영역 사이 통신은 TLS: 서비스 사이드카 + step-ca + PostgreSQL TLS

## 상태
채택(U99). 측정하지 않은 값은 아래에 "측정 안 함"이라 적는다.

## 맥락
영역은 배치와 무관해야 하고(어느 서버·지역에 있든 코드·이미지가 같다), 영역 사이 통신은 평문이 없어야 한다. 서비스는 서로를 `http://<서비스 이름>:8080` 으로 불렀고 PostgreSQL 접속도 평문이었다. 서버를 나누면 평문이 네트워크를 건넌다. 영역 코드를 바꾸지 않고(구조 규칙 1·4) 설치처 OS·Docker 설정을 고치라고 요구하지 않으며 특정 설치처를 전제하지 않아야 한다.

## 결정
1. **서비스마다 TLS 사이드카**(Caddy 공식 이미지, 게이트웨이와 같은 digest): 앱의 네트워크 네임스페이스에 붙어(`network_mode: service:<앱>`) `https://<서비스 이름>`(443)을 끝내고 `127.0.0.1:<앱 포트>`로 넘긴다. 설정 파일 하나(`config/tls-sidecar.caddy`)에 이름·상류만 환경 변수다.
2. **독립 인증기관 step-ca**(공식 이미지, digest 고정, 비루트·읽기 전용·cap_drop ALL + 파일 권한 때문에 NET_BIND_SERVICE 하나). 루트·중간 키는 처음 기동에 `step ca init` 으로 1회 만들어 `pki-ca` 볼륨에 두고, 키 암호화 비밀번호는 비밀 파일(`step-ca-password`, gen-secrets.sh)이다. ACME 공급자를 켠다. 사이드카는 ACME(RFC 8555)로 서비스 이름 인증서를 받고 자동 갱신한다(수명 24시간 = step-ca 기본).
3. 호출자는 `https://<이름>` + 루트 인증서 파일(`pki-root` 볼륨, 공개 인증서만, 읽기 전용 마운트) + `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE`(OpenSSL·requests 표준)로 검증한다. 게이트웨이 Caddyfile 은 `reverse_proxy https://<이름>` + `tls_trusted_ca_certs`, Prometheus·blackbox·json-exporter 는 `scheme: https` + `ca_file`, oauth2-proxy 는 `PROVIDER_CA_FILES`.
4. **PostgreSQL TLS**: 서버 인증서는 step-ca 가 발급(`postgres-cert`, 8시간마다 다시 받음), `postgres-reload` 가 `pg_reload_conf()` 로 읽게 한다. `pg_hba.conf` 는 네트워크 접속을 `hostssl` 만 허용한다. 접속 문자열은 `sslmode=verify-full&sslrootcert=...`(Keycloak JDBC 포함).
5. **공개 입구 인증서**: `GATEWAY_TLS_MODE` = `internal`(기본, 게이트웨이 내부 인증기관) | `files`(`GATEWAY_TLS_CERT_FILE`/`KEY_FILE` 호스트 경로) | `acme`(`GATEWAY_ACME_EMAIL`, `GATEWAY_ACME_DIRECTORY`; 도메인은 `GATEWAY_HOSTS`). Caddyfile 은 `config/gateway-tls/<모드>.caddy` 를 import 하므로 손으로 고치지 않는다. 스키마는 `GatewayEnv`.
6. 추론 서버(`compose.inference.yaml`, 다른 호스트)도 같은 사이드카를 갖고 step-ca 루트·ACME 주소를 변수로 받는다.

## 왜
- 표준: TLS 1.2+ 서버 인증, ACME(RFC 8555), 사설 PKI, OpenSSL `SSL_CERT_FILE`, PostgreSQL `sslmode=verify-full`, CIS Docker(비루트·읽기 전용·cap_drop). 서비스 토큰(Bearer, RFC 6750)은 그대로라 상호 TLS 는 쓰지 않는다.
- 사이드카는 앱 이미지와 영역 코드를 바꾸지 않고 TLS 를 얹는다(영역은 서로의 구조를 모른다). 인증서 갱신이 앱 밖에서 자동이다.
- 수명 24시간·8시간 갱신은 step-ca 기본 수명과 "수명의 1/3 마다 갱신" 관례에서 왔다. 측정 안 함.
- 사이드카를 80/443 에서 열어야 ACME 검증이 닿는다(step-ca 는 80/443 으로 소유를 확인한다). 비루트 + NET_BIND_SERVICE 로 동작하는 것을 단독 시험(`scripts/test-tls-sidecar.sh`)으로 확인했다.
- step-ca 공식 entrypoint 의 `DOCKER_STEPCA_INIT_*` 는 CA 관리 비밀번호를 컨테이너 로그에 찍는다(측정함). 비밀은 로그 금지(D84)이므로 같은 `step ca init` 을 출력 없이 직접 실행한다.

## 검토한 대안과 버리는 이유
- 영역 앱이 직접 TLS: 모든 영역 코드·이미지 변경, 갱신 로직 중복. 버린다.
- 서비스 메시(Envoy/Istio/Linkerd): 이 규모(Compose 한 서버~여러 서버)에 과하고 Kubernetes 전제. 버린다.
- Caddy 내부 CA 만(`tls internal`): 서비스마다 다른 루트가 되어 신뢰할 루트가 서비스 수만큼 늘고, 서버를 나눌 때 루트 배포가 어렵다. 단일 독립 CA 가 필요. 게이트웨이 `internal` 모드에만 남긴다.
- mTLS: 이미 서비스 토큰 계약이 있고 기기 경로만 mTLS. 버린다(복잡도 대비 이득 작음).
- postgres 를 신호(pid 공유)로 reload: check-containers 가 pid 공유를 FAIL 로 본다. SQL `pg_reload_conf()` 로 대신한다.

## 결과
- 얻는 것: 서비스 사이·DB 연결에 평문이 없다(내부 `/healthz` 루프백 프로브 제외). 서버를 나눠도 같은 이미지·코드다.
- 감수하는 것: 서비스당 컨테이너 하나 증가(자원 한도는 측정 안 함, 시작값 64m/0.25cpu). step-ca 루트 키 분실 = 전 인증서 재발급이므로 `pki-ca` 볼륨은 백업·사람 보관 대상이다. 앱 포트(8080)는 같은 Docker 네트워크 안에서 여전히 닿는다(앱이 0.0.0.0 에 바인드하므로 사이드카만으로 막지 못한다): 앱의 바인드 주소 설정이 필요하면 영역에 변경 요청을 낸다(미해결).
- `GATEWAY_TLS_MODE=internal` 은 step-ca 가 아니라 게이트웨이 내부 인증기관이다: 기본 사이트 이름(localhost, 127.0.0.1)과 사람용 이름을 step-ca 가 ACME 로 검증할 수 없다. step-ca 로 받으려면 `acme` + `GATEWAY_ACME_DIRECTORY`.

## 추가 결정 (같은 U99, 후속)
- **앱은 loopback 에 바인드한다.** 사이드카는 앱과 같은 네임스페이스라, 앱이 0.0.0.0 이면 다른 컨테이너가 앱 포트로 평문을 보낼 수 있다. 계약 v3.4.2 의 `*_HOST`(SURVEY_HOST, GATE_HOST, OPS_HOST, QA_HOST, MODEL_RUNTIME_HOST, MODEL_REGISTRY_HOST, DATASET_STORE_HOST)=127.0.0.1, Keycloak `KC_HTTP_HOST`, oauth2-proxy `--http-address` 로 막는다. 정적 시험 `test_sidecar_loopback.py`, 단독 시험에서 다른 컨테이너의 앱 포트 연결 거부를 본다. kiosk-frontend(`KIOSK_HOST`)·admin-console(`ADMIN_HOST`)은 계약 v3.4.3 부터 같은 방식이다.
- **사이드카·step-ca 는 추가 capability 가 없다.** 포트 8443 으로는 ACME 검증(80/443 으로만 온다)을 받을 수 없어(지금은 ACME 도전 없이 토큰 발급이지만 443 을 여는 방식은 그대로), 네임스페이스 소유자(지금은 `<서비스>-net`)의 sysctl `net.ipv4.ip_unprivileged_port_start=0` 으로 443 을 열고, 파일 권한이 붙은 바이너리는 /tmp 사본으로 실행한다(측정함).
- **감시는 게이트웨이를 https 로 프로브한다.** 게이트웨이 사이트 목록에 `GATEWAY_PROBE_SITE`(기본 gateway:8443)를 더하고, `gateway-root` 일회성 잡이 게이트웨이 루트(내부 CA, 또는 GATEWAY_TLS_ROOT_FILE)를 공개 볼륨으로 복사해 blackbox 가 ca_file 로 쓴다.
- **백업 저장소는 `rest:https://` 만 받는다**(restic `RESTIC_CACERT` = `BACKUP_CACERT_FILE`).
- (위 "미해결"이던 원격 호스트 발급은 아래 토큰 방식으로 풀었다.)

## 발급 방식 변경: ACME 도전 -> 일회용 토큰 + renew (같은 U99, 서버를 나누는 배치)
- **왜 ACME 도전이 아닌가.** ACME(HTTP-01/TLS-ALPN-01)는 step-ca 가 서비스 이름의 80/443 으로 들어와 소유를 검증한다. 서버를 나누면 (a) 한 서버에 서비스가 여럿이라 고정 80/443 을 서비스마다 나눌 수 없고, (b) step-ca 가 다른 서버의 사이드카로 들어오는 경로가 필요하다. 방화벽·게시 포트 규칙이 배치마다 달라진다.
- **결정.** step-ca 공식 방식인 JWK 프로비저너 + 일회용 토큰(OTT)을 쓴다. 지휘 쪽 `pki-tokens` 잡이 서비스마다 `step ca token <서비스 이름>` 을 발급해 볼륨에 두고(프로비저너 비밀번호는 이 잡만 읽는다), `<서비스>-cert` 컨테이너가 `step ca certificate <이름> --token` 으로 한 번 받은 뒤 `step ca renew --daemon` 이 기존 인증서(mTLS)로 갱신한다. 사이드카 Caddy 는 파일 인증서를 쓰고 갱신된 파일을 60초 안에 `caddy reload` 한다. 필요한 경로는 인증서 컨테이너 -> step-ca 하나뿐이다. postgres 서버 인증서도 같은 방식이다.
- **이름.** 호출자는 언제나 `https://<서비스 이름>[:<게시 포트>]` 로 부른다. 다른 서버의 서비스는 그 서버를 가리키는 `extra_hosts`(`<서비스 이름>:<서버 주소>`)로 이름을 돌린다(단독 시험 `test-tls-sidecar.sh` 가 서로 다른 Docker 망 두 개로 확인: 같은 이름은 검증 성공, 다른 이름은 거부). 배치 도구가 extra_hosts 와 게시 포트를 계산하는 일은 배치 도구(placement)의 몫이다.
- **감수.** 토큰은 5분(step 기본) 안에 써야 한다. 컨테이너를 24시간 넘게 멈췄다가 다시 시작하면(인증서 만료) `pki-tokens` 를 다시 돌려야 한다. 키 파일은 사이드카와 인증서 컨테이너가 같은 uid(1000)라 읽는다. 인증서 볼륨은 서비스마다 하나다.

## 앱이 죽거나 재시작할 때의 사이드카 (같은 U99)
- **앱에 닿지 못하면 연결을 끊는다.** 사이드카는 앱 연결 거부·타임아웃에서 응답을 만들지 않고 `handle_errors { abort }` 로 연결을 끊는다. 빈 502 를 돌려주면 게이트웨이가 정상 응답으로 받아 계약 503 `UPSTREAM_UNAVAILABLE` 을 만들지 못한다(게이트웨이의 `handle_errors` 는 프록시 오류에서만 불린다). 끊김이면 게이트웨이는 상류 프록시 오류로 보고 503 + `Retry-After` 를 낸다(오류 형식은 게이트웨이 한 곳). 서비스 사이 계약 클라이언트는 끊김을 `UNAVAILABLE` 로 받는다. 단독 시험이 앱 프로세스를 죽여 "빈 502 가 아니라 끊김"을 확인하고, 이 설정을 빼면 그 단언이 실패하는 것도 확인했다.
- ~~**상류 생존 확인과 30초.**~~ **철회(Superseded)**: 아래 "네트워크 공간 소유: `<서비스>-net`(pause)" 절이 대체한다. 5초 감시·30초 후 종료 덧대기는 삭제했다.

## 네트워크 공간 소유: `<서비스>-net`(pause) (Supersedes: 위 "상류 생존 확인과 30초" 항목, RUNTIME.md R3.2·R4.1·R4.2)

**상태.** 채택. 위 "앱에 닿지 못하면 연결을 끊는다"(`handle_errors { abort }`)는 그대로 유효하고, 같은 절의 "상류 생존 확인과 30초"(사이드카가 상류 포트 도달을 5초마다 보고 30초 실패면 종료) 항목은 **이 결정이 대체한다**(철회). 아래 `sysctl`·`network_mode: service:<앱>` 서술도 `<서비스>-net` 기준으로 읽는다.

**맥락.** 사이드카가 `network_mode: service:<앱>`이면 네트워크 공간(netns)의 소유자가 앱이다. 앱 컨테이너가 `docker stop/start`·재시작 정책으로 새 공간을 받으면 사이드카는 옛 공간에 남아 새 앱에 닿지 못한다. 단독 실험(D2 대조, `test-netns-lifetime.sh` (6))에서 재시작 뒤 사이드카와 앱의 netns가 서로 달랐고(`4026533201` / `4026532729`) 사이드카 안 `127.0.0.1:8080`은 연결 거부, 앱 안은 열려 있었다. E2E 5q에서도 사이드카가 `Exited(1)`로 죽고 앱이 돌아와도 붙지 않았다. 30초 감시 종료는 이 위에 덧댄 것이라 오히려 사이드카를 죽였다.

**결정.** 서비스마다 네트워크 공간만 갖는 작은 컨테이너 `<서비스>-net`(Kubernetes Pod의 pause와 같은 방식, 공식 `registry.k8s.io/pause:3.10`, digest 고정)를 둔다. 망·별칭(`aliases: [<서비스>]`)·게시 포트·`extra_hosts`·`sysctls`(`net.ipv4.ip_unprivileged_port_start=0`)는 `-net`에만 둔다. 앱·사이드카는 `network_mode: service:<서비스>-net`이다. 인증서 컨테이너(`-cert`)는 step-ca에만 닿으면 되므로 pki 망에 따로 둔다. `-net`은 비루트 65535, read_only, cap_drop ALL, no-new-privileges, restart unless-stopped이다. 추론 compose도 같다(`model-serving-net`이 `INFERENCE_NETWORK_MODE`·게시 포트·extra_hosts를 가진다, 새 필수 변수 `INFERENCE_PAUSE_IMAGE`).

**왜.**
- 공간의 수명을 앱·사이드카 어느 쪽 생명주기와도 분리한다. 앱이 멈추거나 다시 떠도, 사이드카가 멈추거나 다시 떠도 같은 공간에 다시 붙는다(Pod 모델).
- 실험·시험 근거: 실험 B(P4, `tlsexpb`): pause 구조에서 앱 stop 뒤 사이드카·pause가 `running`, 사이드카 안 `127.0.0.1:8080` 연결 거부, 클라이언트 `ABORT`; 앱 start 뒤 `200`. 실험 B(C4): 게이트웨이 `config/Caddyfile`의 `handle_errors` 그대로에서 앱 stop 중 `503 + Retry-After: 2 + application/json + {"code":"UPSTREAM_UNAVAILABLE"}`, start 뒤 `200`. 실험 A(P3): pause가 read_only·cap_drop ALL·no-new-privileges·65535로 뜨고 SIGTERM에 0.37초로 종료. 실험 A2(P5): `-net`이 별칭·sysctl·extra_hosts·게시 포트를 갖고 앱이 `network_mode: service:`로 붙으며, 앱에 `networks`를 두면 compose가 거부(`mutually exclusive`), 앱에 `ports`를 두면 Docker가 거부(`conflicting options: port publishing and the container type network mode`). 단독 시험: `scripts/test-netns-lifetime.sh`(앱 stop/start, 사이드카 stop/start, 앱 프로세스만 kill, 대조 (6), 모르는 루트 (7)) rc=0.

**검토한 대안과 버리는 이유.**
- 앱이 공간을 소유(기존): 앱 재시작에 사이드카가 따라가지 못한다(위 D2). 버린다.
- 사이드카가 공간을 소유: 사이드카 재시작 때 앱이 옛 공간에 남는다(대칭 문제). 앱은 영역 이미지라 사이드카를 앞세워 기동 순서를 바꾸는 것도 어렵다. 버린다.
- 감시 재시작(상류 도달이 30초 안 되면 사이드카 종료 + restart 정책): 실제로 구현했으나 앱이 느리게 뜰 때 사이드카를 죽이고, 앱이 멈춰 있는 동안 사이드카가 재시작을 반복해 E2E 5q의 계약 503을 깼다. 병을 고치지 않고 증상에 덧댄 것이라 버린다(이 문서의 "30초" 항목 철회).
- 호스트 네트워크(`network_mode: host`): 서비스끼리 포트가 겹치고 망 분리·차단 점검을 못 한다. 버린다.
- 서비스 메시·사이드카 주입: 이 규모에 과하다(위 대안 참조).

**감수하는 것.** 서비스당 컨테이너가 하나 더 늘어난다(`-net`, 메모리 16m·0.1 CPU·pids 16, 측정 안 함, 시작값). 앱·사이드카는 `networks`/`ports`/`extra_hosts`/`sysctls`를 직접 갖지 못하고 `-net`이 갖는다(정적 시험은 `scripts/compose_nets.py`의 `nets()`로 `network_mode`를 따라간다). `-net`이 죽으면 그 서비스의 앱·사이드카는 함께 공간을 잃는다(pause는 하는 일이 없어 실패 원인이 거의 없다). 배치 도구는 `-net`을 앱과 같은 서버에 둬야 한다.

## 인증서 갱신과 만료 뒤 복구 (같은 U99, 실험 C6·S8)

- **C6 (`caddy reload --force`).** 사이드카 감시 루프는 인증서 파일이 바뀌면 `caddy reload`를 부른다. 그런데 Caddy는 Caddyfile이 그대로면 reload를 건너뛰어 새 인증서를 쓰지 못한다. 실험 C(수명 5분 인증서 + `step ca renew --daemon`): 갱신으로 파일 지문은 1분마다 바뀌었지만 서빙 serial은 3분이 지나도 그대로였고(`D5ACDBC9…`), 같은 컨테이너에서 `caddy reload --force`를 부르자 serial이 `89E0F013…`로 바뀌었다. 그대로 두면 24시간 수명 인증서가 만료되어 모든 사이드카가 만료된 인증서를 냈을 것이다. 결정: 루프는 `caddy reload --force`. 시험: `scripts/test-cert-renewal.sh` (A)가 서빙 serial 변경을 단언한다.
- **S8 (만료 뒤 재시작, `[ -s ] ||` → `verify ||`).** 실험 D: 수명 5분 인증서 + 서비스 전체를 6분 정지 + 새 토큰으로 재시작하면, 이전 시작 명령(`[ -s tls.crt ] || 발급; exec step ca renew --daemon`)은 파일이 있다는 이유로 발급을 건너뛰고 renew는 `certificate expired`로 거부되어 https가 `CERTIFICATE_VERIFY_FAILED`로 남았다. 결정: 시작 명령을 `step certificate verify tls.crt --roots 루트 || step ca certificate … --token … --force; exec step ca renew --daemon …`로 바꾼다(검증 실패 = 만료·부재면 토큰 발급 경로). healthcheck도 `step certificate verify`다. 시험: `scripts/test-cert-renewal.sh` (B)가 인증서 만료를 기다린 뒤 새 토큰과 재시작으로 https 200 복구를, `scripts/test_cert_entrypoint.py`가 모든 인증서 컨테이너의 시작 명령·healthcheck가 검증을 쓰는지를 단언한다.
- **감수.** 24시간 넘게 멈춘 서비스를 다시 시작하려면 `pki-tokens`(새 토큰)가 같이 돌아야 한다(`up.sh`가 한다). 토큰은 5분 안에 써야 한다(`exp - iat = 300`초, 실험 A로 확인).

## 되돌리는 조건
인증서 발급 실패가 반복되어 서비스 가용성을 해치거나, 앱이 직접 TLS 를 지원하게 되면 사이드카를 앱 내장 TLS 로 대체하는 새 ADR 이 이 ADR 을 대체한다.
