# 실행 시 컴포넌트 사이의 스키마 (deploy, 구조 규칙 5)

소유: deploy. 근거: `boundary-contracts/RUNTIME.md`(헤드 소유, 영역 사이에서 관찰되는 동작)의 "배포의 대응 의무". 이 문서는 **deploy 컴포넌트 사이**(컨테이너·서비스 단위)의
입력·출력·실패 동작을 정한다. 코드 컴포넌트(`openit_deploy/components`)는 `docs/components.md`가 정본이고, 이 문서와 겹치지 않는다. 조항별 대응표는 `docs/RUNTIME-MAP.md`다.
(파일 이름: 헤드 지시는 `docs/COMPONENTS.md` 였으나 `docs/components.md` 와 대소문자만 달라 대소문자를 가리지 않는 파일시스템에서 충돌한다. 그래서 `RUNTIME-COMPONENTS.md` 로 썼다.)

읽는 법. **확인한 것**(코드·시험으로 확인), **결정**(이 문서가 정하는 것. 구현이 다르면 위반이다)을 구분한다. 열린 항목은 없다(결정할 수 없는 것은 근거와 함께 결정으로 닫았다). 현재 구현이 결정과 다르면 그 항목은 구현이 이 문서에 맞춰질 때까지 위반으로 센다(위반 목록은 `docs/RUNTIME-MAP.md` 맨 끝).

## 0. 용어와 공통 규칙

- **서비스 이름**: compose 의 서비스 이름(예 `survey-service`). 호출하는 쪽이 아는 유일한 신원이다(RUNTIME R1.2).
- **네트워크 공간 소유자**: 한 서비스(앱)와 그 TLS 종단이 같은 loopback 을 쓰도록 네트워크 네임스페이스를 가진 컨테이너. 2절.
- **앱**: 계약 서비스 컨테이너(survey-service 등). 평문 8080 을 loopback 에만 연다(R6.1).
- 모든 컴포넌트는 입력을 파일·환경 변수·네트워크 호출로만 받고, 이웃의 내부 구조(파일 경로, 설정 키 목록)를 모른다. 비밀은 파일(640 + 그룹)만 쓴다(R6.3).
- 컴포넌트 사이 호출은 `https://<서비스 이름>` + `SSL_CERT_FILE` 로 믿는 step-ca 루트만 쓴다(R1.1, R1.3). 예외는 같은 네트워크 공간 안의 loopback 평문뿐이다.

## 1. 구성 한눈에

```
        호출자(키오스크·사람)
              │ https (게이트웨이 인증서, GATEWAY_TLS_MODE)
        ┌─────▼─────┐   forward_auth    ┌────────────┐   OIDC   ┌──────────┐
        │ gateway   ├──────────────────►│ oauth2-proxy├────────►│ keycloak │
        └─────┬─────┘                   └────────────┘          └────┬─────┘
              │ https://<서비스 이름> (step-ca 루트로 검증)             │ postgres(TLS)
   ┌──────────▼──────────┐   인증서/키 볼륨    ┌──────────────┐        │
   │ <서비스>-net(공간)   │◄─────────────────── │ <서비스>-cert │◄── 일회용 토큰 ◄── pki-tokens ◄── step-ca
   │  ├ <서비스>-tls(443) │                    └──────────────┘                      ▲
   │  └ <서비스>(loopback)│                                                    pki-root(루트 공개)
   └──────────────────────┘
```

## 2. 네트워크 공간 소유자 `<서비스>-net` (결정. 현재 구현은 "앱이 소유")

**역할.** 서비스 하나의 네트워크 네임스페이스(주소·loopback·Docker 망 가입·DNS 별칭)를 소유하고, 앱과 TLS 종단이 거기에 붙는다.

| 항목 | 내용 |
|---|---|
| 입력 | Docker 망 목록(서비스가 가입할 망, 기존 compose `networks:`가 여기로 옮겨 간다), DNS 별칭 = 서비스 이름. 이미지는 `pause`(Kubernetes Pod 방식의 표준 네임스페이스 소유 이미지, `registry.k8s.io/pause:3.10`, digest 잠금에 새 외부 이미지 1개로 추가). 셸 없음·SIGTERM 에 종료 외에는 아무 일도 하지 않는다. 읽기 전용 루트·cap_drop ALL·no-new-privileges·비루트로 뜬다는 점은 **미확인**(전제 X1). |
| 출력 | 네트워크 네임스페이스 하나(앱과 TLS 종단이 `network_mode: service:<서비스>-net`). 서비스 이름이 이 컨테이너의 별칭으로 풀린다. 호스트 포트 게시가 필요하면(서버 분리, 게이트웨이 아님) 여기서 연다. |
| 실패 동작 | 소유자가 멈추면 앱·TLS 종단도 함께 못 쓴다(공간이 없어진다). 그러므로 소유자는 **하는 일이 없고** 앱·TLS 종단의 재시작에 영향받지 않는다. 소유자 재시작은 앱·TLS 종단을 다시 붙이는 일을 요구한다(운영상 거의 일어나지 않는다). |
| 책임 | 수명이 가장 길다. `restart: unless-stopped`, 자원 한도 극소, 읽기 전용 루트, cap_drop ALL. |

