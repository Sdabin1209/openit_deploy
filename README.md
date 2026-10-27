# deploy (배포 · E2E · 데모)

문진 시스템의 여러 영역이 만든 이미지를 한 서버에서 Docker Compose로 묶어 띄우고, 되돌리고, 끝에서 끝까지 시험하는 영역이다.

이 영역은 서비스 코드를 쓰지 않는다. 각 영역이 만들어 게시한 이미지(digest)를 `locks/images.lock`에 잠그고, 그것으로 네트워크·볼륨·비밀 파일·헬스체크를 갖춘 구성(`compose.yaml`)을 띄운다. 백업·복구, 주기 잡 스케줄러, 합격 시나리오 E2E(`scripts/e2e.sh`), 화면을 눌러 보는 데모(`scripts/demo.sh`)가 여기 있다. 하지 않는 것: 서비스 코드 수정, 릴리스 활성 포인터(내용 축) 되돌리기(게이트의 몫), 계약 수정, GPU 서버 운영(docs/brief.md, docs/boundary.md).

## 1. 전체 속의 위치

계약을 만들거나 소비하지 않는다(docs/brief.md). 입력은 이웃이 게시한 이미지 digest뿐이고, 출력은 "돌아가는 시스템"이다. 외부 입구는 gateway 하나다(D11).

| 이웃 | 무엇을 | 인터페이스 (docs/E2E.md, docs/boundary.md) |
| --- | --- | --- |
| 각 영역 리포지토리 | 이미지를 받아 digest로 잠근다 (`publish-image.sh`, `publish-images.sh`) | 이미지 라벨 `io.openit.*`, `/healthz`, `/readyz` |
| question-authoring | 컨테이너로 띄움 | I1 문항 읽기 |
| release-gate | 컨테이너로 띄움. 수집기 잡 실행 | I1, I3 읽기 -> I4 릴리스 포인터, I5 롤백. 승인 `GET /v1/submissions/{id}/review-report`, `POST /v1/approvals` |
| survey-service | 컨테이너로 띄움 | I4 폴링 -> I6 Trace 전송, I9로 model-serving 호출 |
| ops-feedback | 컨테이너와 주기 잡 | I6 수집 -> I7 실패 사례 |
| model-registry (model-lab 소스), model-serving (model-runtime 소스) | 컨테이너로 띄움(가짜 모델 변형만) | I3 모델 패키지, I9 추론 |
| kiosk-frontend, admin-console | 정적 화면 이미지 | gateway 경유 `/`, `/staff/`, `/admin/` |
| boundary-contracts, 문진 스키마 | E2E 검증기로만 사용 | `boundary_contracts.validator` |

## 2. 구조

| 경로 | 역할 |
| --- | --- |
| `compose.yaml` | 상시 구성: gateway, kiosk-frontend, admin-console, survey-service, question-authoring, ops-feedback-ingest, release-gate, model-serving, model-registry + 잡 2개(job-ops-feedback, job-release-gate-collect) |
| `compose.registry.yaml` / `compose.test.yaml` / `compose.llm*.yaml` / `compose.inference.yaml` / `compose.external-inference.yaml` | 로컬 레지스트리 / E2E·데모용 시험 구성 / 실제 LLM(GPU) 데모 / 추론 서버 단독 / 외부 추론 서버 연결 |
| `locks/images.lock` (+ `locks/history/`) | 이미지 digest 잠금(코드 축). 롤백은 이것을 되돌리는 일 |
| `config/` | Caddyfile, 주기 잡 `jobs.yaml`, 백업 예시, 서비스별 env 예시 |
| `scripts/` | `doctor.sh` 사전 점검, `build-images.sh`·`publish-images.sh`, `gen-secrets.sh`, `up.sh`·`down.sh`·`status.sh`, `rollback.sh`, `backup.sh`·`restore.sh`, `scheduler.py`, `e2e.sh`, `demo.sh`, `check-*.sh` 점검기 |
| `test/` | 시험용 대역(가짜 모델 문항 순서 등). 이름에 test가 들어간다 |
| `docs/` | 아래 7절 |
| `secrets/`, `state/`, `build/`, `.env`, `.venv/` | 로컬에서 만들어지는 것. git에 넣지 않는다(.gitignore) |

