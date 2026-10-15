# CR-D20: 게이트웨이의 사람 계정 역할 분리와 실패 사례 검토 경로 (D71)

- 상태: 정리 (admin-console CR-003에 대한 deploy 응답)

## 반영한 것
- 사람 계정에 역할을 두었다. 계정과 암호 해시, 계정 -> 역할 매핑은 비밀 파일 `secrets/gateway-human-auth.caddy`(`(human_auth)`, `(role_matchers)`)에 있고 compose.yaml·Caddyfile에는 값이 없다. E2E 시험 계정: `trainer-e2e`(release-approver), `reviewer-e2e`(reviewer). 운영 인증 방식(SSO 등)과 실제 계정은 미정이다.
- 경로별 허용: release-approver 계정은 승인 경로 4개(`GET /v1/submissions*`, `POST /v1/approvals`), reviewer 계정은 검토 경로만(`GET /v1/cases`, `/v1/cases/{id}`, `/v1/deidentified-traces/{ref}` -> ops-feedback **읽기 토큰**(역할 reviewer을 `OPS_READ_TOKENS`에 추가), `POST /v1/cases/{id}/review` -> reviewer **쓰기 토큰**). 인증 없으면 401, 인증은 됐지만 다른 역할의 경로이면 **403**. 모두 `X-Openit-User`를 인증된 계정으로 덮어쓰고 `Cache-Control: no-store`를 둔다. `/admin/` 정적 화면은 어느 역할이든 열린다(API가 역할로 막힌다).
- 열지 않은 것: `POST /v1/traces`(서비스 내부 면, 게이트웨이에서 404)와 승인·검토 이외의 `/v1/*`.
- E2E 7g가 위 동작을 확인한다(인증 없음 401, 승인자 계정의 검토 경로 403, 검토자 계정의 승인 경로 403, 검토자 계정으로 PENDING 목록 -> 사례 -> 비식별 trace -> reviewed_input 포함 CONFIRMED 201·재전송 200).

## 남은 것 (BLOCKED)
- (해소) 응답 FailureCase와 I7 조회의 `ext["ops-feedback"].reviewed_by`가 인증 계정(reviewer-e2e)으로 찍히고 위조 `X-Openit-User`는 기록되지 않음을 ops-feedback bf210fe로 확인했다(E2E 7h REAL). 승인 쪽 approver_id도 같다(4g).
- 검토 화면 렌더링은 E2E에서 볼 수 없다(BLOCKED).
- 한 사람이 두 역할을 겸하는 계정 정책은 정하지 않았다(지금은 계정당 역할 하나).
