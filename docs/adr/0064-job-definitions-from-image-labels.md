# 0064. 잡 정의는 이미지 라벨에서 만든다

- 상태: 채택(2026-11-04). 구조 점검 S10.
- 맥락: `compose.yaml` 이 잡마다 `python -m <모듈> <부명령>` 을 손으로 적고 있었다. 모듈 이름과 부명령은 영역 내부 구조다(구조 규칙 1). 영역이 바꾸면 deploy 가 따로 깨진다. 잡의 실행 시간 상한도 영역이 안다(RUNTIME R9.2).
- 결정: 영역 이미지의 라벨 `io.openit.jobs`(계약 `JobsDeclaration`)가 잡의 `argv`·`timeout_seconds` 의 정본이다. `scripts/gen-jobs.py` 가 compose 의 `job-*` 서비스마다 라벨을 읽어 계약 validator 로 검증하고 `state/compose.jobs.yaml` 덧씌우기를 만든다(`job_overlay` 컴포넌트: 입력 JobOverlayRequest, 출력 JobOverlayResult). `compose.yaml` 의 잡 `command` 는 자리표시 오류만 둔다. `run-job.sh` 가 덧씌우기의 시간 상한(없으면 RUNTIME R9.3 의 3600초)으로 `timeout` 을 건다.
- 왜(근거): (1) 라벨은 영역이 내는 출력이고 deploy 는 계약 스키마로만 읽는다. (2) 3600초는 RUNTIME R9.3 의 시작값이고 측정하지 않았다. (3) 상한이 실행 주기 이상이면 거부한다(R9.3: 상한은 주기보다 짧아야 겹침 방지가 다음 주기를 막지 않는다).
- 겹침과 놓친 실행(R10.12): 주기는 systemd 타이머(`OnUnitActiveSec`)이고 `Persistent` 를 쓰지 않는다. 잡 서비스는 `Type=oneshot` 이라 실행 중에는 타이머가 다시 시작하지 않는다(systemd.timer/service). 정적 시험: `scripts/test_gen_jobs.py`.
- 검토한 대안: compose 에 command 를 계속 적기 — 영역 구조를 deploy 가 안다. 라벨을 compose 해석 때 직접 읽기 — compose 는 이미지 라벨을 읽지 못한다.
- 결과: 얻는 것 — 영역이 잡 명령·시간 상한을 선언만 하면 된다. 감수하는 것 — 덧씌우기를 만들려면 이미지가 로컬에 있어야 한다(없으면 받는다).
- 되돌리는 조건: 영역이 라벨 대신 다른 선언 수단을 계약으로 정할 때.

## 갱신 2026-11-04: 실행 주기는 deploy 가 규칙으로 만든다
- 맥락: release-gate 의 collect 잡이 `timeout_seconds: 600` 을 선언했고 deploy 의 수집기 주기도 600초였다. R9.3 은 상한이 주기보다 짧아야 한다고 정한다(그렇지 않으면 겹침 방지가 다음 주기를 막는다). 잡의 시간 상한은 영역이 알고, 일정은 deploy 가 정하며 영역은 deploy 일정을 모른다(구조 규칙 4). 그래서 영역이 상한을 줄이게 하지 않고 deploy 가 주기를 정한다.
- 결정: 주기 = max(기본 주기, 선언 상한보다 큰 가장 작은 300초 배수). 기본 주기는 `config/systemd/*.timer` 의 `OnUnitActiveSec` 다(출처 D85·ADR 0036). `job_overlay` 컴포넌트가 규칙을 계산하고(600 → 900초) `gen-jobs.py` 가 선언 상한과 규칙으로 정한 주기를 넣은 유닛 사본을 `state/systemd/` 에 만든다(타이머 `OnUnitActiveSec`, 서비스 `TimeoutStartSec`, `job-metrics.sh` 의 주기 인자). JobStale 경보는 `job-metrics.sh` 가 남기는 주기에서 `2 × 주기 + 60초` 로 판정하므로 같은 규칙에서 나온다.
- 왜(근거): R9.3 과 구조 규칙 4. 300초는 사람이 읽는 5분 단위이고 타이머 `AccuracySec`(10초)보다 충분히 크게 잡은 선택이다. **측정한 값이 아니다.** 상한을 넘긴 잡은 `timeout` 이 멈추고 그 실행은 실패다(R9.2).
- 검토한 대안: 영역에게 상한을 낮추라고 요청 — 영역이 deploy 일정을 알게 된다(구조 규칙 4). 주기를 손으로 고정 — 영역이 상한을 늘릴 때마다 deploy 가 따로 깨진다.
- 결과: 얻는 것 — 상한이 바뀌어도 R9.3 을 어기는 배포가 만들어지지 않는다. 감수하는 것 — 수집 빈도가 상한에 따라 낮아질 수 있다(collect 는 10분에서 15분).
- 시험: `scripts/test_gen_jobs.py`(상한=주기 입력이면 주기가 상한보다 크다, 규칙을 빼면 R9.3 점검이 거부하는 변이, 유닛 사본의 값).
