# 0048. gateway 상류 프록시 상한이 클라이언트 대기·서버 마감과 사슬 규칙을 지킨다

- 상태: 채택 (헤드 지시 U424, 2026-10-31). ADR 0047 의 사슬(키오스크 12s > gateway 10.5s > 턴 9s)을 직원 API와 관리 화면 경로로 넓힌다.

## 맥락

`@staffapi`(직원 API, survey-service)가 연결 2s + 응답 헤더 10s = 12s 로, 직원 화면의 대기(kiosk-frontend REQUEST_TIMEOUT_MS 12s)와 같았다. 같으면 클라이언트가 먼저 끊어 gateway 의 분류된 실패(503/504 UPSTREAM_UNAVAILABLE)를 못 받는다. 관리 화면(admin-console, 대기 15s)이 부르는 release-gate·저작 경로도 연결 2s + 헤더 15s = 17s 로 대기보다 길었다. 계약 CONVENTIONS 시간표(D119)의 규칙은 "바깥이 안쪽보다 길다"이다.

## 결정

- `@staffapi`: 연결 1s + 응답 헤더 9.5s = 10.5s(키오스크 경로와 같은 값; 서버 턴 마감 9s 보다 길고 직원 화면 12s 보다 짧다). SSE 읽기 `read_timeout 1h` 는 그대로다(헤더가 오기 전까지만의 상한).
- `proxy_limits` 스니펫: 연결 2s -> 1s(같은 서버의 컨테이너라 거의 즉시). release-gate·question-authoring 헤더 15s -> 13s(합 14s < admin-console 15s), ops-feedback·admin-console 헤더 10s 그대로(합 11s).
- 정적 시험 `scripts/test_time_chain.py` 의 `ProxyChain` 이 Caddyfile 의 모든 `reverse_proxy` 블록을 읽어 위 규칙을 본다. 클라이언트 대기의 기록은 E2E 상수 `STAFF_SCREEN_WAIT_S` 12, `ADMIN_CONSOLE_WAIT_S` 15 다(deploy 에는 그 화면들의 설정 파일이 없고 값은 각 영역이 정한다: 영역이 바꾸면 이 상수를 고친다).

## 왜

- 표준: 호출 사슬에서 바깥 타임아웃이 안쪽보다 길어야 안쪽의 분류된 오류가 전달된다(헤드 D119, ADR 0003·0047 과 같은 규칙).
- 13s: 값은 측정이 아니라 사슬에서 나왔다(**측정하지 않았다**). release-gate 의 승인·활성화·롤백은 DB 쓰기와 번들 검증이 있어 읽기보다 길게 잡은 시작값(15s)을 14s 합 안으로 줄였다. 이 상한이 서버 실제 처리 시간보다 짧은지는 확인하지 못했다.

## 검토한 대안

- 클라이언트 대기를 늘린다: 각 영역의 값이라 deploy 가 정하지 못한다.
- 직원 경로만 고치고 나머지는 둔다: 관리 화면 경로(17s > 15s)가 같은 결함이라 버린다.

## 결과

얻는 것: 모든 사람용 경로에서 gateway 의 분류된 실패가 클라이언트에 닿는다. 감수하는 것: release-gate 처리가 13s 를 넘으면 gateway 가 먼저 504 를 낸다(롤백·활성화처럼 오래 걸릴 수 있는 쓰기, 측정 안 함). E2E 5u 의 기대 시간 상수(`GW_HDR_GATE_S` 13, `GW_DIAL_PROXY_S` 1)를 맞췄다. E2E 는 돌리지 않았다.

## 되돌리는 조건

관리 화면이 대기를 늘리거나 release-gate 쓰기 시간이 측정으로 13s 를 넘으면 이 값을 새 ADR 이 대체한다.
