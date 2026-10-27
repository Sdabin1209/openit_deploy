# 0013. 장애 주입 단계 5q·5w·5p·5m·5u는 `docker stop`/`pause`와 정책 단언 분리로 설계한다

- 상태: 채택
- 날짜: 2026-10-28

## 맥락

환자 요청 경로에 장애 정책(FAULT_POLICY)이 있다: 상류가 죽었을 때와 응답이 없을 때 gateway가 분류된 오류를 마감 시간 안에 주고, 재전송은 같은 `turn_id`로 멱등이어야 하며, DB가 멈추면 `/readyz`가 비정상이 되고 `/healthz`는 유지된다. 정책 문서 자체는 헤드 소유이고 이 ADR은 deploy의 E2E가 그것을 어떻게 시험하는지만 쓴다(정책 원문은 docs/E2E.md가 인용하는 만큼만 근거로 삼았다).

## 결정

실제 Compose 스택에서 컨테이너 수명 명령으로 장애를 만든다. 단계마다 한 가지 장애 종류를 만든다.

| 단계 | 주입 | 만드는 상황 | 보는 경계 |
|---|---|---|---|
| 5q | survey-service `docker stop` → `start` | 연결 거부 | gateway 503 `UPSTREAM_UNAVAILABLE`, `/readyz` 비정상·`/healthz` 200, 재시작 뒤 값 보존, 같은 `turn_id` 재전송 |
| 5w | survey-service `docker pause` → `unpause` | 연결은 되나 무응답 | gateway 응답 헤더 마감 근처 504, 접근 로그 `duration`이 서버 마감 6초 이상·키오스크 10초 미만 |
| 5p | postgres `docker stop` → `start` | DB 중단 | 서비스 `/readyz` 비정상·`/healthz` 200, 부분 저장 없음, 행 지문 동일, 복구 뒤 새 쓰기 |
| 5m | model-serving `docker pause` | 추론 서버 무응답 | survey 턴 마감 안의 분류된 실패, 값 미저장, 복구 뒤 새 `turn_id` 저장 |
| 5u | release-gate stop/pause, ops-feedback-ingest pause | 사람 화면 경로 상류 장애 | gateway 연결 2초 + 헤더 상한(10~15초)의 503/504 JSON |

단언은 두 종류다. **REAL 단언**은 현재 코드가 지켜야 하는 것이고 실패하면 FAIL이다. **정책 단언**(`policy()`)은 정책이 정한 기대이지만 현재 영역 코드로는 통과하지 않는 것으로, 약화하지 않고 `POLICY-PENDING`으로 표시해 기다리는 변경(변경 요청 번호)과 지금 값을 출력하며 실패로 세지 않는다. 통과하면 같은 줄이 REAL로 나온다.

## 왜 (따른 표준과 근거)

- `stop`과 `pause`는 서로 다른 실패 양상을 만든다: stop은 연결 거부(빠른 502/503), pause는 연결이 받아들여지고 응답이 오지 않는다(타임아웃). Caddy 기본 설정에서는 pause에 시간 제한이 없다는 것을 같은 이미지로 **측정**해 확인했다(60초 기다려도 응답 없음, docs/E2E.md '기본 동작의 관찰'). 그래서 gateway에 명시 타이머가 필요하고 5w가 그것을 시험한다.
- 도구 선택: Docker 명령만 쓴다. 추가 권한(NET_ADMIN)·추가 이미지 없이 단일 서버 Compose 전제(ADR 0001)에서 어디서나 돈다. **toxiproxy나 `tc`/`iptables` 같은 네트워크 결함 주입 도구와 비교한 기록은 없다**(근거 기록 없음).
- 정책 단언의 분리는 '시험을 약화해서 통과시키지 않는다'는 원칙이다: 틀린 것을 숨기지 않고 변경 요청(CR-D23, CR-D25)으로 올린다.
- 클라이언트 지연과 서버 처리 시간을 분리해 잰다: gpu-dev에서 호스트 클라이언트가 gateway보다 +0.5~1.9초 늦게 받는 것을 5w 구간별 계측으로 확인했다(원인 미확인, docs/E2E.md). 그래서 마감 단언은 gateway 접근 로그의 `duration`을 쓴다.

## 검토한 대안과 버리는 이유

- 단위·통합 시험만으로 정책을 확인: gateway 타이머, depends_on, 실제 PostgreSQL 재시작은 Compose 스택에서만 나타난다.
- `docker kill`(SIGKILL)로 죽이기: stop과 같은 연결 거부 양상이고 정상 종료 경로(SIGTERM) 시험을 잃는다. 비교 실험은 하지 않았다.

## 결과

- 한 스택에서 순차로 돌려야 하고(서로의 장애가 겹치면 안 된다) 5p가 약 41초로 단계 1~8에서 가장 길다(마지막 전체 실행 기준).
- `pause`는 컨테이너 전체를 얼려 `/readyz`도 응답하지 못하므로, 엔진이 멈춘 상태의 `/readyz` 503은 이 방식으로 볼 수 없다(docs/E2E.md 5m). 이 장애는 model-runtime에 고장 주입 수단이 생겨야 시험할 수 있다.
- 5u의 POST 경로 상한과 정적 프록시는 시험하지 않았다.

## 되돌리는 조건

정책 단언이 모두 REAL로 바뀌면 `policy()` 분리를 없앤다. 네트워크 결함(패킷 손실·지연)을 시험해야 하면 주입 도구를 추가하고 이 ADR을 대체한다.
