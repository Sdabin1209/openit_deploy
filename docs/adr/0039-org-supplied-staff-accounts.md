# 0039. 직원 계정은 조직이 주는 bcrypt 계정 파일을 쓴다 (프로젝트는 발급하지 않는다)

- 상태: 채택
- 날짜: 2026-10-29

## 맥락

`gen-secrets.sh`가 직원 계정마다 무작위 암호와 bcrypt 해시를 만들고(`gw_write_accounts`), `rotate-account.sh`가 새 암호를 만들어 표준 출력으로 한 번 보여 주며 전달하게 했다. 이는 계정 발급·암호 전달·회전을 우리 스크립트가 맡는 구조였다(표준 점검 R06: 표준 인프라는 IdP, OIDC). D111은 이를 "조직이 주는 bcrypt 계정 파일을 받는 방식"으로 바꾸라고 했다. OIDC 도입은 병원 IdP가 정해진 뒤의 일이다(런북 9-1, 미정).

## 결정

- 운영 직원 계정의 원본은 조직이 주는 `secrets/staff-accounts.conf`다. 형식은 한 줄에 `<계정 ID> <역할[,역할]> <bcrypt 해시>`이다(`config/staff-accounts.conf.example`). 해시 만드는 법은 예시 파일에 안내한다(`caddy hash-password`).
- `gw_parse_accounts`가 형식, 계정 ID 규칙, 역할 집합, 중복, bcrypt 형식(`$2a$|$2b$|$2y$` + 비용 2자리 + 53자)을 검사한다. 평문 암호나 다른 해시는 거부한다. 파일을 그룹/다른 사용자가 쓸 수 있으면 거부한다.
- `scripts/apply-accounts.sh [--apply]`가 검사한 뒤 `secrets/gateway-accounts.caddy`를 다시 쓴다(해시는 조직이 준 값 그대로, 출력하지 않는다). 검사 실패면 기존 조각을 바꾸지 않는다. 계정 추가·삭제·암호 변경은 조직이 파일을 고쳐 주는 것으로 한다.
- 지운 것: `scripts/rotate-account.sh`, `config/gateway-accounts.conf`, 운영 계정에 대한 무작위 암호·해시 생성과 `tokens/account-<id>-password|hash` 파일.
- 남긴 것: 시험 계정(`config/gateway-accounts.test.conf`의 `*-e2e`)은 `gen-secrets.sh --test-fixtures`가 계속 암호·해시를 만든다. E2E·데모가 로그인에 평문을 써야 하기 때문이고, 운영 폴더에 시험 자격이 없는지는 기존 `check-test-fixtures.sh`가 막는다.

## 왜

- 표준: Basic 인증(RFC 7617)은 HTTPS 위에서만 쓰고(ADR 0005), 암호 저장은 bcrypt 같은 적응형 해시다(OWASP Password Storage Cheat Sheet). 계정의 수명주기(발급, 폐기, 암호 정책)는 조직의 계정 관리가 맡는 것이 정상이고 응용 프로젝트가 직접 발급하는 것이 이례다.
- 이 프로젝트가 평문 암호를 만들고 보여 주고 디스크에 두는 구간이 운영에서 사라진다.
- 검토한 대안: (a) 지금 OIDC(IdP) — 병원 IdP가 정해지지 않았다. (b) 계정 발급 스크립트 유지 — D89/R06에 어긋난다. (c) htpasswd 파일을 Caddy `basic_auth`에 직접 마운트 — Caddy 설정 형식(`<계정> <해시>`)과 우리 역할 매핑이 있어야 하므로 한 줄에 역할을 더한 자체 형식이 필요하다.

## 값의 출처

bcrypt 비용 14는 우리가 정하지 않는다(조직이 해시를 만든다). 시험용 해시 비용 14는 `caddy hash-password` 기본값이다(측정 안 함). 파일 모드 검사(그룹/다른 사용자 쓰기 금지)는 최소 권한 관행이고 600을 권장한다.

## 결과

- 얻는 것: 운영 경로의 자체 발급·회전 코드와 평문 암호 노출 구간이 사라진다(`rotate-account.sh` 약 25줄, 해시 생성 분기). 시험 `test-staff-accounts.sh` 17건.
- 감수하는 것: 계정이 없으면(조직이 파일을 주기 전까지) 사람 인증 경로는 모두 401이다(기본 동작은 이전과 같다). 새 암호를 "한 번만 보여 주고 전달"하는 편의가 없다(조직 몫). 해시가 든 파일을 `secrets/`에 둬야 한다(커밋하지 않는다).
- 역할 매핑과 서비스 쪽 역할표(`QA_USER_ROLES`)는 여전히 두 곳이다(런북 8절). 이 결정이 바꾸지 않았다.

## 되돌리는 조건

병원 IdP(OIDC)가 정해지면 `(authenticate)` 블록과 역할 매핑을 IdP 클레임으로 바꾸는 새 ADR로 이 계정 파일을 대체한다.
