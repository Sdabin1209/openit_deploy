# 0057. 사람 인증: Keycloak(OIDC) + oauth2-proxy + Caddy forward_auth

- 상태: 채택 (U82, head ADR 0014, 2026-11-03)
- Supersedes: ADR 0039(조직이 준 정적 직원 계정 파일). ADR 0002(Caddy 게이트웨이)의 "인증 블록은 basic_auth"는 이 ADR로 바뀐다
- 날짜: 2026-11-03

## 맥락

사람 계정은 조직이 주는 `staff-accounts.conf`를 Caddy basic_auth 조각으로 바꾸는 방식뿐이었다. 가입 신청, 승인(역할 부여), admin 역할, 초기 admin, 로그인 기록, 한 사람이 역할 여럿을 갖는 것이 없었다. 헤드 ADR 0014가 표준 IdP(Keycloak)와 OIDC로 바꾸기로 정했고, 이 ADR은 그 구현(deploy 쪽)의 선택과 근거다. 계약 3.4.0 CONVENTIONS 6절이 게이트웨이의 신원 전달(`X-Openit-User`, `X-Openit-Roles`)과 승인 대기 403을 정한다.

## 결정

- 컨테이너 둘: `keycloak`(26.4, 기동 `start --import-realm`, `KC_HTTP_RELATIVE_PATH=/auth`)과 `oauth2-proxy`(v7.12.0, 일반 `oidc` 공급자). 둘 다 내부망 `auth`(internal)에 있고 호스트 포트가 없다. Keycloak의 DB는 같은 PostgreSQL의 별도 데이터베이스·계정 `keycloak`(`db-keycloak` 망). 이미지는 digest로 고정(`lock-third-party.sh`).
- 게이트웨이는 사람 경로마다 `forward_auth oauth2-proxy:4180`(`uri /oauth2/auth`)로 묻고, 통과하면 oauth2-proxy의 `X-Auth-Request-Preferred-Username`/`X-Auth-Request-Groups`를 받아 `X-Openit-User`/`X-Openit-Roles`로 붙인다. 정적 계정 파일·basic_auth·`apply-accounts.sh`는 삭제.
- 열린 길은 `/oauth2/*`(oauth2-proxy)와 `/auth/*`(Keycloak). `/oauth2/auth`와 Keycloak master realm은 닫는다. 관리는 realm `openit`의 `admin` 그룹 계정(사용자·그룹 관리, 로그인 기록 보기 역할만).
- realm `openit`는 가져오기 파일로 만든다(`config/keycloak/openit-realm.template.json` + `scripts/gen-keycloak-realm.sh`가 `GATEWAY_HOSTS`로 허용 리다이렉트 URI를 채움): 그룹 8개(계약의 고정 역할 이름), 자가 등록, 로그인 이벤트 365일, 클라이언트 `openit-gateway`(기밀, 직접 암호 흐름 없음, PKCE S256, 그룹 매퍼 full path 없음), 초기 admin `openit-admin`(임시 비밀번호, `admin` 그룹).
- 비밀은 파일(D84): Keycloak은 래퍼(`config/keycloak/entrypoint.sh`)가 파일을 읽어 프로세스 환경에만 넘기고(컨테이너 환경 변수·`docker inspect`에 값이 없다), oauth2-proxy는 `*_FILE` 플래그를 쓴다. 클라이언트 비밀과 쿠키 키 파일은 줄바꿈 없이 만든다(oauth2-proxy는 파일 내용을 다듬지 않는다).
- 밖에서 보이는 주소 `GATEWAY_PUBLIC_URL`(첫 `GATEWAY_HOSTS` 이름 + 밖에 보이는 포트)이 발급자·콜백의 기준이다. 서버끼리는 내부 주소(`http://keycloak:8080`)를 쓰고 oauth2-proxy는 `skip-oidc-discovery`로 주소를 직접 받는다.
- E2E·데모의 시험 사용자는 운영 입구(kcadm)로 만든다(`scripts/idp-test-users.sh`). 운영 realm 파일에는 시험 사용자가 없다.

## 왜 (따른 표준과 근거)

- OpenID Connect Core 1.0 + OAuth 2.0 인가 코드 흐름 + PKCE(RFC 7636). 리버스 프록시의 `forward_auth`+oauth2-proxy는 기존 앱을 OIDC 뒤에 두는 표준 배치다. 서비스와 계약은 안 바뀐다(헤더 규약만).
- 일반 `oidc` 공급자인 이유: `keycloak-oidc` 공급자는 realm 역할을 `role:<이름>` 그룹으로 그룹 목록에 섞어(`default-roles-openit` 등) 그룹이 빈 신규 가입자가 승인 대기로 잡히지 않고 `X-Openit-Roles`에 잡음이 들어갔다. 진짜 스택 스모크 시험(`scripts/test-idp-smoke.sh`)이 잡았다.
- `X-Auth-Request-User`가 아니라 `Preferred-Username`을 쓰는 이유: 전자는 내부 식별자(sub)다. 사용자 ID로는 사람이 읽는 이름이 감사 기록에 맞다.
- 쿠키 12시간·갱신 5분은 측정·결정 전 시작값이다(역할 변경 반영 지연을 5분으로 묶고, 하루 근무 안에서 다시 로그인하지 않게).

## 검토한 대안과 버리는 이유

- ADR 0014가 이미 검토한 것(Authentik, basic_auth + 직접 가입 화면, Caddy OIDC 플러그인, admin-console 승인 화면)은 거기서 버렸다.
- Keycloak에 읽기 전용 루트: 시작 때 Quarkus가 `lib/quarkus`에 다시 빌드한 결과를 쓴다. 최적화 이미지를 만들면 가능하나 그 빌드·유지는 영역 밖 산출물이라 지금은 쓰기 가능한 루트로 두고 나머지 강화(비root, cap_drop ALL, no-new-privileges, 자원 한도)는 적용했다.
- 포트까지 고정한 단일 발급자 대신 다중 호스트: 로그인 쿠키·발급자가 이름 하나에 묶이는 것이 OIDC의 일반 구조라 첫 호스트 이름 하나만 사람 화면에 쓴다.

## 결과

- 얻는 것: 가입 신청·승인·admin·초기 admin·로그인 기록·한 계정 여러 역할. 게이트웨이 시험은 가짜 oauth2-proxy로 빠르게, 로그인·가입·승인·로그아웃·이벤트는 진짜 스택 스모크로 확인한다.
- 감수하는 것: 컨테이너 둘과 Keycloak 기동 시간(수십 초, 첫 기동은 더 걸림, 측정 전). 사람 화면은 한 이름으로만 쓴다. 이미 있는 realm은 다시 가져오지 않으므로 호스트가 바뀌면 관리 화면에서 URI를 고친다. 이메일 발송이 없어 비밀번호 재설정 흐름은 끈다(관리자가 재설정).
- 확인하지 못한 것: admin-console(`/oauth2/userinfo` 소비)과 서비스(`X-Openit-Roles` 소비)의 실제 연결, 전체 E2E(사람 경로 전부가 OIDC로 통과하는지)는 돌리지 않았다. 스모크는 이웃 서비스 없이 게이트웨이까지만 본다.

## 되돌리는 조건

병원이 자체 IdP(AD/LDAP, SAML)를 요구하면 Keycloak의 사용자 연동(federation)이나 IdP 위임으로 바꾸고 게이트웨이 구성은 그대로 둔다.
