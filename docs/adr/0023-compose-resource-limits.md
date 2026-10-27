# 0023. 컨테이너 자원 한도: 서비스마다 mem_limit·cpus·pids_limit, 값은 측정 안 한 시작값

- 상태: 채택 (값은 잠정)
- 날짜: 2026-10-28

## 맥락

한 서버에 postgres와 모델 서빙, 서비스 일곱 개가 같이 있다. 한도가 전혀 없으면(점검 A9·F3·G3) 한 서비스의 메모리·프로세스 폭주가 환자 경로를 막고 호스트를 OOM으로 몰 수 있다. 큰 본문 폭주(B4)와 겹치면 위험하다.

## 결정

`compose.yaml`의 모든 서비스(상시 + job-*)와 레지스트리에 `mem_limit`, `cpus`, `pids_limit`을 **변수**(`<서비스>_MEM_LIMIT` 등, 기본값은 compose에 있음)로 둔다. 목록과 기본값은 `config/resource-limits.env.example`. postgres는 `shm_size`도. 실제 LLM(`compose.llm.yaml`)은 model-serving 한도를 별도 변수로 크게 덮는다. job-*는 로그 회전(10m x 5)을 더한다. `compose.inference.yaml`(GPU 서버 전용 호스트의 서빙 하나)은 한도를 두지 않는다.

| 서비스 | mem | cpus | pids |
|---|---|---|---|
| postgres | 2g | 2.0 | 300 (+ shm 256m) |
| gateway | 256m | 1.0 | 256 |
| kiosk-frontend, admin-console | 128m | 0.5 | 128 |
| survey-service, question-authoring, ops-feedback-ingest, model-registry | 512m | 1.0 | 256 |
| release-gate | 1g | 1.0 | 256 |
| model-serving (fake/CPU) | 1g | 2.0 | 512 |
| model-serving (실제 LLM, compose.llm.yaml) | 16g | 4.0 | 2048 |
| job-ops-feedback | 1g | 1.0 | 256 |
| job-release-gate-collect | 512m | 1.0 | 256 |
| 레지스트리 | 512m | 1.0 | 128 |

## 왜 (따른 표준과 근거)

- **한도를 두는 것**은 컨테이너 격리의 일반 지침이다(Docker 자원 제한 문서, OWASP Docker Security Cheat Sheet, CIS Docker Benchmark의 메모리·CPU·PID 한도 항목). 이 세션에서 원문을 다시 열어 대조하지는 않았다.
- **표의 숫자는 측정에서 나온 것이 아니다. 근거 기록이 없다.** 서비스 종류(정적 화면, 파이썬 HTTP 서비스, DB, 모델 서빙)에 대한 이 에이전트의 어림이다. 처리량·동시 키오스크 수·실제 메모리 사용은 측정한 적이 없다(점검 G1·E6 '확인 못 함'). 그래서 변수로 열어 두고 H1(GPU 서버, 환자 부하) 실측 뒤 재정한다.
- 변수로 둔 이유: 값이 틀렸을 때 이미지를 고치지 않고 `.env`에서 바꿀 수 있게.

## 검토한 대안과 버리는 이유

- **한도 없음(현상 유지)**: 폭주 격리가 전혀 없다. 버린다.
- **측정 뒤에 한도를 넣는다**: 측정(H1)이 GPU 서버를 기다리므로 그동안 무방비다. 틀릴 수 있는 시작값이 무방비보다 낫다고 판단했다.
- **`deploy.resources.limits`(compose 사양)**: 단일 서버 compose에서 `mem_limit`/`cpus`/`pids_limit`이 더 단순하고 같은 효과다.
- **실제 LLM에 한도 없음**: OOM으로 죽는 것보다는 낫지만 호스트 전체 보호가 사라진다. 넉넉한 16g로 두고(측정 안 함) 재정한다.

## 결과

- 얻는 것: 한 서비스의 폭주가 호스트와 이웃으로 번지는 것을 막는다.
- 감수하는 것: **값이 너무 낮으면 정상 부하에서 OOM kill이 난다.** 이 변경 뒤 전체 E2E에서 처음 확인된다(이 에이전트는 E2E를 돌리지 않았다). 컨테이너가 죽으면 `restart: unless-stopped`로 되살아난다. `check-containers.sh`가 한도가 있는지 읽는다.

## 되돌리는 조건

- H1 실측으로 서비스별 실제 사용량이 나오면 표를 그 값에 여유를 얹어 다시 정한다(이 ADR을 대체).
- 한 서비스가 정상 부하에서 한도에 걸리면 그 변수만 올린다.