**왜 이 구조인가(대안 비교, 근거는 RUNTIME R3.2·R3.4·R4.1·R4.2).**

| 안 | 앱 멈춤(R3.2) | TLS 종단 멈춤(R3.4) | 앱 재시작(R4.1) | TLS 종단 재시작(R4.2) | 비고 |
|---|---|---|---|---|---|
| A. 앱이 공간 소유(현재) | 공간이 사라져 종단도 못 뜬다. 게이트웨이가 연결을 못 맺고 시간 초과 504 가 나왔다(5q, 확인함) | 앱은 산다. 종단만 다시 붙이면 된다 | 종단을 다시 붙여야 한다(자동 아님) | 앱 영향 없음 | R3.2·R4.1 위반 |
| B. TLS 종단이 공간 소유 | 종단이 살아서 502 를 낸다. 종단이 연결을 끊으면 503 을 만들 수 있다 | 앱까지 공간을 잃는다 | 앱만 다시 붙이면 된다 | 앱을 다시 붙여야 한다 | R4.2 위반(종단 재시작이 앱 재시작을 요구) |
| C. 공간을 나누고 앱이 0.0.0.0 으로 연다 | 이름 해석 실패·연결 거부로 503 | 같음 | 이름·주소가 그대로 | 같음 | 앱 평문 포트가 망에 열린다: R6.1 위반(서비스 사이 평문 경로가 생김) |
| D. 전용 소유자 `<서비스>-net`(채택) | 소유자가 살아 있어 연결은 맺히고, 종단이 상류 거부를 즉시 연결 종료로 올려 503(R3.2) | 앱은 산다. 소유자는 산다. 503(R3.4) | 앱만 재시작. 종단은 그대로 | 종단만 재시작. 앱은 그대로 | 컨테이너가 서비스당 하나 늘어난다(감수) |
| D'. 전용 소유자를 `UTIL_IMAGE` + `sleep` 으로 | D 와 같음 | D 와 같음 | D 와 같음 | D 와 같음 | 새 외부 이미지는 없지만 셸이 있는 이미지가 서비스마다 하나 더 돈다(공격 면 증가). pause 가 더 작고 표준이라 D 를 채택한다 |
| E. 호스트 네트워크 | — | — | — | — | 격리(R6.2) 불가. 버린다 |

**전제(외부 도구 동작).**
- P3(=실험 X2·X3): Docker `network_mode: service:X` 는 X 컨테이너의 수명에 묶인다. X 가 멈추면 이를 쓰는 컨테이너는 다시 시작할 수 없고, X 가 다시 시작해 새 네임스페이스를 받으면 기존 컨테이너는 옛 네임스페이스에 남는다(5q 에서 `survey-service-tls` 가 Exited(1)로 남았다, 확인함). 확인하는 단독 시험: **없음(필요한 시험: `scripts/test-netns-lifetime.sh` — 소유자 유지 중 앱·종단을 각각 멈췄다 시작해 서로 영향 없음 확인)**.

## 3. 앱 (계약 서비스)

| 항목 | 내용 |
|---|---|
| 입력 | 환경 변수·`*_FILE` 비밀(계약 `*Env` 선언, 잡과 같은 환경 R7.2), 데이터베이스 접속 문자열(파일), 상류 서비스 주소 `https://<이름>`. |
| 출력 | loopback 의 평문 HTTP(포트 8080, `*_HOST=127.0.0.1`)로 계약 API. `/healthz`, `/readyz`(HealthStatus). |
| 실패 동작 | 프로세스 종료·컨테이너 멈춤 시 TLS 종단이 상류 연결 거부를 즉시 연결 종료로 올린다(R3.1·R3.2). 앱은 중계를 모른다. |
| 전제 | P6: `restart: unless-stopped` 는 컨테이너가 종료되면 다시 시작한다(공간 소유자가 살아 있을 때만). |

## 4. TLS 종단 `<서비스>-tls` (Caddy 사이드카)

