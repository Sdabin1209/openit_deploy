# CR-D15: 셋째 구간 상태와 남은 막힘

- 상태: 정리 (CR-D10, D11은 해소, D12는 일부 남음)

| CR | 상태 |
| --- | --- |
| D10 승인 평가 실행기 | 부분 해소: 정책 스키마 검증, 실행기 규약 문서(runner_protocol.md), 운영 모드 거부(`GATE_ALLOW_TEST`), `/readyz`의 eval 상태가 생겼다. 실행기 **구현**은 여전히 없어(O11) E2E는 시험용 실행기(`test/gate-runner`)를 TEST-SUB로 꽂는다 |
| D11 검토 게시 | 해소: `POST /v1/cases/{id}/review`(검토 토큰)로 7단계의 검토를 실제 HTTP로 교체했다. 저작으로의 환류도 `GET /v1/signals`로 확인했다 |
| D12 model-lab·GPU | 일부: 파일 저장소 팩토리와 회귀 평가(I7)가 문서화됐다. 그러나 CPU로 도는 model-lab 이미지가 없어(이미지는 model-registry뿐, 잡은 requirements.lock 환경) 회귀 평가를 Compose·E2E에서 돌리지 못했다. E2E_GPU=1 경로는 신호 전이라 돌리지 않았다. GPU 서버에서 model-registry·qa·ops 읽기 면에 닿는 경로는 사용자 결정 |
| D13 | 해소(재현 안 됨) |

## 새 관찰

- 개선 신호가 ops-feedback의 읽기 면을 부르므로 `ops-feedback-ingest`를 `authoring` 네트워크에 더했다. 결과적으로 question-authoring과 ops-feedback이 서로 도달 가능하다(토큰으로 보호). survey-service→question-authoring은 계속 차단. 다른 배치를 원하면 헤드가 알려 달라.
- 정책 JSON 형식은 이제 `release_gate/schemas/gate_policy.schema.json`이 정본이다. E2E가 시험 정책을 그 스키마로 검증한다.
