# 변경 요청 처리 결과: `HealthStatus` 스키마 (deploy → 헤드)

해소됨. 헤드가 RUNTIME.md R5.1·DC-GW.1 을 고쳤다: 서비스의 준비 확인 스키마가 계약에 있으면(`SurveyReadyz`·`GateReadyz`·`OpsFeedbackReadyz`) 본문이 그 스키마를 통과해야 하고, 없으면 비어 있지 않은 JSON 객체여야 한다.
게이트웨이 자신의 `/readyz` 는 비어 있지 않은 JSON 객체다. 없는 `HealthStatus` 를 요구하지 않는다. 공통 스키마는 헤드 OPEN_GAPS U101 로 분리됐다.

deploy 의 대응: `config/Caddyfile` 의 게이트웨이 응답 `{"status":"ok"}`·`{"status":"not-ready"}`, `scripts/e2e.sh readyz_check`(스키마 또는 비어 있지 않은 객체), `scripts/test_gateway_health_body.py`, `scripts/test_health_checks_read_body.py`.
