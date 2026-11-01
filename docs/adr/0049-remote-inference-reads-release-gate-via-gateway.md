# 0049. 원격 추론 서버는 게이트웨이의 기계 토큰 경로로 release-gate 를 읽는다

- 상태: 채택 (헤드 확인 결함, 사용자 지시 D72 "추론 서버는 어디에 두든 기능 차이가 없어야 한다", 2026-11-01). 헤드 OPEN_GAPS L27(위치 독립 시험이 HTTPS 필수 뒤 깨짐)을 닫는다.

## 맥락

추론 서버(model-runtime)는 적재 신호를 받으면 release-gate 의 `GET /v1/releases/{id}`, `GET /v1/releases/{id}/bundle` 을 직접 읽고, 활성 포인터는 `GET /v1/active-pointer` 로 읽는다(계약 클라이언트). 같은 서버의 컨테이너로 있으면 내부 네트워크로 닿는다. **다른 호스트에 두면 닿을 운영 경로가 없었다**: 운영 compose 는 release-gate 를 호스트에 게시하지 않고(D11: 외부 입구는 gateway 하나), gateway 는 사람용 경로 외의 `/v1/*` 를 404 로 막는다(`handle /v1/*`).
기존 `scripts/test-inference-location.sh` 는 시험용 overlay 로 release-gate 를 호스트에 직접 게시하고 평문 HTTP 로 불러 통과시켰다. 운영에는 없는 둘째 문을 시험이 만들어 준 우회였고, gateway 가 HTTPS 필수가 된 뒤에는 깨졌다. 즉 "위치 독립"은 시험에서만 참이었다.

## 결정

- gateway 에 **추론 서버 기계 토큰 경로**를 둔다(`config/Caddyfile` `@inferencemachine`). 메서드 GET, 경로 `/v1/active-pointer`, `/v1/releases/*`(번들 포함), 요청의 `Authorization: Bearer <값>` 이 비밀 파일 `gateway-inference-token` 의 값과 같을 때만 `release-gate` 로 프록시한다. 상류에는 model-serving 이 원래 쓰던 읽기 토큰(`gate-read-model-serving`)을 붙이고, 사용자·기기 헤더는 지우고, 응답에 `Cache-Control: no-store` 를 둔다.
- 토큰이 없거나 틀린 `GET /v1/releases/*` 는 401(`WWW-Authenticate: Bearer`). 사람 계정(Basic)의 `/v1/releases/*` 는 계속 404 다. `/v1/active-pointer` 는 사람(operator) 경로와 겹치므로 Bearer 가 맞을 때만 기계 경로가 가져가고, 그 밖은 기존 운영자 블록이 처리한다(자격 없으면 Basic 도전 401).
- 원격 서버는 `RELEASE_URL` 로 **게이트웨이의 HTTPS 주소**를 쓰고, `INFERENCE_RELEASE_TOKEN_FILE` 에 이 게이트웨이 추론 토큰을 둔다. 게이트웨이 CA 루트(공개 인증서)는 `compose.inference.yaml` 의 `configs` 로 넣고 `SSL_CERT_FILE` 로 가리킨다. 꺼내는 도구는 `scripts/export-gateway-ca.sh`.
- 토큰 생성·권한은 다른 토큰과 같다(`gen-secrets.sh` 의 `tok`, 폴더 700 안 파일 644: 컨테이너 uid 10001 이 읽는다, ADR 0022).
- 위치 독립 시험은 샌드박스 방식으로 다시 썼다: 제품은 `compose.yaml` + `compose.external-inference.yaml`(운영 모드, `compose.test.yaml` 미사용), "다른 호스트"는 `compose.inference.yaml` 을 별도 프로젝트로. 운영 compose 에 시험용 문을 내지 않는다.

## 왜

- 외부 입구가 gateway 하나라는 구조(D11)와 HTTPS 필수(D88/U5, ADR 0005)를 그대로 쓴다. 새 문이나 새 프로토콜 없이 기존 gateway 의 TLS·접근 로그·헤더 정리를 재사용한다.
- 표준: 서비스 간(기계) 호출은 Bearer 토큰(RFC 6750), 사설 CA 는 클라이언트가 명시적으로 신뢰(검증을 끄지 않는다). 기기 토큰 블록(`kiosk_devices`/`@device_ok`)과 같은 방식(Caddy `{file.…}` 치환, 읽을 때 한 번)이라 운영자가 새로 익힐 것이 없다.
- 상류 토큰을 gateway 가 바꿔 붙이므로 원격 호스트에는 release-gate 의 토큰이 가지 않는다. 원격 호스트가 뚫려도 얻는 것은 읽기 세 경로뿐인 토큰이고, 교체는 gateway 한 곳에서 한다(토큰 파일 삭제 후 `gen-secrets.sh`, gateway 재시작).
- `SSL_CERT_FILE`: 계약 클라이언트에 CA 인자가 없고 Python 기본 SSL 컨텍스트가 이 변수를 읽는다(python:3.12-slim 에서 확인). model-runtime 코드를 바꾸지 않는다. 이미지의 `probe()`(`RELEASE_URL/healthz`, urllib 기본 컨텍스트)도 같은 CA 로 통과함을 시험이 보인다.
- 상한: `response_header_timeout` 은 **응답 머리글까지만** 잰다(본문 읽기에는 걸리지 않는다). 번들 본문(tar) 크기와 무관하므로 번들 경로만의 별도 상한 예외를 두지 않고 `proxy_limits 13s`(ADR 0048)를 그대로 쓴다. 번들 전체 전송 시간의 상한은 두지 않았다. **번들 크기와 전송 시간은 측정하지 않았다.** 서버 쪽 읽기 제한은 model-runtime 의 `MODEL_RUNTIME_RELEASE_READ_TIMEOUT_S`(기본 120)다.

