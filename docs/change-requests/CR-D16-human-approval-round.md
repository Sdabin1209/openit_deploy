# CR-D16: 사람 승인 전환(D53) 반영 상태와 남은 막힘

- 상태: 정리

| 항목 | 상태 |
| --- | --- |
| CR-D10 승인 평가 실행기 | 해소: 자동 PASS와 워커·정책 임계치가 게이트에서 사라졌다. E2E의 시험용 정책·실행기·시험 워커·`GATE_ALLOW_TEST`를 삭제했다. 승인은 `POST /v1/approvals`(역할 release-approver, 별도 시험용 토큰) |
| 공개 API(O06) | survey-service가 구현(D55). 게이트웨이가 `/v1/sessions`만 넘기고 `/intervention`은 외부에 닫는다. 직원 개입 경로는 survey-service에 직접(내부)만 있다. 위험 신호로 멈춘 세션의 RESUME/END는 가짜 백엔드로 유도하지 못해 E2E가 시험하지 못했다(메모리: 멈춘 세션 유도 방법을 survey-service가 알려 주면 추가) |
| 모델 추론 | survey-service는 여전히 `fake` 백엔드(CR-D08) |
| model-lab 회귀 평가가 `reviewed_input`을 쓰는지 | 못 돌렸다: 회귀 평가는 model-lab 파이프라인(잡)에 있고 CPU로 도는 이미지가 없다. E2E는 `reviewed_input`이 ops-feedback에서 검증(잘못된 입력 400)되고 I7 읽기에서 그대로 보이는 데까지 확인했다. CR-D12 |
| 경계 계약 태그 | 이미지는 v1.3.1 wheel로 빌드(`BOUNDARY_TAG_ALL`). question-authoring의 빌드 스크립트 기본 태그는 아직 v1.2.0, survey/ops/gate는 v1.3.0이라 deploy가 환경 변수로 v1.3.1을 넘긴다. 영역 기본값을 v1.3.1로 올리면 deploy의 지정은 필요 없다 |

## 새 관찰

- 승인 요청 보고서는 활성 릴리스와 같은 지표를 맞댄다. 활성화가 일어나면 아직 대기 중인 제출의 보고서가 바뀌므로 낡은 `report_hash`는 409다(E2E가 잘못된 해시로 확인).
- 이 구성에서 승인자는 사람이다. E2E는 스크립트가 시험용 토큰으로 대신하며 `TEST-SUB`로 표시한다. 운영에서 승인자 토큰을 누구에게 어떻게 주는지(콘솔 UI 없음)는 사용자 결정이다.
