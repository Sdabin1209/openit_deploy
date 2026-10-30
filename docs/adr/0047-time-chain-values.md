# 0047. 시간 상한 사슬 값: 키오스크 12s > gateway 10.5s > survey 턴 9s > 추출 3s + 응답 5s

- 상태: 채택 (사용자 결정, 2026-10-30)
- Supersedes: 0003 의 값(불변식은 유지)
- 날짜: 2026-10-30

## 맥락

ADR 0003 의 사슬(키오스크 10s > gateway 9.5s > 턴 6s, 응답 생성 2s)은 초기값이었고 측정하지 않았다. 사용자가 응답 생성에 5초가 필요하다고 정했다(응답 생성 2.0s -> 5.0s). 안쪽이 늘면 바깥도 함께 늘어야 바깥이 안쪽의 분류된 실패를 받는다.

## 결정

값 추출 3.0s(`SURVEY_INFERENCE_EXTRACT_TIMEOUT_SECONDS`, 변경 없음), 응답 생성 5.0s(`SURVEY_INFERENCE_RESPOND_TIMEOUT_SECONDS`), survey 턴 총 마감 9.0s(`SURVEY_TURN_DEADLINE_SECONDS`, 6.0->9.0), gateway 연결 1s + 응답 헤더 9.5s = 10.5s(`config/Caddyfile` `@kioskapi`; 8.5s->9.5s), 키오스크 대기 12s(kiosk-frontend 영역이 정한다, 10->12). 세 survey 값은 `config/survey.env` 에 명시한다(영역 기본값에 기대지 않는다). 계약 `SurveyServiceEnv` 가 세 키를 허용한다.

## 왜

- 출처는 사용자 결정이다. 측정한 값이 아니다(**측정하지 않았다**). 사슬의 형태는 ADR 0003 과 같다: 바깥이 안쪽보다 길어야 안쪽이 분류된 실패를 만든다.
- 턴 9s > 추출 3s + 응답 5s = 8s: 한 턴이 두 호출을 순서대로 부르므로 마감이 호출 상한의 합보다 1s 길다.
- gateway 10.5s > 턴 9s, 키오스크 12s > gateway 10.5s: 각각 1.5s 의 여유(Go 의 연결·응답 헤더 타이머가 순차라 합이 상한, ADR 0003).

## 검토한 대안

- 영역 기본값에만 두고 deploy 는 적지 않는다: 사슬의 두 바깥 값(gateway, 키오스크)과 나란히 볼 수 없고 어긋나도 모른다. 버린다.
- E2E 상수를 복사해 두는 것으로 대신한다: 복사본이 정본이 된다. 정적 시험이 설정에서 읽는다.

## 결과

얻는 것: 사슬이 설정과 시험(`scripts/test_time_chain.py`, self-checks.list)으로 고정된다. E2E 의 시간 상수(`KIOSK_WAIT_S` 12, `SURVEY_TURN_DEADLINE_S` 9)와 단언 문구를 새 사슬에 맞췄다. 감수하는 것: 키오스크 대기 12s 는 deploy 에 설정 파일이 없어 E2E 상수가 deploy 쪽의 유일한 기록이다(kiosk-frontend 가 값을 바꾸면 이 상수와 시험이 알려 주지 못한다). 장애 시험(5w, 5m, 5p)이 느려진다(최대 마감 9~10.5s 대기, 측정하지 않았다). E2E 는 돌리지 않았다.

## 되돌리는 조건

응답 생성 상한을 측정으로 다시 정하면 새 ADR 이 이 값을 대체한다.
