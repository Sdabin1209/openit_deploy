# 0002. gateway는 Caddy

- 상태: 채택
- 날짜: 2026-10-28

## 맥락

외부 입구는 gateway 하나다(D11). 기본 인증(직원·승인·운영·검토 계정), 기기 토큰(키오스크), 경로별 역할, 상류 장애 응답, 본문 상한, 보안 헤더, TLS를 한 곳에서 맡는다.

## 결정

Caddy v2(`locks/images.lock`의 digest 이미지)를 쓰고 설정은 `config/Caddyfile` 하나와 생성 조각 둘(`accounts.caddy`, `devices.caddy`)이다. Caddy 플러그인(rate_limit 등)이 필요한 기능은 만들지 않는다.

## 왜 (따른 표준과 근거)

- 설정 파일 하나와 작은 이미지로 필요한 기능이 모두 된다: `basic_auth`, 경로·헤더 매처, `reverse_proxy`의 연결/응답 헤더 timeout, `handle_errors`, `request_body`, `header`, `tls internal`(D88). 출처: docs/design.md 4절 표(선택 사유), Caddy v2.11.7에서 `caddy validate`와 E2E로 확인.
- 인증 블록을 `(authenticate)` 조각 하나로 분리해 병원 IdP(OIDC)가 정해지면 그 조각만 교체한다(docs/RUN.md 4-1-2).
- 실측한 기본 동작: 설정 없이는 상류 연결 거부가 502(3초 뒤), 무응답은 마감이 없다. 그래서 상한을 명시했다(docs/E2E.md).

## 검토한 대안과 버리는 이유

- **nginx**: 가장 널리 알려졌으나 TLS 발급·갱신을 따로 붙여야 하고 `handle_errors`에 해당하는 상류 장애 응답 구성이 더 번거롭다. 바꿔도 무방한 대안으로 남긴다(docs/design.md 4절).
- **Traefik**: 라벨 기반 동적 라우팅이 이 구성(서비스 몇 개, 경로가 고정)에 과하고 docker 소켓이 필요해 보안 면적이 커서 제외(docs/design.md 4절).

## 결과

- Caddy 기본 배포에는 로그인 시도 속도 제한 모듈이 없다(`caddy list-modules` 137개에서 rate/limit 모듈 없음을 확인). 커스텀 이미지 빌드는 새 위험이라 하지 않았고, 한계와 대안(네트워크 제한, 강한 무작위 암호, 실패 로그 감시)을 runbook에 둔다.
- 설정 문법이 덜 알려져 있어 `scripts/test-gateway-auth.sh`와 E2E가 경로·역할·헤더 위조를 시험한다.

## 되돌리는 조건

속도 제한·WAF가 필수가 되거나 Caddy 설정으로 표현하기 어려운 경로 로직이 생기면 nginx(+모듈)나 앞단 방화벽을 둔다.