| 항목 | 내용 |
|---|---|
| 입력 | `/certs/tls.crt`, `/certs/tls.key`(인증서 컨테이너가 쓰는 볼륨, 읽기 전용), 환경 `TLS_NAME`(서비스 이름), `TLS_UPSTREAM`(기본 127.0.0.1:8080), 설정 `config/tls-sidecar.caddy`. |
| 출력 | 443 에서 `https://<서비스 이름>`. 맞는 Host 는 상류로 전달(응답 상태·헤더·본문 불변, R2.1). 모르는 Host/SNI 는 421(R3.7). 평문 http 는 받지 않는다(R3.9). |
| 실패 동작 | 상류(앱)가 거부하면 연결을 끊어 호출자가 503 으로 해석하게 한다(빈 502 를 내지 않는다, R3.1·R2.2). 인증서 파일이 새로 바뀌면 일정 주기에 reload 한다(R4.4). 상류가 안 닿는 동안에도 종단은 종료하지 않고 계속 떠서 503 을 낸다(결정: 공간 소유자가 별도이므로 앱이 멈춰도 종단은 산다. 종단이 상류 부재로 스스로 죽으면 앱이 돌아와도 종단을 다시 올려야 해서 R3.4 의 "복구까지 재시작 없음"을 어긴다. 종단 프로세스 자체가 죽는 경우만 restart 정책이 다시 올린다. 현재 구현의 30초 종료 감시는 2절 구현과 함께 없앤다, 위반 목록 참조). |
| 전제 | P1: Caddy 는 맞는 사이트가 없으면 본문 없는 200 을 돌려준다 → 마지막 사이트(catch-all)로 421 을 낸다. 시험: `scripts/test-tls-sidecar.sh`("모르는 Host 는 421"). P2: Caddy 는 사이트 이름이 `localhost` 이면 그 이름에 내부(local) CA 발급 정책을 자동으로 만들어 루트 설치를 시도한다 → 사이트 이름 대신 Host 매처를 쓴다. 시험: **없음(필요한 시험: `caddy adapt` 결과에 internal 발급 정책이 없음을 보는 정적 시험)**. |

## 5. 인증서 컨테이너 `<서비스>-cert`, `postgres-cert`

| 항목 | 내용 |
|---|---|
| 입력 | 일회용 토큰 파일(`pki-tokens` 볼륨 `/tokens/<이름>.ott`), step-ca 루트(`pki-root` 볼륨, 읽기 전용), step-ca 주소(`https://step-ca:<포트>`). |
| 출력 | `/certs/tls.crt`, `/certs/tls.key`(서비스 이름 SAN). 갱신 데몬(`step ca renew --daemon`)이 만료 전에 같은 파일을 갈아 쓴다(R4.4). |
| 실패 동작 | 토큰이 없거나 만료(5분)면 시작 실패 → healthcheck 실패 → 종속 컨테이너(TLS 종단)가 뜨지 않는다. 이미 인증서가 있으면 토큰 없이 재시작해 갱신만 한다. 인증기관이 멈춰도 만료 전 인증서로 정상 동작한다(R3.11). |
| 전제 | P4: `step ca certificate` 는 `--token` 과 `--san` 을 함께 받지 않는다. 인증서 SAN 은 토큰이 정한다. 시험: **직접 시험 없음(필요한 시험: 토큰 SAN 과 인증서 SAN 이 같음을 보는 단독 시험)**, 간접: `scripts/test-split-pki.sh`, `scripts/test-inference-location.sh`. P5: 토큰은 일회용이고 5분 유효하다. 시험: `scripts/test-split-pki.sh`. |

## 6. `pki-tokens`, `pki-root`, `step-ca`

| 컴포넌트 | 입력 | 출력 | 실패 동작 | 전제와 시험 |
|---|---|---|---|---|
| `step-ca` | `pki-ca` 볼륨(루트·중간 키), 비밀 `step-ca-password`, 환경 `STEP_CA_PORT`·`STEP_CA_DNS_NAMES` | 인증서 서명 API(JWK 프로비저너 `admin`), 루트 인증서 | 멈추면 새 발급·갱신만 실패(R3.11). 첫 기동에 `ca init`. 루트 키 분실 = 전 인증서 재발급(백업 대상) | 시험: `scripts/test-tls-sidecar.sh` |
| `pki-root` | `pki-ca` 볼륨(읽기 전용) | `pki-root` 볼륨에 `root_ca.crt`(공개, 644) | 일회용(`restart: "no"`). 실패하면 의존 컨테이너가 시작하지 않는다 | `scripts/test-tls-sidecar.sh` |
| `pki-tokens` | `step-ca`(JWK 비밀번호 파일), 루트 | 서비스 이름마다 `/tokens/<이름>.ott`(5분 유효) | 일회용. 서비스 목록은 이 서비스의 인증서 컨테이너 목록과 같아야 한다(정적 대조 없음: 필요, 위반으로 센다) | `scripts/test-split-pki.sh` |

