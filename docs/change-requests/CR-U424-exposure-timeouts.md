# 변경 요청 (deploy -> 헤드, 각 영역에 전달): 노출 선언(deploy-exposure.json)의 timeouts_ms 를 새 gateway 상한으로

- 배경: deploy 가 gateway 상류 상한을 시간 사슬 규칙(바깥 > 안쪽, 계약 CONVENTIONS 시간표 D119)에 맞췄다(ADR 0048). 영역 이미지의 라벨 `io.openit.exposure`(각 영역의 `deploy-exposure.json`)에 선언한 `timeouts_ms` 가 옛 값이라 `check-exposure` 가 43건 시간 제한 어긋남을 낸다. 지금은 `config/exposure-known-diffs.json` 에 이유와 함께 올려 E2E 를 막지 않는다. 영역이 선언을 올리면 그 예외가 '낡은 예외'로 보고되므로 deploy 가 지운다.
- 새 값(Caddyfile 이 정본, 영역은 선언을 맞춘다):
  - survey-service 직원 경로(`/v1/staff/*`, `/v1/sessions/*/intervention`): `{"dial": 1000, "response_header": 9500, "read": 3600000}` (지금 2000/10000/3600000).
  - release-gate 모든 사람용 경로, question-authoring 저작 경로: `{"dial": 1000, "response_header": 13000}` (지금 2000/15000).
  - admin-console `/admin/*`: `{"dial": 1000, "response_header": 10000}`. ops-feedback 검토 경로: `{"dial": 1000, "response_header": 10000}` (지금 dial 2000).
- 근거: ADR 0048(deploy docs/adr). 측정한 값이 아니다.
