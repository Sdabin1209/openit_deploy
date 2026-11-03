# 0056. CSRF 허용 출처를 GATEWAY_HOSTS 에서 만든다

- 상태: 채택 (OPEN_GAPS L20, 2026-11-03)
- 날짜: 2026-11-03

## 맥락

게이트웨이의 CSRF 방어(점검 M2)는 상태를 바꾸는 메서드에서 Origin 이 `https://` + 요청의 `Host`(host:port)와 다르면 403 이다. 비교 기준이 요청이 보낸 Host 헤더 자신이라, 허용 출처를 설정이 정하지 않는다. 앞선 L20 작업은 `GATEWAY_HOSTS` 의 형식(와일드카드·포트만 항목 금지)을 기동 전에 검사해 Caddy 가 그 사이트 이름 밖의 Host 를 핸들러로 보내지 않게 했다.

## 결정

허용 출처의 호스트 이름을 `GATEWAY_HOSTS` 에서 만든다. `scripts/lib.sh` 의 `gateway_host_names` 가 포트를 떼어 따옴표 목록을 만들어 `GATEWAY_HOST_NAMES` 로 내보내고(`dc` 가 부를 때마다 다시 계산), compose 가 게이트웨이에 넘기며, Caddyfile 의 `@csrf` 가 `{http.request.host} in [{$GATEWAY_HOST_NAMES}]` 와 `Origin == "https://" + {http.request.hostport}` 를 함께 요구한다. 이름 규칙 위반(와일드카드·따옴표 등)은 `gateway_host_names` 가 멈추고, `GatewayEnv` 스키마가 기동 전에 형식을 검사한다.

## 왜

- 허용 이름이 인증서 이름과 같은 한 곳(`GATEWAY_HOSTS`)에서 나온다. 운영자가 두 군데를 맞출 일이 없다.
- 포트를 목록에 고정하지 않는다: 밖에 게시된 포트는 컨테이너 포트(8443)와 다를 수 있고(데모·E2E 는 Docker 배정 포트) 브라우저가 보내는 Host 의 포트가 실제 출처의 포트이기 때문이다. 같은 호스트의 다른 포트(다른 출처)는 Origin 과 Host 가 달라 막힌다. 포트까지 목록으로 고정하면 정상 브라우저의 POST 가 403 이 될 수 있다(확인한 것: 시험의 임의 게시 포트).
- 표준: Fetch 표준의 Origin 헤더와 OWASP CSRF Prevention Cheat Sheet 의 "Origin 헤더를 신뢰할 수 있는 출처 목록과 비교".

## 검토한 대안과 버리는 이유

- Origin 을 `host:port` 목록(GATEWAY_HOSTS 그대로)과 비교: 위 포트 문제.
- 현행 유지(Host 헤더와 비교만): 허용이 설정으로 드러나지 않고 Host 위조 방어를 사이트 매칭에만 기댄다.

## 결과

- 얻는 것: 허용 이름이 설정에서 생성되고 목록 밖 Host 는 Origin 과 무관하게 막힌다. 회귀 시험: 다른 Origin 403, 같은 호스트 다른 포트 403, `//`·`%2f`·`%2e%2e`·대소문자·청크 본문 경로 우회 403, 목록 밖 Host 는 핸들러에 닿지 않음, `gateway_host_names` 의 규칙 위반 거부(`scripts/test-gateway-auth.sh`).
- 감수하는 것: 호스트 이름만 제한하므로 같은 호스트의 다른 포트에 다른 서비스가 있으면 그 서비스의 출처는 Host 와 Origin 이 같을 때 통과한다(그 서비스가 이 게이트웨이의 Host 로 요청해야 하므로 브라우저는 보내지 못한다).

## 되돌리는 조건

게이트웨이를 단일 고정 포트로만 노출하게 되면 포트까지 목록에 넣는 더 엄격한 비교로 바꾼다.
