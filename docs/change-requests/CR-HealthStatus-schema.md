# 변경 요청: `HealthStatus` 스키마가 계약 패키지에 정의돼 있지 않다 (deploy → 헤드)

RUNTIME.md R2.3·R5.1 은 `/healthz`·`/readyz` 본문이 `HealthStatus` 를 따르고 확인하는 쪽이 **본문의 `status`** 를 본다고 정한다. 그러나 boundary-contracts v3.4.3 패키지(`load_schema('HealthStatus')`)와 문서(CONVENTIONS, HTTP.md)에는 `HealthStatus` 정의가 없다(검색: RUNTIME.md 의 두 줄뿐).

지금 서비스마다 본문이 다르다: 앱 `/healthz` 는 `{"status": "ok"}`, survey-service `/readyz` 는 `{"ready": true, "problems": [...]}`(status 필드 없음). deploy 는 게이트웨이 자신의 응답을 `{"status":"ok"}` / `{"status":"not-ready"}` 로 정했다(config/Caddyfile, 시험 scripts/test_gateway_health_body.py).

요청: `HealthStatus` 스키마(필수 `status` 열거, `ready`·`problems` 등 선택 필드)를 계약에 정의하고, `/readyz` 가 있는 서비스(survey-service 등)가 `status` 를 내게 한다. 그때까지 deploy 의 읽는 쪽은 `/healthz` 만 `status` 를 판정하고 `/readyz` 는 서비스별 형식(`ready`)을 임시로 받는다.