## 7. 게이트웨이 `gateway` (Caddy)

| 항목 | 내용 |
|---|---|
| 입력 | `config/Caddyfile`, `auth.caddy`, 환경 `GATEWAY_HOSTS`·`GATEWAY_TLS_MODE`, 비밀 파일(토큰), 상류 `https://<서비스>`(루트: `/etc/openit/pki/root_ca.crt`), `forward_auth https://oauth2-proxy`. |
| 출력 | 공개 API·사람 화면. 인증 없음: 화면 302(`/oauth2/start`), API 401+Bearer, 닫힌 면 404. 상류 장애: 503/504 JSON(R3.1~R3.4). 본문 상한 초과: 413(R3.5). |
| 실패 동작 | 상류 거부·이름 해석 실패는 502→503 `UPSTREAM_UNAVAILABLE`+`Retry-After`, 시간 초과는 504(`handle_errors`). Content-Length 가 8MiB 를 넘는 요청은 상류에 보내기 전에 413. 상류(앱·종단·oauth2-proxy)가 준비된 뒤에야 뜬다(`depends_on: service_healthy`, R5.2). |
| 더하는 머리글과 우선순위 (R2.1) | 앱이 같은 이름을 이미 정했으면 앱 값을 지우거나 바꾸지 않는다(우선순위: 앱 > 게이트웨이 선언값). 게이트웨이는 앱이 안 정했을 때만 다음을 더한다. 사이트 전체: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Strict-Transport-Security: max-age=31536000`. 상류 중계 경로: `Cache-Control: no-store`(키오스크 API·저작·검수·릴리스·oauth2 경로). `Server` 는 지운다(게이트웨이가 낸 값만). 문법: Caddy `header ?<이름> <값>`(없을 때만 설정). `header_down` 은 `?` 를 받지 않는다(2.11.7). 주의: 한 `header { }` 블록 안의 `?` 항목은 하나의 "모두 없을 때만" 조건으로 묶여 앱이 하나만 정해도 나머지가 빠지므로 머리글마다 한 줄씩 쓴다. 시험: `scripts/test-gateway-faults.sh`(앱이 Cache-Control·X-Frame-Options·Referrer-Policy 를 정하면 그대로, 안 정하면 게이트웨이 값). |
| 전제 | P7: Caddy `reverse_proxy` 는 상류 연결 실패를 502, 시간 초과를 504 로 내고, 본문 읽기 오류는 상류가 TLS 이면 413 이 아니라 502 로 올라온다. 시험: `scripts/test-gateway-auth.sh`(8MiB 413 포함). P13: Content-Length 로 사전 거절할 수 있다(위 시험). |

## 8. 사람 인증 `oauth2-proxy`, `keycloak`

| 컴포넌트 | 입력 | 출력 | 실패 동작 | 전제와 시험 |
|---|---|---|---|---|
| `oauth2-proxy` | OIDC 클라이언트 비밀(파일), 쿠키 비밀(파일), 발급자 주소 | `/oauth2/auth` 인증 확인(헤더 `X-Auth-Request-*`), 로그인·로그아웃 경로 | 멈추면 게이트웨이가 사람 경로를 503. 쿠키 만료 8시간, 갱신 5분(ADR 0058) | `scripts/test-gateway-auth.sh`(가짜 oauth2-proxy), `scripts/test-idp-smoke.sh`(**TLS 구성에 맞지 않아 실패 중**) |
| `keycloak` | `--config-file`(비밀 파일), 가져오기 realm(비밀 파일), PostgreSQL(TLS) | realm `openit` OIDC | 멈추면 새 로그인만 실패(기존 쿠키 세션은 만료까지 유효) | P11: optimized image 가 읽기 전용 루트 + tmpfs 로 기동한다 → `scripts/test-idp-smoke.sh` |

## 9. 데이터베이스 `postgres`, `postgres-cert`, `postgres-reload`

| 항목 | 내용 |
|---|---|
| 입력 | 비밀(비밀번호·접속 문자열 `db-*-dsn`), `pg_hba.conf`(TLS 접속만), 서버 인증서(`postgres-cert`가 `/pg-tls` 에 쓴다). |
| 출력 | 5432 TLS(`sslmode=verify-full`). 서비스마다 계정 분리(ADR 0055). |
| 실패 동작 | 멈추면 서비스가 계약대로 503 `UNAVAILABLE`(`/readyz` 503, R3.10). 인증서 갱신 뒤 `postgres-reload` 가 주기적으로 `pg_reload_conf()` 로 새 인증서를 읽게 한다(R4.4). |
| 전제 | P10: PostgreSQL 은 `pg_reload_conf()` 로 서버 인증서를 다시 읽는다. 시험: **없음(필요한 시험: 갱신 뒤 reload 로 새 인증서가 쓰임을 보는 단독 시험)**. 증거 시험: E2E 5p·5pn. |

## 10. `backup-target`, 백업·복구

| 항목 | 내용 |
|---|---|
| 입력 | restic REST 서버 이미지, htpasswd 파일, TLS 인증서 폴더(`BACKUP_TARGET_TLS_DIR`, 운영은 저장소 쪽 인증서). |
| 출력 | append-only restic 저장소(TLS). 서버 자격으로는 지울 수 없다. |
| 실패 동작 | 백업은 실패로 보고되고 불완전한 백업이 성공으로 남지 않는다(E2E 5b). 서버 밖 저장소는 서버 장애와 독립이다. |
| 시험 | `scripts/test-backup.sh`, E2E 5b·단계 9 백업 구간. |

## 11. 잡 (관리 프로세스)

| 항목 | 내용 |
|---|---|
| 입력 | 서버와 같은 환경·비밀·신뢰(YAML 앵커, R7.2). 예외: `job-ops-feedback`(별도 프로그램), `ops-feedback-migrate`(소유자 DSN). |
| 출력 | run-once 결과(종료 코드, 마지막 줄 JSON). 멱등. |
| 실패 동작 | 의존이 멈춰 있으면 실패가 드러난다(조용히 성공하지 않는다, E2E 5pj). |
| 시험 | `scripts/test_job_env_matches_server.py`, `scripts/test_sd_jobs.py`, `scripts/test_e2e_job_urls.py`, E2E 4a·6·5pj. |

### 11.1 잡마다 계약 (R9.2)

공통(근거 따라 결정): 입력은 인자·설정 파일·이 표의 키만 받는다(R9.1). 시간 한도는 systemd `TimeoutStartSec=3600`(`config/systemd/openit-*.service`)이다. 한도는 측정하지 않았다 — 가장 긴 주기(1시간, ops-feedback)가 한도 안에 끝난다는 상한이며 정상 실행 시간은 이보다 훨씬 짧다고 가정할 뿐이다(측정하면 이 값을 고친다). 겹침 방지: 잡마다 `Type=oneshot` systemd 서비스이고, 이미 실행 중인 서비스 유닛은 타이머가 다시 시작해도 두 번째가 뜨지 않는다(systemd.service, systemd.timer: 유닛당 한 인스턴스). 그래서 앱 안의 `flock` 을 따로 두지 않는다(대안: 파일 잠금 — 같은 컨테이너 안 중복만 막고 유닛 단위 보장이 이미 있어 이중 장치라 버린다). 백업(`pg-backup.sh`, `backup.sh`)은 호스트 스크립트라 `flock` 을 쓴다. 출력: 종료 코드 0=성공, 0 아님=실패, 마지막 줄은 한 줄 JSON(CONVENTIONS 3절의 `BoundaryError` 형식은 실패 때 쓴다). 멱등이다.

| 잡 | 필수 입력(환경 키·`*_FILE`) | 주기 | 출력(마지막 줄 JSON) |
|---|---|---|---|
| `job-survey-purge` | 문진 서비스 서버와 같은 환경(`survey.env`, `*_FILE` 비밀 전부 서버와 같은 YAML 앵커 `survey_env`) | 86400s | 지운 개수 한 줄(compose 주석에서 확인) |
| `job-question-authoring-purge` | 저작 서버와 같은 환경(`qa_env`) | 86400s | 지운 개수 한 줄(compose 주석에서 확인) |
| `job-release-gate-prune` | 출고 게이트 서버와 같은 환경(`gate_env`), 인자 `--dry-run` 은 미리보기 | 86400s | 한 줄 JSON(키는 잡 코드가 정한다, 이 문서가 확인하지 않았다) |
| `job-release-gate-collect` | 출고 게이트 서버와 같은 환경(`gate_env`), I1·I3 읽기 토큰 파일 | 600s | 한 줄 JSON(키는 잡 코드가 정한다, 이 문서가 확인하지 않았다) |
| `job-ops-feedback` | `OPS_DEID_SALT_FILE`, `OPS_GATE_READ_TOKEN_FILE`, `OPS_GATE_WRITE_TOKEN_FILE`, `OPS_LOG_DATABASE_URL_FILE`, `OPS_FAILURE_DATABASE_URL_FILE`, `SSL_CERT_FILE`, 설정 파일 `/config/job.yaml` | 3600s | 한 줄 JSON(키는 잡 코드가 정한다, 이 문서가 확인하지 않았다) |
| `ops-feedback-migrate` | 소유자 DSN 파일 한 개(일회성, 주기 없음, 겹침은 compose 가 일회성 서비스로 한 번만 띄운다) | 기동 때 1회 | 종료 코드 |

주기는 `config/systemd/openit-*.timer` 의 `OnUnitActiveSec` 값이다(옛 스케줄러의 간격을 그대로 옮긴 것, 타이머 파일 주석). 각 잡의 환경 키 전체 목록은 서버와 같은 것이라 서버 절을 따른다(복사하지 않는다, `scripts/test_job_env_matches_server.py` 가 같음을 지킨다).

## 12. 감시 (prometheus, alertmanager, blackbox, exporter)

| 항목 | 내용 |
|---|---|
| 입력 | `compose.monitoring.yaml`, 탐침 대상(게이트웨이 `/healthz`, 서비스 `/readyz`), 규칙 파일. |
| 출력 | 지표·경보. 게이트웨이 평문 8080 `/healthz` 만 평문 탐침(상류와 무관한 정적 200, 컨테이너 내부 프로브 예외). |
| 실패 동작 | 감시가 멈춰도 제품은 영향받지 않는다. |
| 시험 | `scripts/test-monitoring.sh`, `scripts/check-monitoring-live.sh`. |

### 12.1 경보 목록 (R8.2)

| 경보 | 조건(결정) | 근거 | 현재 구현 |
|---|---|---|---|
| 인증서 발급·갱신 실패 | `<서비스>-cert` 컨테이너가 종료·재시작 반복하거나 갱신 로그가 실패(지표: 인증서 파일 갱신 시각이 수명의 2/3 지난 뒤에도 안 바뀜) | step-ca 갱신 데몬은 수명의 2/3 지점에 갱신한다(smallstep 문서) | 규칙 없음: 위반으로 센다 |
| 인증서 남은 수명 < 1/3 | 서비스 `:443` 인증서 `notAfter` 까지 남은 시간 / 전체 수명 < 1/3 (blackbox `probe_ssl_earliest_cert_expiry`) | RUNTIME R8.2 | 규칙 없음: 위반으로 센다 |
| 디스크 사용률 80% 이상 | 기존 `DiskUsageWarning`(80%), `DiskUsageCritical`(90%) | RUNTIME R8.2 | 있음(`config/prometheus/rules/openit.yml`) |
| 상류 `/readyz` 실패 | `ProbeDown`(`probe_success == 0`) | RUNTIME R8.2 | 있음 |
| 시계 오차 | node exporter `node_timex_offset_seconds` 절댓값 > 0.5초, `node_timex_sync_status == 0`(NTP 비동기) | Kerberos 등 관례 5분은 인증서·토큰에 느슨하다. 0.5초는 측정 근거 없이 정한 상한이며 측정하면 고친다(R1.6) | 규칙 없음: 위반으로 센다 |

로그 크기 상한은 compose 의 `logging` 옵션(`max-size`, `max-file`)으로 둔다(Docker 문서 json-file 드라이버).
## 13. 배치 도구 `placement` (Ansible 인벤토리·플레이북)

| 항목 | 내용 |
|---|---|
| 입력 | 인벤토리(`ansible/inventory*.yml`), compose, 비밀 폴더. |
| 출력 | 서버별 `compose.placement.yaml`, `plan.json`(기동 단계), 필요한 비밀 이름, 게시 포트. 다른 서버의 서비스는 `https://<서비스 이름>:<게시 포트>` + `extra_hosts`(R1.4). |
| 실패 동작 | 잘못된 배치(서비스 누락·중복·게시 포트 누락·인증서 이름 불일치)는 `validate` 가 거부한다. 서버를 나눠도 R1~R6 이 같다(R7.1). |
| 전제 | 인벤토리에는 앱만 적고 TLS 종단·인증서·pg 짝은 자동으로 따라간다(`leaders`). 소유자 `<서비스>-net` 은 앱과 같은 서버에 둔다(결정: `network_mode: service:X` 는 같은 Docker 호스트의 컨테이너끼리만 가능하다, Docker 문서). 그래서 `leaders` 규칙은 소유자를 앱 짝에 포함한다. 시험: `scripts/test-split-placement.sh`, `scripts/test-split-pki.sh`, `scripts/test-split-pki-playbook.sh`. |

