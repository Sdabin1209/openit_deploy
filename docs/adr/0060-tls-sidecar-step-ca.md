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
- **사이드카·step-ca 는 추가 capability 가 없다.** 포트 8443 으로는 ACME 검증(80/443 으로만 온다)을 받을 수 없어, 앱 네임스페이스의 sysctl `net.ipv4.ip_unprivileged_port_start=0` 으로 443 을 열고, 파일 권한이 붙은 바이너리는 /tmp 사본으로 실행한다(측정함).
- **감시는 게이트웨이를 https 로 프로브한다.** 게이트웨이 사이트 목록에 `GATEWAY_PROBE_SITE`(기본 gateway:8443)를 더하고, `gateway-root` 일회성 잡이 게이트웨이 루트(내부 CA, 또는 GATEWAY_TLS_ROOT_FILE)를 공개 볼륨으로 복사해 blackbox 가 ca_file 로 쓴다.
- **백업 저장소는 `rest:https://` 만 받는다**(restic `RESTIC_CACERT` = `BACKUP_CACERT_FILE`).
- **미해결:** 다른 호스트의 추론 서버 사이드카는 ACME 로 인증서를 받는데 step-ca 가 그 이름의 80/443 으로 닿아야 한다. 호스트 포트를 Docker 가 임의 배정하는 시험 배치에서는 검증이 불가능하다. 원격 호스트용 발급(발급 토큰 방식 `step ca certificate` 등)은 정하지 못했다.

## 되돌리는 조건
인증서 발급 실패가 반복되어 서비스 가용성을 해치거나, 앱이 직접 TLS 를 지원하게 되면 사이드카를 앱 내장 TLS 로 대체하는 새 ADR 이 이 ADR 을 대체한다.