```
각 영역 CI/로컬 빌드 -> 로컬 레지스트리 -> publish-image(s).sh -> locks/images.lock
                                                                   |
 gen-secrets.sh -> secrets/tokens/* -> (NAME_FILE) ->  up.sh -> compose.yaml -> gateway(edge) -> 서비스(serving/authoring/release/logs)
                                                                   |
 e2e.sh / demo.sh: 같은 구성 + compose.test.yaml(시험 대역)을 임시 프로젝트로 띄워 1~9단계를 확인
```

## 3. 실행 방법

전제: git, python3(3.10+)와 venv, Docker(데몬 + compose + buildx). 이미지는 형제 폴더의 영역 리포 소스로 빌드하므로 `deploy`의 상위 폴더에 영역 리포들이 나란히 있어야 한다(`head/setup.sh`가 받아 준다). 설치 상세와 환경별 증상표는 docs/SETUP.md.

```
cd <루트>/deploy
bash scripts/doctor.sh                 # 1) 사전 점검. FAIL이면 안내된 한 줄 해결을 먼저 한다
bash scripts/e2e.sh                    # 2) 시험: 빌드 + 임시 레지스트리 + 전체 합격 시나리오(인도 전 필수). 개발 중에는 --fast --reuse-build
bash scripts/demo.sh up                # 3) 화면을 눌러 보는 데모(프로젝트 deploy-demo). 끝나면 demo.sh down
```

상시 구성(운영 형태): `registry.sh up` -> `build-images.sh` -> `publish-images.sh` -> `gen-secrets.sh` -> `cp .env.example .env` -> `up.sh deploy`. 상시 구성은 활성 릴리스가 없어 survey-service `/readyz`가 503 `no_active_release`인 것이 정상이다(docs/runbook.md). 상태 `status.sh`, 내리기 `down.sh deploy`, 롤백 `rollback.sh`.

비밀은 환경 변수가 아니라 파일이다(D84): `gen-secrets.sh`가 `secrets/tokens/<이름>`을 만들고(값은 출력하지 않는다), compose가 서비스마다 필요한 것만 `/run/secrets`에 마운트하며 서비스는 `NAME_FILE` 경로로 읽는다(docs/RUN.md 4-1절). 점검: `bash scripts/check-secrets-hidden.sh`.

이 세션에서 직접 돌려 본 것(가벼운 것만): `bash -n scripts/*.sh`(문법, 이상 없음), `doctor.sh --help`, `demo.sh --help`, `scheduler.py status`(잡 6개와 `interval_seconds: null` 출력), `docker --version`, `docker compose version`. **돌리지 않은 것**: `doctor.sh` 본 실행, 이미지 빌드, `up.sh`, `e2e.sh`, `demo.sh up`, `backup/restore`, `check-*.sh`, 시험 스크립트(`test-*.sh`). 이 영역에는 pytest 시험이 없고 시험은 셸 스크립트와 E2E다(`ls`로 확인).

## 4. 현재 상태

확인된 것(모두 이 PC의 WSL2 + Docker Desktop 한 환경, docs/STATUS.md):
- 가짜 모델 E2E(`scripts/e2e.sh`)의 통과 수는 `docs/E2E_RESULTS.md`가 정본이다(실행마다 e2e.sh가 한 줄을 자동으로 더하고, 과거 값은 근거와 함께 그 파일의 '과거 기록' 표에 있다). 이 문서에는 숫자를 옮겨 적지 않는다(check-all 규칙 10이 잡는다).
- 단계 상태(STATUS.md 열다섯째 구간): 2단계는 배선 REAL·데이터는 시험용(synthetic-data 게시기 모드, 실제 학습 데이터로 게시한 적 없음; docs/E2E.md), 직원 알림 화면 SKIPPED(G01), 3·6단계 일부 TEST-SUB(시험 대역). 즉 "전체 합격"이 아니라 "돌린 검사가 모두 통과"다.
- 기준 태그: boundary-contracts v2.0.2, turn-engine v0.4.0, model-runtime v0.7.3 (`scripts/lib.sh`).
- gpu-dev(12GB)에서 Qwen3-1.7B 적재와 형식 통과 확인, 단 키오스크 14턴은 학습 안 된 모델 탓에 모두 실패(OPEN_GAPS U01, U07. 이 세션은 확인하지 않고 대장을 옮겼다).