## 14. 시험 컴포넌트 (E2E, 단독 시험)

| 항목 | 내용 |
|---|---|
| 입력 | 운영 입구(게이트웨이·계정·기기 토큰)와 컨테이너 안 실행(`docker exec`). 제품에 시험용 문이 없다(`scripts/test_compose_no_test_doors.py`). |
| 출력 | PASS/FAIL/SKIP/BLOCKED 와 사유. 선행 단계 실패는 FAIL 이 아니라 SKIP. |
| 실패 동작 | 간헐 실패는 재시도로 덮지 않고 원인을 찾는다. 시험끼리 공용 자원(venv·이미지 태그)을 공유하지 않는다(`scripts/test_no_pip_outside_setup.py`). |
| 전제 | P8: Docker Desktop 의 엔진은 호스트 루프백 게시 포트에 닿지 못한다(시험은 `pick_bind`). P9: 컨테이너가 다시 만들어지면 IP 가 바뀐다(이름으로만 부른다). P12: 공용 `.venv` 에 설치하는 단계가 동시에 돌면 서로 깨뜨린다. 시험: `scripts/test-publish.sh`, `scripts/test_no_pip_outside_setup.py`. |

R9.1 (시험·잡 입력 명시): 단독 시험은 E2E 가 내보낸 값을 상속하지 않는다. 사전 점검은 시험마다 `env -i` 와 필요한 이름만 넘겨 돌고(`scripts/e2e.sh`), 시험은 잠금 파일·비밀 폴더 같은 입력을 스스로 정한다(`scripts/test_selfcheck_clean_env.py`가 정적으로 지킨다). 잡은 위 11.1 표의 키만 읽는다. 실제로 `DEPLOY_LOCK` 상속이 분리 배치 플레이북 시험을 E2E 안에서만 실패시킨 것을 재현으로 확인했다.