## 검토한 대안과 버리는 이유

- **release-gate 를 호스트에 직접 게시**(예전 시험의 방식): 평문 HTTP 이고(게이트웨이의 TLS 를 지난다는 보장이 없음) 운영 입구가 둘이 된다(D11 위반). 접근 제어는 방화벽과 release-gate 토큰뿐이 되고 gateway 의 접근 로그·헤더 정리를 거치지 않는다. 버린다.
- **원격 서버에 release-gate 읽기 토큰을 그대로 주고 gateway 가 통과시키기**: 원격 호스트에 서비스 토큰이 퍼지고, 그 토큰은 gateway 밖(내부 네트워크)에서도 유효하다. 기계 토큰을 gateway 에서 바꿔 붙이는 쪽이 노출이 작다. 버린다.
- **사람 계정(Basic)으로 읽기**: 기계에 사람 계정을 주면 역할·감사 기록이 흐려지고 `/v1/releases/*` 를 사람에게 열어야 한다. 버린다.
- **VPN/SSH 터널로 release-gate 에 직접 닿기**: 호스트에 문이 필요하다는 점이 같고 운영 절차가 늘어난다. 터널이 필요한 환경은 `INFERENCE_NETWORK_MODE=host` 로 게이트웨이 주소에 닿을 수 있어 이 결정 안에서 해결된다.
- **mTLS 로 서버 인증**: 키오스크 기기에 쓰는 방식(ADR 0040)이 있으나 서버 호스트마다 인증서 발급·갱신이 더 든다. 첫 단계는 토큰으로 두고 필요하면 새 ADR 로 대체한다.

## 결과

- 얻는 것: 추론 서버를 다른 호스트·GPU 서버에 둘 때의 운영 경로가 생겼고, 같은 경로를 시험이 쓴다(우회 없음). 확인한 것은 `scripts/test-inference-location.sh`: 기계 토큰 경로가 release-gate 까지 닿음, 사람 계정의 `/v1/releases/*` 404, 토큰 없음·틀림 401, 서버 자신의 클라이언트가 HTTPS+CA+토큰으로 release-gate 의 NOT_FOUND 를 받음.
- 감수하는 것: (1) 이 경로의 실제 번들 적재(활성 릴리스를 받아 LOADED)는 시험에서 확인하지 않았다. 시험이 릴리스를 만들지 않는다(릴리스 생성은 운영 compose 에 시험용 문 없이 할 수 없다). (2) 토큰 비교는 문자열 `==` 이다(Caddy `header` 매처; 상수 시간 비교 아님). 기기 토큰 비교와 같은 한계이며 TLS 위에서 쓰고 토큰은 무작위 48자라 타이밍 공격을 현실적 위협으로 보지 않았으나 측정하지 않았다. (3) 토큰 교체는 gateway 재시작이 필요하다(Caddy 는 설정을 읽을 때 한 번 치환). (4) `Exposure` 계약에 기계 토큰 종류가 없어 이 경로는 노출 라벨 대조(`check-exposure.sh`) 밖이다(`docs/change-requests/CR-D440-exposure-machine-token.md`). (5) 게이트웨이 인증서의 사이트 이름(`GATEWAY_HOSTS`)에 원격 서버가 부르는 이름이 들어 있어야 한다.

## 되돌리는 조건

- release-gate 가 직접 게시할 만한 이유(전용 사설 링크 + TLS 종단)가 생기고 헤드가 입구를 둘로 허용하면 새 ADR 이 대체한다.
- `Exposure` 에 기계 토큰 종류가 생기면 노출 대조에서 제외한 부분(`exposure_check.py`)을 되돌린다.
- 번들 전송이 `proxy_limits` 나 서버 읽기 제한에 걸리는 것이 측정으로 확인되면 번들 경로만의 상한을 새 값으로 정한다.
