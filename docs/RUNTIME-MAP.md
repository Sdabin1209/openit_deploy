# 실행 시 동작 계약 대응표 (RUNTIME.md R1.1 ~ R8.1)

소유: deploy. 근거: `boundary-contracts/RUNTIME.md`(f375c77)의 "배포의 대응 의무". 조항마다 **구현 위치 | 정적 점검 | 단독 시험(E2E 밖) | E2E 단계**를 한 줄로 적는다. 빈칸은 두지 않는다. 없는 것은 "없음(만들 것: …)"이다.
컴포넌트 입력·출력·실패 동작과 외부 도구 전제는 `docs/RUNTIME-COMPONENTS.md`. 전제 번호 P·X 는 그 문서 15·16절.

읽는 법.
- **정적 점검**: 컨테이너를 띄우지 않고 파일을 읽어 하는 점검(`scripts/test_*.py`, `scripts/check-*.sh`). 자체 점검 목록(`scripts/self-checks.list`)에 있다.
- **단독 시험**: E2E 전체를 돌리지 않고 Docker 로 한 부분만 돌리는 시험(`scripts/test-*.sh`).
- **E2E 단계**: `scripts/e2e.sh`/`e2e_steps.py` 의 단계·점검 이름.
- **전제 미확인**: 그 조항이 기대는 외부 도구 동작을 아직 단독 실험으로 확인하지 못했다(`RUNTIME-COMPONENTS.md` 16절). 조항이 통과해 보여도 근거가 약하다.
- **위반**: 지금 알고 있는 위반은 표 아래 "알려진 위반"에 조항 번호와 함께 적었다.

## 대응표