## 15. 전제(외부 도구 동작) 모음과 확인 시험

| # | 전제 | 확인한 것 | 단독 시험 |
|---|---|---|---|
| P1 | Caddy: 맞는 사이트가 없으면 본문 없는 200 | 예(4차 E2E) | `scripts/test-tls-sidecar.sh` (모르는 Host 421) |
| P2 | Caddy: 사이트 이름 `localhost` 는 local CA 정책을 자동 생성(루트 설치 시도) | 예(`caddy adapt` 로 확인) | 없음(필요, 위반으로 센다) |
| P3 | Docker: `network_mode: service:X` 는 X 의 수명에 묶임 | 예(5q) | 없음(필요한 시험: `scripts/test-netns-lifetime.sh`) |
| P4 | step: `--token` 과 `--san` 은 함께 못 받음(SAN 은 토큰이 정함) | 예(오류 메시지) | 직접 없음(간접 `test-split-pki.sh`) |
| P5 | step: 일회용 토큰 5분 | 예 | `scripts/test-split-pki.sh` |
| P6 | Docker restart 정책(`unless-stopped`)의 재시작 조건 | 부분(공간 소유자가 멈춘 동안 불가) | 정책 존재만: `scripts/test_compose_restart_policy.py` |
| P7 | Caddy reverse_proxy: 연결 실패 502, 시간 초과 504, TLS 상류의 본문 읽기 오류는 502 | 예 | `scripts/test-gateway-auth.sh` |
| P8 | Docker Desktop: 엔진이 호스트 루프백 게시 포트에 못 닿음 | 예 | E2E `pick_bind`(단독 시험 없음) |
| P9 | Docker DNS: 재생성 시 IP 변경 | 예 | E2E 5q 복구 |
| P10 | PostgreSQL: `pg_reload_conf()` 가 서버 인증서를 다시 읽음 | 아니오(문서 근거만) | 없음(필요, 위반으로 센다) |
| P11 | Keycloak optimized image 가 읽기 전용 루트로 기동 | 예(3차 스모크) | `scripts/test-idp-smoke.sh`(현재 TLS 구성에서 실패) |
| P12 | 공용 venv 설치 동시 실행 경합 | 예 | `scripts/test_no_pip_outside_setup.py` |
| P13 | Caddy: Content-Length 로 사전 413 | 예 | `scripts/test-gateway-auth.sh` |