확인하지 못한 것: 깨끗한 두 번째 환경(일반 Linux 서버)에서의 설치(U06, U12), 24GB GPU, 진짜 어댑터로 한 턴(H1~H4), 실제 브라우저·음성·푸시(U05), 서버 밖 외부 감시(자리만 있음), 백업 주기(설정 없으면 `backup.sh`가 거부, 의도).

## 5. 이 영역의 열린 항목 (헤드의 OPEN_GAPS.md에서 골랐다. ID 그대로)

| ID | 요약 | 막고 있는 것 |
| --- | --- | --- |
| H1 | 24GB급 GPU에서 Qwen3-8B 적재·실측 (순서는 docs/GPU_HOLE.md) | GPU |
| H2 | 학습된 LoRA-A/B를 얹어 한 턴 통과, 어댑터 교체 (U07, U08, U10) | GPU + 학습 결과(model-lab) |
| H4 | 문법 컴파일 비용, 동시 부하 (U01, U04). 부하 시험 스크립트는 없음 | GPU |
| U07 | 새 구조의 실제 LLM 데모. 모델 정확성은 학습 쪽 몫 | GPU, 다른 영역 |
| U06 / U12 | 일반 Linux 서버 설치, 두 번째 독립 머신 확인 | 환경 마련(사용자) |
| D-A | 운영 도메인·HTTPS, 콘솔 로그인, CI가 서버 레지스트리에 닿는 방법, 토큰 발급·회전 | 사용자 결정 |
| G01 / G02 | 직원 알림 입력원 없음 / synthetic-data가 v1 내용을 만듦. E2E에서 SKIPPED·BLOCKED로 드러남 | 다른 영역, 사용자 결정 |
| (O16) | 허용 중단 시간·복구 시점, 백업 주기. OPEN_GAPS에는 없고 docs/brief.md에 있음 | 사용자 결정 |

H3(학습 파이프라인 실행)와 G06은 model-lab 몫이다(docs/GPU_HOLE.md).

## 6. 먼저 알아 둘 것

- 코드 축 롤백은 잠금 파일을 되돌리는 것(`rollback.sh`)이고, 릴리스 포인터 되돌리기는 게이트가 한다.
- 데모와 E2E의 모델·승인자는 시험용 대체다. 실제 모델·실제 승인이 아니다.
- 학습 서버·GPU 서버 접속은 이 리포의 세션이 하지 않는다. GPU 절차는 사용자가 따라 하도록 docs/GPU_HOLE.md에 있다.

## 7. 더 자세한 문서 (docs/)

| 문서 | 내용 |
| --- | --- |
| [brief.md](docs/brief.md) | 영역 목적, 범위, 수용 기준 |
| [boundary.md](docs/boundary.md) | 소유·소비, 서비스별 환경 변수·포트·볼륨, 장애 영향 |
| [design.md](docs/design.md) | 내부 설계(네트워크 분리, 연결 표) |
| [SETUP.md](docs/SETUP.md) | 환경별 설치, 증상별 표 |
| [RUN.md](docs/RUN.md) | 상시 구성·데모 실행, 비밀 파일, 버전 표 점검 |
| [runbook.md](docs/runbook.md) | 적용·롤백, 백업·복구, 주기 잡, 흔한 문제 |
| [E2E.md](docs/E2E.md) | 1~9단계 합격 시나리오(헤드 전달본) |
| [GPU_HOLE.md](docs/GPU_HOLE.md) | GPU 서버가 열릴 때 할 일(H1~H4) |
| [ci.md](docs/ci.md) | 영역 CI가 이미지를 게시하는 계약(D24) |
| [STATUS.md](docs/STATUS.md) | 구간별 한 일과 시험 결과 |
| [E2E_RESULTS.md](docs/E2E_RESULTS.md) | E2E 통과 수의 정본(실행 기록 + 과거 기록) |
| `docs/change-requests/` | 헤드에게 보낸 변경 요청(CR-D01~D22) |
| [CHANGELOG.md](CHANGELOG.md) (리포 루트) | 변경 이력 |
