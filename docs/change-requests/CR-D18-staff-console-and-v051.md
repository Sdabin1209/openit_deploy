# CR-D18: model-runtime v0.5.1 반영 결과와 새 관찰

- 상태: 정리 (CR-D17 해소)

| 항목 | 결과 |
| --- | --- |
| 번들 캐시 권한 | 해소: 기본 경로 `/var/lib/model-runtime/bundles`가 앱 사용자 소유라 새 named volume에서 PUT 적재가 된다. `model-serving-init`을 없앴다 |
| fake용 serving_config | `/v1/info`의 `serving_config_expectation`(constraint, prompt/protection 버전, output_contract)으로 만든다. survey 이미지의 `fake_serving_configs()`와의 차이는 E2E 3단계 출력에 남는다 |
| 위험 정지 시험 | 해소: `MODEL_RUNTIME_FAKE_RISK_PHRASE`(시험 구성에만)로 위험 정지 -> 정지 중 발화 무응답 -> staff RESUME(멱등) -> 발화 재개, END 후 턴 409를 REAL로 확인 |
| 라벨 | model-serving `io.openit.model-runtime=0.5.1`, survey/gate 이미지는 `v0.5.1` wheel |

## 새 관찰 (survey-service)

위험 정지 턴의 응답에 `staff_alert: DELIVERY_FAILED`가 나온다. 이 구성에는 직원 콘솔 전달 어댑터(`SURVEY_STAFF_CONSOLE` 팩토리)가 없어 직원 알림이 나가지 않는다. 프론트는 이 신호로 직원 호출 화면을 보여야 한다(PUBLIC_API.md). 운영에서 직원 콘솔(알림 수신처)을 무엇으로 할지는 survey-service와 사용자 결정이다. E2E는 `DELIVERED`와 `DELIVERY_FAILED` 둘 다 위험 정지의 신호로 받아들인다.
