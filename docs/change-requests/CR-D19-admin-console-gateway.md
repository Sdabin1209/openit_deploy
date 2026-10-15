# CR-D19: admin-console(출고 승인 화면) 게이트웨이 반영과 확인된 어긋남

- 상태: 정리 (admin-console CR-002에 대한 deploy 응답)

## 반영한 것
- 이미지 `admin-console`(로컬 `../admin-console` 폴더, 태그 없음)을 `git archive`로 빌드해 compose에 추가했다(포트 8080, `/healthz`·`/readyz`, 라벨 6개, `ADMIN_DEV_APPROVER_ID`는 설정하지 않음). 경계 계약 기본 태그는 v1.3.3.
- 게이트웨이: `/admin/`(접두사를 떼고 전달, `/admin`은 `/admin/`으로 리다이렉트)와 release-gate의 네 경로만 사람 인증(기본 인증, 시험 계정 `trainer-e2e`, 운영 방식 미정) 뒤에서 프록시한다: `GET /v1/submissions`, `GET /v1/submissions/{id}`(+`/review-report`), `POST /v1/approvals`. 열지 않는 것(`POST /v1/submissions`, `/v1/activate`, `/v1/rollback`, `/v1/releases*`)은 404. 인증된 사용자 ID를 `X-Openit-User`로 덮어쓰고(클라이언트가 보낸 값은 무시), `X-Openit-Report-Hash`는 통과, `Cache-Control: no-store`를 응답에 둔다. 게이트웨이는 release-gate에 닿도록 `serving` 네트워크에도 붙었다.

## 확인한 어긋남 (E2E 4g가 발견)
1. **읽기 경로에 쓰기 토큰은 쓸 수 없다.** admin-console CR-002는 "release-approver 쓰기 토큰을 붙인다"고 했지만, release-gate는 `GET /v1/submissions*`에서 쓰기 토큰을 403(`읽기 토큰이 없거나 맞지 않는다`)으로 거부한다(런북: 쓰기 토큰은 읽기 면에서 403). 그래서 게이트웨이는 GET에는 `release-approver` **읽기** 토큰(`GATE_READ_TOKENS`에 역할 추가), POST에는 **쓰기** 토큰을 붙인다. 계약(HTTP.md)이 승인 화면의 GET에 어느 토큰을 쓰는지 한 줄로 밝히면 좋다.
2. `POST /v1/approvals` 응답이 `GateApproval` 그대로가 아니라 `{"approval": GateApproval, ...}`로 한 겹 싸여 있다. HTTP.md는 "새 `GateApproval`(201)"이라고만 한다. 클라이언트(admin-console, `boundary_contracts.clients`)와 서버 중 어느 쪽이 맞는지 정해야 한다.
3. 화면의 `/config.json`은 절대 경로라 `/admin/` 아래에서는 kiosk-frontend로 가서 404가 된다. 화면은 없는 것으로 처리하므로 지금은 영향이 없다(`ADMIN_DEV_APPROVER_ID`를 쓰지 않는 한). 상대 경로(`config.json`)로 바꾸면 해결된다(admin-console).
4. 운영 인증(SSO, 사내망 제한 등)과 HTTPS는 미정이다.