| 조항 | 구현 위치(파일·서비스) | 정적 점검 | 단독 시험(E2E 밖) | E2E 단계 |
|---|---|---|---|---|
| R1.1 평문 호출 경로 없음 | `compose.yaml`(모든 상류 주소 `https://<이름>`), `scripts/lib.sh registry_scheme`(레지스트리: loopback 만 http), 계약 클라이언트(loopback 밖 http 거부, 3.4.1) | `scripts/test_no_plaintext_addresses.py`, 헤드 `cross-area-check.py`(평문·검증 끄기), `scripts/test_e2e_job_urls.py` | `scripts/test-tls-sidecar.sh`("평문 http 로 사이드카 443 을 부르면 거부"), `scripts/test-split-pki.sh` | e2e.sh "도달: …"·"차단: …" 점검(https 로 부른다), 단계 9 앞부분 |
| R1.2 서버 신원 = 서비스 이름, SAN 은 이름 + 선언된 별칭 | `pki-tokens`(서비스 이름 토큰), `<서비스>-cert`(`step ca certificate <이름>`), 추론 서버 토큰의 `--san` 선언 | **없음(만들 것: 인증서 컨테이너 이름 = 서비스 이름 = 토큰 대상 이름 대조, 별칭 선언 목록 외 이름 금지 정적 점검)** | `scripts/test-tls-sidecar.sh`("다른 이름으로 부르면 인증서 이름 불일치로 거부"), `scripts/test-inference-location.sh`(SAN 이름 호출). 전제 X7 확인 | 도달 점검(이름으로 부름). 별칭(localhost)은 `/healthz model-serving (https)` |
| R1.3 호출하는 쪽은 배포가 정한 루트만 믿음, 검증 끄기 없음 | 컨테이너 `SSL_CERT_FILE=/etc/openit/pki/root_ca.crt`(compose 의 모든 앱·잡), E2E 시험 프로세스는 신뢰 묶음(게이트웨이 CA + step-ca 루트) | `scripts/test_no_plaintext_addresses.py`(검증 끄기 금지), `scripts/test_callers_trust_root.py`(호출자를 compose 환경·설정에서 뽑아 모두 SSL_CERT_FILE/CA 변수 + pki-root 마운트, 변이 확인), `scripts/test_job_env_matches_server.py` | `scripts/test-tls-sidecar.sh`("다른 루트만 아는 호출자 거부", "루트를 지정하지 않은 호출자 거부") | 단계 1~ 전체(검증 켠 채 통과), `/healthz model-serving (https)` |
| R1.4 서버가 어디 있든 호출 코드·설정 이름이 같음 | `openit_deploy/wiring/placement_tool.py`(다른 서버는 `https://<이름>:<게시 포트>` + `extra_hosts`) | `scripts/placement.py validate`(자체 점검 `test-split-placement.sh` 안), `scripts/test_pki_isolation.py` | `scripts/test-split-placement.sh`, `scripts/test-split-pki.sh`, `scripts/test-split-pki-playbook.sh`, `scripts/test-inference-location.sh`(추론 서버 분리) | 추론 서버 분리 기동(e2e.sh 샌드박스 기동, 단계 5·5s). 서버 분리 전체 E2E 는 **없음(만들 것: 분리 배치로 단계 1~5 를 도는 E2E 옵션)** |
| R2.1 중계는 앱 응답을 바꾸지 않음 | 게이트웨이 `reverse_proxy`(본문·상태·헤더 불변), TLS 종단 `reverse_proxy`(`config/tls-sidecar.caddy`) | **없음(만들 것: Caddyfile 의 `handle_response`/`header_down` 가 앱 응답을 바꾸는 지시를 허용 목록으로만 두는 정적 점검)** | `scripts/test-gateway-faults.sh`(가짜 상류 `test/gateway-oidc/fault-upstream.py` 가 403·500·503·413 BoundaryError 와 X-Test-Custom 을 낼 때 상태·본문·머리글 그대로; 변이 확인 `FAULTS_MUTATE=1`) | 단계 5a(403·401), 5d(401·403), 5k(400): 앱 오류 본문이 그대로 오는 단언 |
| R2.2 중계는 앱 대신 정상 응답(빈 2xx)을 만들지 않음 | `config/tls-sidecar.caddy` catch-all(421) | `scripts/test_health_checks_read_body.py`(본문 없는 200 을 통과로 보지 않음) | `scripts/test-tls-sidecar.sh`("모르는 Host 는 421, 빈 200 이 아니다") | e2e.sh `/healthz`·`/readyz` 점검: 중계를 거쳐(`inpy` = 앱 컨테이너 안에서 `https://<서비스 이름>`) 본문 status/ready 판정(`health_check`), 추론 서버 `getinf` 도 같다 |
| R3.1 앱 프로세스 죽음 → 503 `UPSTREAM_UNAVAILABLE` + Retry-After | 게이트웨이 `handle_errors`(502/503→503), TLS 종단의 상류 거부 시 연결 종료. 전제 X5 확인 | **없음(만들 것: Caddyfile `handle_errors` 의 502·503 → 503 JSON 과 Retry-After 지시를 확인하는 정적 점검)** | `scripts/test-gateway-faults.sh`(상류 멈춤: 503 + `{"code":"UPSTREAM_UNAVAILABLE"}` + Retry-After + application/json + 본문에 내부 정보 없음) | 단계 5q(앱 중지 → 503) — **현재 504 로 실패** |
| R3.2 앱 컨테이너 멈춤·재시작 중 → 503 (504·빈 502 아님) | 위와 같음 + 공간 소유자 `<서비스>-net`(목표, 2절). 현재는 앱이 공간 소유(위반) | 위 정적 점검(**없음, 만들 것**) | `scripts/test-gateway-faults.sh`(같은 경우 + 상류 복귀 후 200, R4.1). 컨테이너 수명 쪽은 `scripts/test-netns-lifetime.sh`(줄 T 1) | 단계 5q — **현재 504 로 실패** |
| R3.3 상류가 시간 한도 안에 답하지 않음 → 504 | Caddyfile `proxy_limits`(dial 1s, 응답 헤더 55/120s 등), `handle_errors` 504 | `scripts/test_time_chain.py`(시간 한도 사슬: 키오스크 60 > 게이트웨이 56 > 서비스 50) | `scripts/test-gateway-faults.sh`(상류 80초 무응답: 504 + UPSTREAM_UNAVAILABLE + Retry-After, 약 55초 소요) | 단계 5w(survey-service pause → 504), 5u(사람 화면 경로), 5m(model-serving 무응답) |
| R3.4 TLS 종단 자신이 멈춤·재시작 → 503 | 게이트웨이 `handle_errors`. 종단 재시작이 앱·소유자와 독립(2절 목표) | 위 정적 점검(**없음, 만들 것**) | **없음(만들 것: `test-netns-lifetime.sh` 에 종단만 멈추고 게이트웨이 503 단언)**. 전제 X2·X5 확인 | **없음(만들 것: E2E 단계 5q 변형 — 종단 컨테이너만 멈춤)** |
| R3.5 본문 상한 초과 → 413 (503 아님) | Caddyfile `request_body max_size 8MiB` + `@toolarge`(Content-Length 사전 413) | **없음(만들 것: Caddyfile 의 `max_size`·`@toolarge` 상한이 계약 상한(8MiB)과 같음을 보는 정적 점검)** | `scripts/test-gateway-faults.sh`(Content-Length 초과: 413 + PAYLOAD_TOO_LARGE + application/json, chunked 초과: 413), `scripts/test-gateway-auth.sh` | 단계 5a(8MiB 초과 본문 → 413) |
| R3.6 요청 줄·헤더가 너무 큼 → 414·431 | Caddy 기본 서버 한도(설정 없음) | **없음(만들 것: Caddyfile 에 기본 한도를 낮추거나 명시하는 `max_header_size` 지시 유무 점검)** | `scripts/test-gateway-faults.sh`(헤더 1.3MB: 431, 요청 줄 1.3MB: 414 또는 431) | **없음(만들 것: 5a 에 긴 헤더 요청 한 건)** |
| R3.7 모르는 Host/SNI → 421 | `config/tls-sidecar.caddy` 마지막 사이트(catch-all, `respond 421`) | **없음(만들 것: 사이드카 설정에 catch-all 421 이 있고 사이트 이름 `localhost` 가 없음을 보는 정적 점검)** | `scripts/test-tls-sidecar.sh`("모르는 Host 는 421 Misdirected Request") | **없음(만들 것: e2e.sh 도달 점검에 모르는 Host 한 건)** |
| R3.8 인증서 이름 불일치·모르는 루트 → 호출 실패, 게이트웨이는 503 | 클라이언트 검증(R1.3), 게이트웨이 `handle_errors` | 위 R1.3 점검 | `scripts/test-tls-sidecar.sh`("다른 루트만 아는 호출자 거부", "다른 이름으로 부르면 거부"). 게이트웨이↔서비스 사이의 503 은 **없음(만들 것: 틀린 루트를 쥔 게이트웨이로 503 단언)** | **없음(만들 것: 게이트웨이의 상류 루트를 틀리게 두는 변형)** |
| R3.9 평문 http 로 서비스 TLS 종단 → 거부 | 종단은 443 TLS 만 연다(평문 포트 없음) | `scripts/test_sidecar_loopback.py`(앱 평문 포트는 loopback), `scripts/test_no_plaintext_addresses.py` | `scripts/test-tls-sidecar.sh`("평문 http 로 사이드카 443 을 부르면 거부") | e2e.sh "차단:" 점검 일부(평문 8080 거부) |
| R3.10 데이터베이스 멈춤 → 서비스 503 `UNAVAILABLE`(`/readyz` 503) | 각 서비스(계약 의무), compose `postgres`(+`postgres-cert`) | 없음(해당 없음: 데이터베이스 장애에 대한 503 은 서비스 계약 의무이고 deploy 는 서비스 코드를 점검하지 않는다. deploy 몫은 E2E 5p·5pn 으로 관찰하는 것) | 없음(정직하게: `scripts/test-postgres.sh` 는 postgres 단독의 기동·권한·백업·복구라 서비스 응답(503 UNAVAILABLE)을 보지 않는다. 서비스를 DB 와 함께 띄워야 하는 경우라 E2E 밖 단독 시험은 만들지 않고 E2E 5p·5pn 으로만 확인한다) | 단계 5p(postgres 중지 → `/readyz` 비정상, 공개 API 503 `UNAVAILABLE` retryable), 5pn(망 분리 → 2초 안 503, 재연결 후 자동 200), 5pj(DB 중지 중 잡 실패가 드러남) |
| R3.11 인증기관 멈춤 → 이미 받은 인증서로 정상 | `<서비스>-cert`(`[ -s tls.crt ] ||` 로 기존 인증서면 재발급 안 함), `step ca renew --daemon` | **없음(만들 것: 인증서 컨테이너가 인증서 존재 시 step-ca 에 의존하지 않는 시작 경로를 가졌는지 정적 점검)** | **없음(만들 것: `test-tls-sidecar.sh` 에 step-ca 를 멈추고 기존 인증서로 https 응답 단언)**. 전제 미확인: X6 | **없음(만들 것: 단계 5q 변형 — step-ca 중지 중 환자 턴)** |
| R4.1 앱 재시작 후 같은 이름·주소로 응답 | `restart: unless-stopped`, 공간 소유자(2절 목표), 게이트웨이 `depends_on` | `scripts/test_compose_restart_policy.py`(정책 존재만) | **없음(만들 것: `test-netns-lifetime.sh` — 앱 재시작 뒤 종단 경유 200)**. 전제 X2 확인 | 단계 5q(복구, 세션 보존; 앱 `/readyz` 200 이후 게이트웨이 복구까지 걸린 시간을 Retry-After 와 비교), 5p·5pn(DB 복구) |
| R4.2 종단 재시작해도 앱 그대로 | 공간 소유자 + 종단 `restart: unless-stopped`(목표) | `scripts/test_compose_restart_policy.py` | **없음(만들 것: `test-netns-lifetime.sh` 종단만 재시작)**. 전제 X2 확인 | **없음(만들 것: 5q 변형)** |
| R4.3 복구 판단은 `/readyz` 본문 `status`, 고정 대기 없음 | `e2e_steps.py wait(...)`(폴링), `survey_ready_after` | `scripts/test_health_checks_read_body.py`(status/ready 판정까지 요구). e2e_steps.py 의 sleep 은 이유 주석이 있거나 `settled()`(값 안정)·`wait()`(조건)로 바꿨다. **무조건 sleep 금지 정적 점검: 없음(만들 것)** | 해당 없음(시험 도구 규칙) | 단계 5q·5p·5pn 의 복구 단언 |
| R4.4 인증서 사람 손 없이 갱신, 갱신 뒤 종단이 새 인증서 사용 | `<서비스>-cert`(`step ca renew --daemon --expires-in 12h`), 종단 감시 루프(`caddy reload` — 설정이 같으면 건너뜀, **`--force` 필요: V7**), `postgres-reload` | **없음(만들 것: 갱신 주기(12h)·인증서 수명(24h) 일치를 대조하는 정적 점검)** | **없음(만들 것: 수명 몇 분 인증서로 갱신·reload 일련번호 변화를 보는 `test-cert-renewal.sh`)**. 전제: X6a 확인, **X6b 반증(V7)**, P10 미확인 | **없음(만들 것: 해당 없음 — 수명 24h 라 E2E 길이 밖; 단독 시험이 대신한다)** |
| R4.5 코드 축 롤백은 같은 deploy 판의 잠금 사이에서만, 다른 판이면 어느 deploy 커밋인지 말하고 멈춤 | `scripts/rollback.sh`(후보 = lib.sh SERVICES 의 서비스 digest 전부, 키 집합이 다르면 종료 2 + 잠금을 만든 deploy 커밋 해시·`git checkout` 안내) | 없음(해당 없음: 동작 규칙이라 단독 시험이 정본) | `scripts/test-rollback.sh`(digest 빠진 잠금 건너뜀, 다른 판 잠금은 종료 2·잠금 불변·커밋 안내, 같은 판은 되돌림) | 단계 9 롤백 구간(같은 실행 안의 잠금) |
| R5.1 건강 확인은 상태 코드 + 본문 `status` | 컨테이너 healthcheck(`python urlopen`, 상태만), E2E `getinf`·`inpy`, 게이트웨이 자신의 응답(`config/Caddyfile`: `{"status":"ok"}`/`{"status":"not-ready"}`), 감시 `blackbox.yml http_2xx_gateway` 본문 정규식. 계약에 `HealthStatus` 정의가 없어 변경 요청(`docs/change-requests/CR-HealthStatus-schema.md`) | `scripts/test_health_checks_read_body.py`(본문을 읽는 줄도 status/ready 를 판정하는 흔적이 있어야 함, `body-judged`·`status-code-ok` 표시는 이유가 줄에 있다), `scripts/test_gateway_health_body.py` | `scripts/test-tls-sidecar.sh`(본문 확인) | e2e.sh `/healthz`·`/readyz` 점검 |
| R5.2 게이트웨이는 상류가 준비된 뒤 받음 | compose `gateway.depends_on`(앱·종단·oauth2-proxy `service_healthy`) | `scripts/test_gateway_depends.py` | — (정적으로 충분. 동적: `compose up --wait` 가 단독 시험 `test-idp-smoke.sh` 의 기동 구간) | `compose up --wait` 점검 |
| R6.1 앱 평문 포트는 앱·종단 밖에서 안 닿음 | 앱 `*_HOST=127.0.0.1`(계약 3.4.2·3.4.3), 공간 공유 | `scripts/test_sidecar_loopback.py` | `scripts/test-tls-sidecar.sh`("앱 포트(8080)는 연결 거부") | e2e.sh "차단:" 점검, `check-containers.sh` 런타임 |
| R6.2 호출 관계 밖의 쌍은 망에서 안 닿음 | compose `networks`(서비스 쌍별 망, `internal`), 인증서 발급용 `pki` 망은 발급 컨테이너만 | `scripts/test_service_pair_isolation.py`(허용 목록 방식: compose 에서 뽑은 호출 관계 밖의 모든 앱·게이트웨이 쌍이 공통 망 없음; 알려진 위반 V8 5쌍만 표에 허용, 변이 확인), `scripts/test_pki_isolation.py`(앱은 pki 망 없음, E2E 차단 쌍), `scripts/test_compose_no_test_doors.py` | — | e2e.sh "차단: …" 8쌍, `check-containers.sh` |
| R6.3 비밀은 파일(640 + 그룹)만 | `scripts/gen-secrets.sh`, compose `secrets`·`group_add`, `*_FILE` | `scripts/test_no_secret_in_environment.py`, `scripts/check-secret-perms.sh`, `scripts/test_caddy_secret_mounts.py`, `scripts/test_inference_group_add.py` | `scripts/test-secret-perms.sh`, `scripts/test-secret-group-read.sh`, `scripts/test-check-secrets-hidden.sh` | e2e.sh "비밀 노출 점검(check-secrets-hidden)", Keycloak `/proc/1/environ` 점검(idp 스모크) |
| R7.1 한 서버·여러 서버에서 R1~R6 이 같음 | `placement_tool.py`, `ansible/site.yml`(단계 기동), `postgres`·`step-ca`·`keycloak` 배치 가능 | `scripts/placement.py validate`, `scripts/test-sslrootcert-mounts.sh` | `scripts/test-split-placement.sh`, `scripts/test-split-pki.sh`, `scripts/test-split-pki-playbook.sh`. 전제 X4 확인, X8 반증(유지), X9 대기 | **없음(만들 것: 분리 배치로 E2E 단계 1~5 를 도는 옵션; 지금 분리는 E2E 밖)** |
| R7.2 잡은 서버와 같은 환경·비밀·신뢰 | compose YAML 앵커(`job-*` = 서버), `ENV_SERVICES` 에 잡 포함 | `scripts/test_job_env_matches_server.py`(잡·짝을 compose 에서 뽑는다, 같은 이미지; 예외 job-ops-feedback 은 같은 이름 키 값 일치 + SSL_CERT_FILE·루트 마운트 일치; 변이 확인 포함), `scripts/check_config_contracts.py`(잡 포함) | — (정적이 정본) | 단계 4a(수집기 run-once)·6(비식별 잡)·5pj |
| R8.1 503 `UNAVAILABLE` 때 로그에 예외 종류·위치 | 서비스 몫(survey-service 로그 포매터가 예외를 버렸다: 헤드가 survey 담당에 넘김) | 없음(해당 없음: 서비스 코드 점검은 서비스 몫). deploy 몫은 아래 E2E 에서 관찰 | 없음(해당 없음: 서비스 몫. survey-service 의 로그 단독 시험은 survey 담당) | **없음(만들 것: E2E 에서 503 UNAVAILABLE 을 일부러 낸 뒤 서비스 로그에 예외 종류가 남음을 단언하는 단계 한 건)** |

