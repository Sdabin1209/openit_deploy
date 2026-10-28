# deploy 표준성·근거 전수 점검 (2026-10-29, 기준서: head/docs/audit/standards-audit-spec.md)

범위: 읽기 전용 점검. 코드·설정·시험은 고치지 않았고 실행하지 않았다(스크립트는 읽기만 했다). 비밀 값(secrets/, .env, 환경 변수)은 읽지 않았다.
읽은 것: CLAUDE.md, README.md, docs/adr/ 중 0001·0002·0003·0005·0010·0011·0015·0020·0022·0023·0025·0031(앞부분), config/Caddyfile, compose.yaml(전체 구조와 한도·healthcheck 줄), compose.registry.yaml, config/jobs.yaml, config/systemd/*, config/gateway-accounts.conf, config/kiosk-devices.conf.example, scripts/{gen-secrets,gateway-lib,kiosk-add-device,rotate-account,scheduler.py,backup,backup-lib,backup_tool.py,backup-secrets(머리말),publish-image,registry,lock-third-party(머리말),check_health.py}, docs/runbook.md·docs/RUN.md·docs/design.md의 관련 줄(grep).

## 결과표

분류: S 표준+근거 / S- 표준이나 근거 기록 없음 / N 비표준이나 근거 있음 / N- 비표준+근거 없음 / O 재발명 / ? 확인 못 함

| # | 요소 | 분류 | 표준 이름 | 근거 위치 | 증거 위치 |
|---|---|---|---|---|---|
| R01 | 단일 서버 Docker Compose 오케스트레이션 | S | Compose Specification | ADR 0001(Kubernetes·Swarm·systemd 대안 비교, "측정한 근거는 없다" 명시) | compose.yaml:4 |
| R02 | gateway = Caddy v2 | S | (역방향 프록시 일반 관행. 특정 표준 없음) | ADR 0002(nginx·Traefik 비교) | config/Caddyfile, compose.yaml:211-241 |
| R03 | HTTPS 필수, `tls internal`(Caddy 내부 CA), HSTS 1년, 평문 포트는 /healthz만 두고 308 | S | RFC 6797(HSTS), RFC 7538(308) | ADR 0005 | Caddyfile:3-8, 51, 70 |
| R04 | 서비스 사이·DB 연결 평문(내부 TLS 없음) | N | 없음(Docker 내부 네트워크 신뢰는 관행일 뿐 이름 있는 표준을 확인 못 함) | ADR 0005 "측정·위협 모델링한 근거 없음: 판단", ADR 0031(앞부분만 읽음) | ADR 0005 왜 절 |
| R05 | 직원·승인자 계정: Basic 인증 + bcrypt 해시(`caddy hash-password`), 평문은 해시 생성 때만 | S | RFC 7617(Basic), bcrypt | ADR 0022 "Caddy 표준 방식" | gateway-lib.sh:158-166, 173-175 |
| R06 | 계정 발급·암호 회전을 우리 스크립트가 관리(gw_write_accounts, rotate-account.sh가 새 암호를 표준 출력으로 전달) | O | 표준 인프라는 IdP(OIDC, OpenID Connect Core 1.0) | OIDC 교체 지점만 문서화(RUN.md 4-1-2, gateway-lib.sh:1-8). 왜 지금 IdP 없이 자체 관리인가는 "병원 IdP 미정"(gateway-accounts.conf:8, README D-A)뿐이고 **인증 방식 ADR 없음** | gateway-lib.sh:153-177, rotate-account.sh:1-15, gateway-accounts.conf |
| R07 | 키오스크 기기 토큰: 우리가 무작위 토큰을 발급·보관·회전·폐기(add/rotate/remove/from-list), 기기별 json 산출물 전달, 목록 두 곳(Caddy, survey)에 복제 | O | 기기 자격 표준 후보: mTLS 클라이언트 인증서(RFC 8705 / RFC 5280 PKI; Caddy 내부 CA가 이미 있다), OAuth 2.0 client credentials(RFC 6749 4.4) | **근거 기록 없음**: D85 F절·D88/U8는 "기기별 토큰"으로 정했을 뿐 "왜 자체 발급이고 왜 인증서가 아닌가" 비교 ADR 없음. 런북 9-3에 절차만 있음 | kiosk-add-device.sh:1-38, gateway-lib.sh:178-192, Caddyfile:280-290 |
| R08 | 기기 토큰 대조 = Caddy `expression ... in ["Bearer <토큰>", ...]`, 목록 파일 gateway-devices.caddy가 평문 토큰 포함·모드 644 | ? | 비밀 비교의 상수 시간 요구(일반 관행)를 이 방식이 만족하는지 Caddy 소스를 읽지 못해 확인 못 함 | ADR 0022 "결과"가 644 평문을 감수 항목으로 적음. 비교 방식 자체의 근거 없음 | gateway-lib.sh:179-186, Caddyfile:17-18 |
| R09 | 토큰·암호 생성: `secrets.token_hex(24)` = 48자리 16진수(192비트) | S- | Python `secrets`(CSPRNG), OWASP 세션 관리 지침의 엔트로피 권고(정확한 수치는 이 세션에서 원문 확인 못 함) | RUN.md·runbook 9절에 "무차별 대입이 비현실적"이라는 한 줄. 24바이트를 고른 이유는 기록 없음 | gen-secrets.sh:20, gateway-lib.sh:133 |
| R10 | 토큰 만료 없음, 회전은 수동·주기 미정 | N- | (회전 주기에 대한 표준 확인 못 함) | runbook:221 "근거 없음, 사용자 결정 대기", ADR 0022 결과 절 "근거 기록이 없다" | runbook.md:221, ADR 0022 |
| R11 | 비밀은 compose file secrets → /run/secrets, 서비스는 `NAME_FILE`로 읽음, env_file 금지 | S | Docker/Compose secrets 관행, 12-factor 3절의 변형(파일 주입) | D84, compose.yaml 주석, check-secrets-hidden.sh | compose.yaml:49-56 부근(secrets 주석), gen-secrets.sh:3-6 |
| R12 | 비밀 폴더 700, 호스트 전용 파일 600 | S | 최소 권한 | ADR 0022 | gen-secrets.sh:19-22 |
| R13 | 컨테이너가 읽는 비밀 파일 644(폴더 700 안) | N | 최소 권한에서 벗어남 | ADR 0022(Engine 29.2.0/Compose 5.0.2에서 uid/mode 미적용을 측정, 640+group_add는 시험했으나 적용 안 함) | gen-secrets.sh:10-12, gateway-lib.sh:176, 186, 191 |
| R14 | 역할 매처: 계정 → 역할 표를 Caddy `expression`으로 생성, 경로별 `handle @role_*` | S- | RBAC(NIST RBAC 개념). Caddy 표현식은 도구 고유 방식 | 파일 머리말·Caddyfile 주석(D85 E절). 인가 구조 ADR 없음 | gateway-lib.sh:168-171, Caddyfile:13-16 |
| R15 | gateway가 인증을 마친 요청에 역할별 서비스 토큰(읽기/쓰기 분리)과 `X-Openit-User`를 주입 | S- | API 게이트웨이의 자격 변환 관행(이름 있는 표준 확인 못 함) | Caddyfile 주석(D69, 점검 L1). ADR 없음 | Caddyfile:127-205 |
| R16 | CSRF 방어: 변경 메서드에서 Sec-Fetch-Site·Origin 검사(헤더가 없으면 통과) | S- | OWASP CSRF Prevention Cheat Sheet(Fetch Metadata, Origin 검증) | Caddyfile 주석(점검 M2) | Caddyfile:72-78 |
| R17 | 보안 헤더(nosniff, X-Frame-Options DENY, no-referrer, -Server) | S- | OWASP Secure Headers 관행 | Caddyfile 주석(B7) | Caddyfile:62-71 |
| R18 | 시간 체인: 연결 1s + 응답 헤더 8.5s = 9.5s < 키오스크 10s, 재시도 없음 | N | 데드라인 전파 원칙(FAULT_POLICY) | ADR 0003. 값은 가짜 모델 기준, 실모델 측정 안 함 명시 | Caddyfile:285-298 |
| R19 | 사람 화면 경로 값: 연결 2s, 헤더 15s/10s, SSE read 1h, 본문 8MiB(사이트)/1MiB(쓰기 3곳) | N | 없음 | Caddyfile 주석에 이유와 "시작값, 실측 근거 없음" 명시. ADR 없음 | Caddyfile:20-24, 59-62, 121, 157 |
| R20 | 자체 스케줄러 scheduler.py(간격 판정, flock, 상태 JSON, 타임아웃, null 주기 거부, where 필터) | O | 표준: systemd timer(`OnUnitActiveSec`, `Persistent=`, oneshot 서비스, journald·`systemctl show`에 Result·종료 코드·마지막 실행), cron + `flock -n` | ADR 0010이 **"cron/systemd timer가 잡 명령을 직접 부르는 대안만을 따로 비교한 기록은 없다"고 스스로 적음.** 근거로 든 "timer 단독으로는 상태가 남지 않는다"는 코드에서 읽은 차이라고만 쓰였고, systemd는 마지막 실행·결과를 자체 기록하므로 이 주장은 확인되지 않았다(이 세션이 실행해 본 것은 아님). 컨테이너 안 cron과 docker 소켓 스케줄러(ofelia)와의 비교는 있음 | scheduler.py:1-88, ADR 0010:19, 26, config/systemd/openit-scheduler.* (tick을 systemd timer가 1분마다 부름) |
| R21 | 잡 주기 600s(수집기)/3600s(ops-feedback)/86400s(백업·purge) | N | 없음 | "사용자 결정(D85, 표준 주기)", ADR 0010, 측정 안 함 | jobs.yaml:2-3, 18-30 |
| R22 | 잡 타임아웃 기본 3600s, 복원 시험 주 1회(604800s), release-gate-prune 86400s | N- | 없음 | 3600s: 근거 없음(scheduler.py:17 인자 설명뿐). 604800s: jobs.yaml이 "측정·표준 근거 없음". prune: "근거 ADR 없음: 판단, 측정 안 함" | scheduler.py:17, jobs.yaml:27-31, 35-38 |
| R23 | systemd 예시 주기: scheduler tick 1분, check-health 5분 | N- | 없음 | "주기는 시작값이며 사용자 결정이 아니다"(주석)뿐 | config/systemd/openit-*.timer |
| R24 | DB 백업 = `pg_dump -Fc`, DB별, 병렬 시작, 시각을 MANIFEST에 기록 | S | PostgreSQL 문서의 논리 백업(pg_dump) | ADR 0020(PITR·볼륨 복사 대안 비교) | ADR 0020 결정 1, 왜 절(pg-backup.sh 본문은 읽지 못함) |
| R25 | 백업 암호화: 수신자 공개키(age 우선, gpg 대체), 서버에는 공개키만, 개인키가 들어 있으면 거부 | S | age, OpenPGP(RFC 4880/9580) 공개키 암호화 | ADR 0020(대칭·서버 개인키·LUKS 대안 비교). **age 분기는 한 번도 실행하지 못했다**고 ADR이 적음 | backup-lib.sh:19-27, 34-47 |
| R26 | 파일 볼륨 백업·복구를 자체 도구로 구현(backup_tool.py: 복사, SQLite backup API, SHA-256 MANIFEST, 복원, 지문; backup-lib.sh의 find 기반 보관 삭제) | O | 표준 도구: restic / borg(스냅샷·무결성·암호화·보관 정책), 또는 tar + `sha256sum` + `sqlite3 .backup` | ADR 0020은 DB 백업 대안만 비교했고 파일 볼륨에 restic/borg를 검토한 기록은 읽은 범위(grep)에서 없다. SQLite 처리는 DB가 PostgreSQL로 옮겨 간 뒤에도 남아 있다(ADR 0021이 SQLite를 개발용으로 규정) | backup_tool.py:1-139, 187-197, backup-lib.sh:50-58 |
| R27 | 백업 보관 14일, 가장 최근 1개는 남김 | N | 없음 | "D88 U4"(사용자 결정), ADR 0020. 값 측정 안 함 | config/backup.env.example:9, backup-lib.sh:14 |
| R28 | secrets 백업 최신 14개 보관(BACKUP_SECRETS_KEEP) | N- | 없음 | 스크립트 머리말이 "근거 기록 없음" | backup-secrets.sh:7 |
| R29 | 로컬 레지스트리 `registry:2`, 인증·TLS 없이 127.0.0.1 바인드, 삭제 허용 | N | OCI Distribution Spec(서버는 참조 구현이나 인증·TLS 없는 운용은 비표준) | ADR 0011(GHCR·Kubernetes 대안 비교), ADR 0025가 한계 명시. push 인증은 미정 | compose.registry.yaml:1-8, 56-58, 60 |
| R30 | 이미지는 digest(`@sha256`)로만 참조·잠금, push 출력 digest와 레지스트리 HEAD digest 일치 확인 | S | OCI 내용 주소 지정(digest), 재현 가능한 배포 관행 | ADR 0011 | publish-image.sh:71-75, compose.yaml:1 |
| R31 | publish 상한 3s/5s/15s/900s | N | 없음 | ADR 0011 후속 + 스크립트 주석: 필요는 E2E 5g에서 관찰, 값은 "판단, 측정 안 함" | publish-image.sh:58-63 |
| R32 | 잠금 파일 형식(정렬된 KEY=value, flock + 임시 파일 교체, 게시마다 history 복사)과 compose `--env-file` 사용 | N | 없음 | ADR 0011이 잠금 방식은 설명하나 형식 대안(예: compose 파일 안 digest, 서명 매니페스트) 비교 없음 | publish-image.sh:77-90 |
| R33 | 외부 이미지(caddy:2-alpine, registry:2, python:3.12-slim, postgres:16)를 부동 태그로 받아 digest를 고정 | S- | digest 고정 관행 | lock-third-party.sh 머리말만. 부동 태그를 고른 이유, 갱신 절차 기록 없음 | lock-third-party.sh:1-20 |
| R34 | 이미지 라벨 `io.openit.{service,revision,contracts.*,turn-engine,model-runtime}`, 필수 4개 검사 | N | OCI image-spec 사전 정의 키는 `org.opencontainers.image.*`(revision, source 등). 라벨 키를 역 도메인 이름공간으로 두는 것은 Docker 라벨 관행 | D50 / CR-D06(원문 읽지 못함). 영역 이미지가 OCI 표준 `org.opencontainers.image.revision`도 함께 다는지 확인 못 함 | publish-image.sh:51-56 |
| R35 | 자원 한도 방식: 서비스마다 `mem_limit`/`cpus`/`pids_limit`(변수화) | S | Docker 자원 제한, OWASP Docker Security Cheat Sheet, CIS Docker Benchmark(ADR이 원문을 다시 열지 않았다고 명시) | ADR 0023(`deploy.resources` 대안 비교) | compose.yaml:6, 163-165, 212-214 외 |
| R36 | 자원 한도 값(postgres 2g/2.0/300, gateway 256m, 서비스 512m, gate 1g, model-serving 1g·16g 등) | N- | 없음 | ADR 0023: "표의 숫자는 측정에서 나온 것이 아니다. 근거 기록이 없다." 측정 안 함. purge·prune 잡 값(256m/0.5/100~128)은 ADR 표에도 없음 | compose.yaml:163-165, 212-214, 438-440, 456-458, 475-477; config/resource-limits.env.example |
| R37 | healthcheck 방식: 이미지에 curl이 없어 python urllib / wget / pg_isready, `/healthz`(생존)와 `/readyz`(준비) 분리 | S- | Docker HEALTHCHECK, Kubernetes probe 구분 관행(liveness/readiness) | 주석("이미지에 curl 없음")뿐, ADR 없음 | compose.yaml:18, 202-203, 241, 280-282 |
| R38 | `start_interval: 1s`, `start_period: 20s` | S | Docker HEALTHCHECK 옵션(엔진 25+) | ADR 0015(격리 시험 측정값: 5.5~6.0초 → 1.6초). 전체 스택 효과는 측정 안 함 명시 | compose.yaml:19-23, 241 |
| R39 | healthcheck `interval 15s / timeout 3s / retries 5`(postgres 10s/3s/6, start_period 30s) | N- | 없음 | 값의 이유 기록 없음(ADR 0015는 interval을 그대로 두는 이유만 "부하·민감도"로 설명) | compose.yaml:19-22, 202-208 |
| R40 | 레지스트리 컨테이너 격리: 비root 65532, read_only, cap_drop ALL(+일회성 CHOWN 서비스), no-new-privileges, tmpfs, 네트워크 없는 chown 서비스 | S | OWASP Docker Security Cheat Sheet, CIS Docker Benchmark(ADR이 원문 재대조 안 했다고 명시) | ADR 0025(동작 확인: id, 쓰기 불가, 업로드 201). uid 65532는 "특별한 근거 없음"이라고 명시 | compose.registry.yaml:15-45 |
| R41 | 서비스 컨테이너 격리 앵커 x-hardening: no-new-privileges, cap_drop ALL, read_only, tmpfs /tmp, 비root(10001), docker.sock 미마운트(check-containers.sh가 검사), gateway만 NET_BIND_SERVICE 추가 | S- | 위와 같음 | x-hardening 전용 ADR 없음. ADR 0025가 "다른 서비스가 이미 같은 방식"이라고만 언급. `cap_add` 이유는 인라인 주석 | compose.yaml:8-14, 216-217, check-containers.sh:4, 21-25 |
| R42 | 로그 json-file, max-size 10m × max-file 5 | N- | Docker 로깅 드라이버 옵션(값의 표준은 없음) | "상시 서비스와 같은 값"뿐, 값 근거 없음 | compose.yaml:14, 16 |
| R43 | 네트워크 분리(edge/serving/ui·release·logs·db-*·datasets internal) | S- | 네트워크 분할(최소 접근) 관행 | docs/design.md·ADR 0031이 참조. 네트워크 모양 자체의 ADR 없음 | compose.yaml:25-45 |
| R44 | 호스트 포트 기본 127.0.0.1 바인드(gateway는 GATEWAY_BIND로 개방) | S- | 최소 노출 | 주석(compose.registry.yaml:2, compose.yaml:237-239). ADR 없음 | compose.yaml:237-239 |
| R45 | PostgreSQL 단일 컨테이너 설정(`max_connections=100`, `idle_in_transaction_session_timeout=300000`, 로깅 옵션, 계정별 연결 상한 20) | ? | PostgreSQL 설정 파라미터. 값의 근거 여부는 ADR 0024·0021 본문을 읽지 못해 확인 못 함 | ADR 0021·0024 존재(읽지 않음) | compose.yaml:195-200, resource-limits.env.example |
| R46 | 상태 점검 도구 check_health.py(스케줄러 상태, 디스크, 외부 URL, /readyz, 백업 나이·암호화 설정을 읽어 OK/WARN/CRIT/SKIP) | O | 표준 모니터링: Prometheus(node_exporter, blackbox_exporter) + Alertmanager, 또는 Nagios 호환 점검 플러그인 | 도구 선택 ADR 없음. 시스템 고유 부분(scheduler.json, 백업 나이)은 외부 도구가 못 읽으나 디스크·HTTP 탐침·임계 경보는 일반 기능. 외부 감시·알림 수단은 "자리만 있음/미정" | check_health.py:1-156, config/external-monitor.example.yaml |
| R47 | 점검 종료 코드 0 OK / 1 WARN / 2 CRIT | S- | Nagios plugin 종료 코드 관행(코드는 이를 인용하지 않는다. SKIP은 별도 집계) | 인용 없음 | check_health.py:2-3, 156 |
| R48 | 점검 임계값: 디스크 80/90%, 지연 2배, 정체 3600s, 판정 루프 900s, 연속 실패 1/3, 백업 172800s, 탐침 5s | N- | 없음 | "헤드가 정한 표준 관행의 시작값, 사용자 결정 아님"이라고만 하고 어느 표준인지 안 적음 | check_health.py:5, 16-25, 83 |
| R49 | stop_grace_period 30s(postgres), 40s(release-gate, dataset-store) | N | 없음 | 인라인 주석: 서비스 영역의 최악 종료 35s + 여유 5s, 측정 안 함 명시 | compose.yaml:201, 352, 406 |

## 분류별 개수

| S | S- | N | N- | O | ? | 합계 |
|---|---|---|---|---|---|---|
| 12 | 11 | 11 | 8 | 5 | 2 | 49 |

## N-, O, ? 목록

- R06 O: 직원 계정 발급·회전을 자체 스크립트로 관리(표준: IdP/OIDC). 인증 방식 ADR 없음.
- R07 O: 키오스크 기기 자격(토큰)을 직접 발급·회전·폐기. 표준 후보인 mTLS 기기 인증서(내부 CA 이미 있음)나 OAuth client credentials와의 비교 기록이 없다.
- R20 O: scheduler.py. cron/systemd timer 직접 사용 대안 비교 기록이 없다고 ADR 0010이 인정.
- R26 O: 파일 볼륨 백업 도구 backup_tool.py·보관 삭제. restic/borg 비교 기록 없음.
- R46 O: check_health.py. 표준 모니터링 스택과의 비교 기록 없음.
- R10 N-: 토큰 만료·회전 주기 없음, 근거 없음.
- R22 N-: scheduler 타임아웃 3600s, 복원 시험 주기 604800s, prune 주기 86400s.
- R23 N-: systemd 예시 주기 1분/5분.
- R28 N-: secrets 백업 보관 개수 14.
- R36 N-: 컨테이너 자원 한도 값 전부(ADR 0023이 근거 없음을 인정).
- R39 N-: healthcheck interval/timeout/retries 값.
- R42 N-: 로그 회전 10m × 5.
- R48 N-: check_health 임계값 전부.
- R08 ?: 기기 토큰 대조의 상수 시간 비교 여부(Caddy 표현식 `in [...]`).
- R45 ?: PostgreSQL 설정값(ADR 0021·0024 미열람).

## 점검 중 눈에 띈 것 (분류 밖 관찰, 확인한 줄 기준)

1. gen-secrets.sh:76-78은 시험 기기 e2e, e2e-a/b/c의 토큰을 운영 비밀 폴더에도 만들고, gateway-accounts.conf의 `*-e2e` 시험 계정(역할 포함)도 기본 목록이다. 코드 주석은 "운영에서는 remove한다"고만 하며 자동으로 막지 않는다. 지워지지 않으면 시험 자격이 운영 gateway에서 유효하다.
2. rotate-account.sh:4와 ADR 0022 결과 절은 "암호가 docker run 인자로 보인다"고 쓰지만 같은 파일 :207과 gateway-lib.sh:161은 표준 입력으로 준다(점검 L6). 문서와 코드가 어긋난 것으로 보인다(실행 확인은 안 함).
3. 이미지 서명·검증(cosign 등)은 없다. digest 잠금만 있다(R30). 평가 대상이 아니었으나 공급망 항목이라 적는다.
4. kiosk-add-device.sh remove와 sync는 gateway-devices.caddy와 survey-kiosk-device-tokens를 같이 갱신하지만 반영에는 gateway·survey-service 재시작이 필요하다(코드 주석). 폐기가 즉시가 아니라 재시작 때 효력을 갖는다.

## 점검하지 못한 것

- 실행·시험: 어떤 스크립트도 실행하지 않았다(doctor, check-*, backup, 시험 포함). 이 문서의 "동작한다"는 모두 ADR·주석이 적은 내용이고 이 세션이 확인한 것이 아니다.
- 읽지 못한 파일: ADR 0004·0012~0014·0021·0024·0030·0032~0034의 본문, scripts/pg-backup.sh·restore.sh·pg-restore.sh·pg-roles.sh·up.sh·build-images.sh(라벨 부분 제외)·doctor.sh·run-job.sh·e2e*.sh·check-*.sh 대부분, config/*.env, config/postgres/initdb, compose.llm*/inference/test 변형, docs/design.md·RUN.md·runbook.md 전문(grep 발췌만), docs/ci.md.
- 표준 원문 대조: RFC·OWASP·CIS·Nagios 등은 이름만 인용했고 이 세션에서 원문을 다시 열지 않았다. OWASP 엔트로피 권고의 정확한 수치는 쓰지 않았다.
- Caddy의 기기 토큰 비교 구현(상수 시간 여부), `tls internal` 인증서 수명·갱신 동작, 루트 인증서 배포 절차의 실제 여부.
- systemd timer가 마지막 실행·종료 코드를 기록한다는 점은 일반 지식이며 이 환경에서 확인하지 않았다(R20의 평가 근거).
- BACKUP_DIR이 실제로 서버 밖인지, 백업 개인키 보관, age 분기 실행, 전체 복원(실제 키) 시험.
- 영역 이미지의 라벨 실제 내용(OCI 표준 라벨 병행 여부), D50·CR-D06·D85·D88 원문(head 쪽).
