# CR-D02: release-gate 배포 항목: 읽기 토큰 분리, 수집기 실행 형태, 버전 변수

- 상태: 제안
- 보내는 곳: deploy -> head (영향: release-gate)

## 확인한 것(release-gate boundary/runbook)

1. `GATE_READ_TOKEN`이 하나다. CONVENTIONS 9절과 브리프는 "영역마다 서로 다른 읽기 전용 토큰"을 요구한다. 지금은 survey-service, ops-feedback, question-authoring이 같은 읽기 토큰을 나눠 써야 하므로 한 영역 토큰 유출이 다른 영역을 구별하지 못한다.
2. 후보 수집기는 gate-service 안에서 `GATE_POLL_SECONDS`마다 돈다. D39는 "run-once 같은 명령과 설정 파일을 가진, 같은 입력에 같은 결과를 내는 잡"을 요구하고 스케줄러가 주기를 정한다. 지금은 스케줄러가 수집 주기를 정할 수 없다.
3. `GATE_TURN_ENGINE_VERSION`, `GATE_MODEL_RUNTIME_VERSION`이 이미지 빌드 인자로 기본 `unset`이다. 릴리스 매니페스트에 기록되고 학습 때 버전과 일치 검사에 쓰인다고 되어 있다. 현재 이미지는 `unset`으로 뜬다(deploy는 값을 만들지 않았다).
4. 이미지 라벨은 있으나 키가 `org.openit.*`로 다른 영역과 다르다(CR-D06).

## 요청

- (1) `GATE_READ_TOKENS=survey-service=토큰,ops-feedback=토큰,...`처럼 읽는 쪽 역할을 토큰에 묶는다(쓰기 토큰과 같은 방식). 호환을 위해 `GATE_READ_TOKEN`은 한 릴리스 동안 유지해도 된다.
- (2) `gate-collector --once`(run-once)를 별도 명령으로 내고 같은 입력에 같은 결과·멱등이 되게 한다. deploy는 그 명령을 `job-release-gate-collector`로 두고 `config/jobs.yaml` 주기로 돌린다(서비스 안 폴링은 끈다).
- (3) 두 버전 값을 deploy가 어디서 받아야 하는지 정한다. 제안: 이미지 라벨(survey-service 이미지가 이미 `io.openit.turn-engine`, `io.openit.model-runtime` 라벨을 낸다)에서 읽거나, 게이트 이미지를 빌드할 때 같은 태그를 넣는 절차를 헤드가 정한다.