## 전제 상태와 근거가 약한 조항

`docs/RUNTIME-COMPONENTS.md` 16절의 결과(헤드 전달) 기준.

| 조항 | 기대는 전제 | 상태 |
|---|---|---|
| R3.1·R3.2·R3.4 | X1·X2·X5 | 확인(성립). 구현이 목표 구조에 맞춰질 때까지는 위반(V1) |
| R3.3 | X5 의 504 쪽(응답 헤더 지연) | **전제 미확인**(전달받은 요약에 없음) |
| R4.1·R4.2 | X2 | 확인(성립). 구현 대기 |
| R4.4 | X6a, X6b | X6a 확인, **X6b 반증 → 위반 V7** |
| R3.11 | X6a, P10 | X6a 확인, P10(PostgreSQL reload) **전제 미확인** |
| R1.2 | X7 | 확인(성립) |
| R7.1 | X4, X8, X9 | X4 확인, X8 반증(제약이 아니라 선택, 유지), X9 결과 대기(01:15) |

## 알려진 위반 (조항 번호)

| # | 증상(확인한 것) | 위반 조항 | 상태 |
|---|---|---|---|
| V1 | 단계 5q: 앱 중지 중 게이트웨이가 503 이 아니라 **504** (e2e-b6). 사이드카가 앱의 네트워크 공간에 붙어 앱이 멈추면 종단도 못 뜬다(`survey-service-tls` Exited(1)). | R3.2 (또한 R3.4·R4.1·R4.2 의 구조 원인) | 구현 중(TLS 보조: `<서비스>-net` 방식, 00:55). 해소 전까지 위반 |
| V2 | 종단 설정의 사이트 이름 `localhost` 가 Caddy 의 local CA 발급 정책을 자동 생성해 루트 설치 시도 경고(pki.ca.local). 선언하지 않은 별칭이 자동 발급되는 것 | R1.2(선언된 별칭만), R1.3(배포가 정한 루트만 믿음) | 고침 스크립트 작성(Host 매처, `/tmp/d10/sc.py`)만 있고 **적용 보류**(헤드의 동결 지시) |
| V3 | `rollback.sh` 가 (a) 서비스 digest 수를 4개로 고정, (b) 잠금 전체를 바꿔 다른 deploy 판(키 집합이 다른) 잠금으로 롤백하면 compose 가 거부 | **R4.5** (계약 1bb9ceb 에 반영됨) | 해소: `e4d33e9` + 잠금을 만든 deploy 커밋 안내(G7). 단독 시험 `scripts/test-rollback.sh` |
| V4 | `test-idp-smoke.sh` 가 TLS 구성에서 실패 | R1.1·R6.1 의 시험 의무(시험이 새 구성을 따라가야 한다) | 해소(TLS 보조: wo-450-pre `5e31e9a`, rc=0 보고). 이 worktree 에서는 아직 재확인하지 않음 |
| V5 | 단계 9 뒷구간(jobs·backup·rollback)이 TLS 구성에서 E2E 로 한 번도 안 돌았다 | R7.2·R1.1 의 E2E 대응 | 미해소(최종 전체 E2E 에서 처음 돈다) |
| V6 | survey-service 의 503 UNAVAILABLE 로그에 예외 종류·위치가 없었다(포매터가 트레이스를 버림) | R8.1 | survey 담당에 넘김. 해소 확인 전 |
| V7 | 인증서 갱신 뒤 사이드카 감시 루프의 `caddy reload` 가 설정이 같으면 reload 를 건너뛰어 갱신된 인증서를 서빙하지 않는다(실험 C6, 헤드 전달). 24시간 인증서가 만료되면 서비스 사이 호출이 실패한다 | **R4.4** | 구현 대상: `compose.yaml`·`compose.inference.yaml` 의 감시 루프(`caddy reload --force`) + `scripts/test-tls-sidecar.sh`, 단독 시험 "수명 5분 갱신 뒤 서빙 serial 변경"(`scripts/test-cert-renewal.sh`, 만들 것). 코드 수정은 헤드 지시 대기 |
| V8 | 호출 관계 없이 같은 망에 있는 앱 쌍 5개: admin-console↔kiosk-frontend(ui), gateway↔model-serving(serving), model-registry↔question-authoring(release), model-serving↔ops-feedback-ingest(serving), ops-feedback-ingest↔release-gate(serving). 허용 목록 방식 점검(G9)이 새로 드러냈다. | **R6.2** | 알려진 위반 표(`scripts/test_service_pair_isolation.py` KNOWN). 망을 서비스별로 다시 나누는 줄 T 1 에서 해소하고 표에서 지운다 |