## 16. TLS 보조의 외부 도구 전제 (단독 실험 결과)

출처: 목록 `/tmp/tls-premises-todo.md`, 결과 원문 요지 `/tmp/tls-premises-results.md`(TLS 보조 00:46 보고), 실험 스크립트 `/tmp/tlsx/exp/`(`common.sh`, `expA`, `expA2`, `expA3`, `expB`, `expC`). 리포에 들어갈 단독 시험은 줄 T 가 `scripts/test-netns-lifetime.sh`·`scripts/test-cert-renewal.sh` 로 만든다(여기서는 만들지 않았다). 아래 값은 그 원문 요지를 옮긴 것이고 내가 다시 돌린 것은 아니다.

| # | todo | 전제 | 결과 | 근거(실험 이름·핵심 출력) | 기대는 조항 |
|---|---|---|---|---|---|
| X1 | P3 | pause 이미지(`registry.k8s.io/pause:3.10`, digest `sha256:ee6521f2…917a`)가 read_only·cap_drop ALL·no-new-privileges·비루트로 뜨고 SIGTERM 에 끝난다 | **확인** | 실험 A: `status=running user=65535:65535 ro=true capdrop=[ALL]`(no-new-privileges 포함), stop 0.37초, 종료 코드 0 | R3.1·R3.2·R3.4·R4.1·R4.2 |
| X2 | P4 | 앱·사이드카가 `network_mode: service:<서비스>-net`(pause) 일 때 앱 재시작에도 같은 공간 | **확인** | 실험 B: 정상 200 → 앱 stop 중 사이드카·pause running, 사이드카 안 `127.0.0.1:8080` 연결 거부, 클라이언트 ABORT RemoteDisconnected → 앱 start 뒤 200 | R3.2·R3.4·R4.1·R4.2 |
| X3 | D2 | 현재 구조(앱이 공간 소유): 앱 stop/start 뒤 사이드카 끊김 | **확인(재현)** | 실험 B: 앱 stop→start 뒤 사이드카 running 이지만 안의 `127.0.0.1:8080` 거부, 클라이언트 ABORT URLError, netns 다름(사이드카 4026533201, 앱 4026532729). 또 e2e-b6 5q 504 | R3.2·R4.1 위반 근거 |
| X4 | P5 | 망 별칭·게시 포트·`extra_hosts`·`sysctls` 는 `-net` 이 갖고, 앱에 `networks`/`ports` 를 두면 compose 가 거부 | **확인** | 실험 A·A2: `-net` 이 sysctls·extra_hosts·게시 포트(127.0.0.1:16323)·별칭(app)을 가지고 앱 `network_mode: service:app-net`, netns 같음(`net:[4026532727]`). 앱에 `networks` → "mutually exclusive network_mode and networks". 앱에 `ports` → `config -q` 는 통과하나 `up` 에서 "conflicting options: port publishing and the container type network mode" | R1.4·R6.1·R7.1 |
| X5 | C4 | 앱 stop → 게이트웨이(현 `config/Caddyfile` `handle_errors`) 503 + Retry-After | **확인** | 실험 B: 앱 stop 중 HTTP 503, `Retry-After: 2`, `application/json`, `{"code":"UPSTREAM_UNAVAILABLE"}`; 앱 start 뒤 200 | R3.1·R3.2·R3.4 |
| X6a | S7 | 수명 5분 인증서 + `step ca renew --daemon --expires-in 4m` 가 갱신 | **확인** | 실험 C: 파일 인증서 지문이 1분마다 변경(6cbca3… → 38ff50… → 87cee0…) | R4.4·R3.11 |
| X6b | C6 | 같은 감시 루프의 `caddy reload` 가 새 인증서를 서빙 | **반증** | 실험 C: 3분 뒤에도 서빙 인증서는 처음 것(serial=D5ACDBC9467266A7805E5EB63689E12E, notAfter=15:46:57). `caddy reload` → serial 그대로, `caddy reload --force` → serial=89E0F0130E13E164707D9930DF9BA036, notAfter=15:50:33. 원인: Caddyfile 이 그대로면 reload 를 건너뜀 | R4.4 **위반(V7)** |
| X7 | S4 | 일회용 토큰 재사용 거부 | **확인(만료 거부는 미확인)** | 실험 A: JWT `exp-iat=300초`, 재사용 시 "The request lacked necessary authorization", 첫 사용 성공. 만료 시각 이후 거부는 기다리지 않고 JWT exp 표준에 의존 | R1.2·R4.4 |
| X8 | S5 | 토큰 audience 포트가 다르면 거부(그래서 `STEP_CA_PORT` 안팎 동일이 필요) | **반증** | 실험 A3: CA 컨테이너 안 9000, 호스트 게시 16339. (a) 안쪽 주소 토큰(aud=`https://step-ca:9000/1.0/sign`)을 바깥 `https://host.docker.internal:16339` 로 사용 → 발급 성공, (b) 바깥 주소 토큰 → 성공. 한정: 접속 이름은 CA 인증서 SAN(`step ca init --dns`)에 있어야 한다. dnsNames 밖 이름의 audience 거부는 미시험. 안팎 동일은 필요 이상이지만 단순함을 위해 유지 | R7.1 |
| X9 | S8 | 만료 뒤 재시작 복구 | **결과 대기** | 01:15 실험 중 | R4.4 (줄 T 3) |

**미확인으로 남은 것**: S8, 토큰 만료 시각 이후 거부, dnsNames 밖 이름의 audience 거부, Windows 호스트의 `host.docker.internal` 해석 차이, R3.3 의 응답 헤더 지연 504(실험 B 는 연결 거부만), PostgreSQL 인증서 reload(P10).

반증된 X6b 의 대안(표준): `caddy reload --force`(공식 옵션). 구현은 줄 T 2.
