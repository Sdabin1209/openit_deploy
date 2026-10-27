# 0015. 컨테이너 healthcheck에 start_interval 1초를 둔다

- 상태: 채택
- 날짜: 2026-10-28

## 맥락

`up --wait`와 `depends_on: service_healthy` 사슬은 healthcheck가 healthy를 보고하는 시점에 묶인다. 점검 간격(interval)이 15초이고 start_period 동안의 기본 점검 간격(start_interval)은 5초다. gateway와 admin-console은 start_period가 없어 첫 점검이 15초 뒤다.

## 결정

`x-pyhealth`(여섯 서비스)와 postgres에 `start_interval: 1s`를 더하고, gateway와 admin-console에는 `start_period: 20s`와 `start_interval: 1s`를 더한다. 평시 점검 간격(15초)과 retries는 그대로다. `doctor.sh`가 Docker 엔진 25 이상을 확인한다(`start_interval`은 엔진 25에서 생겼다).

## 왜 (따른 표준과 근거)

- Docker의 healthcheck 옵션이 정한 기능을 쓴다(`--health-start-interval`). start_period 동안의 실패는 retries에 세지 않는 것이 이 옵션의 정의이고, 시작이 느린 서비스에 기존 start_period가 이미 쓰인다.
- **측정(격리 시험, 즉시 healthy가 되는 컨테이너 하나, Docker 엔진 29.2.0, 이 PC)**: start_period 20초·start_interval 기본일 때 healthy까지 5.5초와 6.0초, start_interval 1초일 때 1.6초와 1.6초. start_period가 없는 경우 15.7초, start_period 20초+start_interval 1초일 때 1.4초. 전체 스택에서의 기동 단축은 **측정하지 않았다**: 의존 사슬 단계 수만큼 곱해질 것으로 추정할 뿐이다.

## 검토한 대안과 버리는 이유

- interval 자체를 줄이기: 평시에도 점검이 잦아져 부하와 로그가 늘고 일시 장애에 민감해진다.
- E2E의 대기 루프만 단축: 운영의 `up --wait`가 그대로 느리다.

## 결과

- 기동 직후 20~30초 동안 healthz를 1초마다 부른다(가벼운 내부 요청). 엔진 25 미만에서는 설정이 거부될 수 있다(doctor가 먼저 막는다).

## 되돌리는 조건

엔진 25 미만을 지원해야 하면 이 항목을 빼고 기동 시간이 늘어나는 것을 받아들인다.
