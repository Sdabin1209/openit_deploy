# deploy 설계

> 확인한 것은 이 문서에 "확인"으로, 제안은 "제안", 정해지지 않은 것은 "미정"으로 표시한다. 영역 코드(src)는 읽지 않았고, 아래 서비스 사실은 각 영역의 `docs/boundary.md`, `docs/runbook.md`, `Dockerfile`, `scripts/`와 실제로 이미지를 띄워 본 결과다.

## 1. 구성 한눈에

```
 (외부)                    edge                  serving                          release (internal)                  logs (internal)
 클라이언트 ──▶ gateway ──┐
 (공개 API는 O06 대기)    └▶ survey-service ──I4──▶ release-gate ──I1──▶ question-authoring
                              │  (edge, serving)      │ (serving, release)        (authoring, release)
                              └─────────I6──▶ ops-feedback-ingest            ──I3──▶ model-registry (release)
                                              (serving, logs)  ▲ job-ops-feedback (logs, release): I4 읽기
 서빙 서버 밖(GPU, D40): model-lab 파이프라인(I3 게시), 승인 평가 워커, synthetic-data의 LLM 생성. 호스트/GPU 서버의 run-once 잡은 I1·I7을 HTTP로 읽는다
```

| 네트워크 | 성격 | 붙는 서비스 | 용도 |
| --- | --- | --- | --- |
| edge | 일반(호스트 포트 가능) | gateway, survey-service | 외부 입구. 호스트 포트를 여는 것은 gateway뿐이다(D11) |
| serving | internal | survey-service, release-gate, ops-feedback-ingest | I4 읽기(survey→gate), I6 수집(survey→ops) |
| authoring | internal | question-authoring, ops-feedback-ingest | 저작 면(관리자 콘솔 자리). ops-feedback-ingest를 더한 이유: 개선 신호(`/v1/signals`)가 I7 읽기 면을 부른다 |
| release | internal | release-gate, question-authoring, model-registry, job-ops-feedback, job-release-gate-collect | 게이트가 I1(qa)·I3(model-registry)를 읽는 길, ops 잡이 I4를 읽는 길 |
| logs | internal | ops-feedback-ingest, job-ops-feedback | 원본 Trace 저장소(`ops-data`)를 만지는 프로세스끼리 |

**서비스 사이 연결(D49, 모두 HTTP, base URL의 호스트는 Compose 서비스 이름이다)**

| 호출자 -> 서버 | 인터페이스 | 네트워크 | 토큰(호출자의 환경 변수 이름 <- 서버가 묶은 역할) |
| --- | --- | --- | --- |
| survey-service -> release-gate | I4 `/v1/active-pointer`, 릴리스, 번들 | serving | `SURVEY_RELEASE_READER_TOKEN` <- `GATE_READ_TOKENS` 역할 survey-service |
| survey-service -> ops-feedback-ingest | I6 `/v1/traces` | serving | `SURVEY_TRACE_INGEST_TOKEN` <- `OPS_INGEST_TOKEN` |
| release-gate -> question-authoring | I1 읽기 | release | `GATE_I1_TOKEN` <- `QA_READ_TOKENS` 역할 release-gate |
| release-gate -> model-registry | I3 읽기 | release | `GATE_I3_TOKEN` <- `MODEL_REGISTRY_READ_TOKENS` 역할 release-gate |
| job-ops-feedback -> release-gate | I4 읽기(사례의 문항 세트 채움) | release | `OPS_GATE_READ_TOKEN` <- `GATE_READ_TOKENS` 역할 ops-feedback (롤백 자동 요청을 켜면 `OPS_GATE_WRITE_TOKEN`) |
| question-authoring -> ops-feedback-ingest | I7 읽기(개선 신호) | authoring | `QA_FAILURES_TOKEN` <- `OPS_READ_TOKENS` 역할 question-authoring |
| (밖) 검토자 -> ops-feedback-ingest | `POST /v1/cases/{id}/review` | (UI 없음) | `OPS_REVIEW_TOKENS` 역할 reviewer |
| (밖) synthetic-data -> question-authoring / ops-feedback | I1 / I7 읽기 | 호스트(시험) 또는 GPU 서버 | 역할 synthetic-data |
| (밖) model-lab -> model-registry | I3 게시 | GPU 서버에서 접근 경로 미정(CR-D12) | `MODEL_REGISTRY_WRITE_TOKENS` 역할 model-lab |

네트워크 분리와 충돌이 있었던 곳: **없다.** 이 연결은 위 5개 네트워크 배치로 전부 설명된다(survey는 serving으로 gate·ops만 닿고 qa·model-registry에는 닿지 못한다). 근거와 유지 규칙: (1) 서빙 런타임 경로는 survey가 부르는 두 서비스(gate의 읽기 면, ops의 수집)만 `serving`에 둔다. (2) 게이트의 입력(I1, I3)은 `release`에 두어 survey가 문항 저장소·모델 저장소에 직접 닿지 못하게 한다(survey는 게이트가 묶은 사본만 쓴다). (3) 원본 Trace는 `logs`로 한정한다. (4) 이웃의 저장소 볼륨은 공유하지 않는다(D50). 같은 영역이 소유한 프로세스끼리만 볼륨을 공유한다(release-gate와 그 수집 잡의 `gate-data`, ops-feedback ingest와 그 잡의 `ops-data`).
미정: GPU 서버(밖)에서 model-registry, question-authoring 읽기 면, ops 읽기 면에 닿는 길(공개 포트인지 터널인지). 지금 Compose는 이들을 호스트에 열지 않는다(시험 구성만 `127.0.0.1` 동적 포트).

확인: E2E가 매번 도달 가능(survey→ops, survey→gate, gate→qa, gate→model-registry)과 차단(survey→qa, survey→model-registry, qa→ops, ops→qa, ops→model-registry, release-gate→인터넷)을 검사한다. 한계: 같은 네트워크의 서비스끼리는 서로 닿는다. 인증(토큰, 역할)이 막는다.

## 2. 두 개의 축 (D07)

| 축 | 무엇 | 어디 | 바꾸는 법 |
| --- | --- | --- | --- |
| 코드 | 이미지 digest | `locks/images.lock` (+ `locks/history/`) | `publish-images.sh`가 갱신, `rollback.sh`가 이전 것으로 되돌림 |
| 내용 | 릴리스 활성 포인터 | release-gate 레지스트리 | 게이트의 몫. deploy는 건드리지 않는다 |

- `compose.yaml`은 이미지를 `${DEPLOY_REGISTRY}/openit/<영역>@${<영역>_DIGEST}` 꼴로만 쓴다. 태그를 쓰지 않는다. `scripts/check-compose.sh`가 이를 검사한다(E2E가 돌린다). 외부 이미지(gateway, registry, 유틸)도 `@sha256:`로 고정한다.
- 잠금 파일은 환경 변수 형식(`KEY=value`)이다. 서비스마다 `<영역>_DIGEST`, `<영역>_REVISION`(커밋). 셸에 남은 같은 이름의 변수가 잠금을 이기지 못하게 `dc`가 지운다(시험 중 실제로 겪은 문제).
- 롤백 = 잠금을 `locks/history/`의 이전 것으로 되돌리고 `up.sh`. 현재 잠금도 history에 남기므로 롤백을 되돌릴 수도 있다. E2E가 "새 버전 게시 → 적용 → 롤백 → 이전 digest 컨테이너"를 실제로 돈다.
- 로더가 지원하지 않는 계약 버전을 거부하는 것은 각 서비스의 몫이다(survey-service의 적재 거부 확인은 영역 문서에 있다). deploy는 이미지 라벨로 계약·라이브러리 버전을 노출한다.

## 3. 로컬 레지스트리와 CI 제출 (D24)

- `compose.registry.yaml`(registry:2, 별도 프로젝트). 운영은 `127.0.0.1:5000`, 볼륨 `registry-data`.
- 빌드는 `scripts/build-images.sh`: 영역 리포지토리를 `git archive HEAD`로 `build/ctx/<이름>`에 꺼내 그 사본에서 영역의 빌드 스크립트(wheel 만들기)를 실행하고 `docker build`한다. 라이브러리(boundary-contracts, turn-engine, model-runtime)는 영역 스크립트가 `git -C ../<이름> archive <태그>`로 읽으므로 `build/ctx/<이름>`에 bare 사본을 둔다. 이웃 리포지토리는 수정하지 않는다.
- `publish-images.sh`: push → 레지스트리 digest와 push 출력의 digest가 같은지 확인 → 잠금 갱신. 지금은 CI가 없어 사람이(또는 스케줄러가) 돌린다. 영역 CI가 생기면 같은 일(이미지 push, digest 제출)을 CI가 하고 deploy는 `locks/images.lock` 갱신 절차만 둔다. 제출 방법(PR인지 API인지)은 미정(D24).
- 환경 제약(확인): Docker Desktop(WSL)은 데몬이 VM 안에 있어, Docker가 배정한 임의 호스트 포트나 `127.0.0.1` 게시 포트에는 데몬이 접근하지 못했다. `0.0.0.0` 게시와 지정 포트는 되었다. 그래서 시험은 레지스트리만 "빈 포트를 골라 `0.0.0.0`에 잠시" 띄운다(`registry.sh`, 끝나면 내림). 리눅스 서버에서는 기본값 `127.0.0.1:5000`이면 된다.

## 4. gateway: Caddy를 고른 근거

후보: Caddy, nginx, Traefik.

| | 장점 | 단점 | 판단 |
| --- | --- | --- | --- |
| Caddy | 설정 몇 줄, 이미지 작음, TLS 자동 발급 내장, 설정 파일 하나 | 설정 문법이 덜 알려짐 | 선택 |
| nginx | 가장 널리 알려짐 | TLS 발급·갱신을 따로 붙여야 함 | 대안(바꿔도 무방) |
| Traefik | 라벨로 동적 라우팅 | docker 소켓이 필요(보안 면적 큼), 서비스 몇 개뿐인 이 구성에 과함 | 제외 |

- 지금 gateway는 `/healthz`, `/readyz`만 응답하고 나머지는 404다. **공개 API 경로(I10)는 O06 대기라 만들지 않았다**(E2E가 `POST /v1/turns`가 404인지 확인). 업스트림 자리는 `config/Caddyfile`의 주석.
- 비root(10001), 읽기 전용 루트, `NET_BIND_SERVICE`만 추가(caddy 바이너리의 파일 권한 때문에 cap_drop ALL이면 실행이 거부됨을 시험으로 확인).
- 미정: 공개 도메인, TLS(자동 발급은 도메인과 80/443 개방이 필요), 호스트 바인드. 지금은 `127.0.0.1:${GATEWAY_PORT}`에 HTTP, TLS 끔.

## 5. 저장소, 계정, 비밀 값

- 확인: 네 영역의 저장소는 모두 **SQLite 파일**이다(O10을 영역이 정했다). 그래서 "저장소별 DB 인스턴스·계정"을 DB 서버 계정으로 만들 수 없다. deploy는 같은 효과를 이렇게 낸다(제안, 헤드 확인 필요: CR-D07).
  - 저장소마다 볼륨 하나(`survey-data`, `qa-data`, `ops-data`, `gate-data`). 쓰기 마운트는 소유 서비스만.
  - 이웃은 HTTP+토큰으로 읽는다. 읽기 전용 마운트는 쓰지 않는다: WAL 모드 SQLite는 읽기 전용 마운트에서 `-shm`을 만들지 못해 열리지 않을 수 있음을 시험에서 만났다. 백업 도구만 볼륨을 붙이고 읽기만 한다(만든 `-wal/-shm`은 지운다).
- 토큰(CONVENTIONS 9절): `scripts/gen-secrets.sh`가 `secrets/`(gitignore)에 서비스·역할마다 다른 토큰을 만든다.

| 서버 | 환경 변수(서버) | 읽기 역할 | 쓰기 역할 |
| --- | --- | --- | --- |
| release-gate | `GATE_READ_TOKENS`, `GATE_WRITE_TOKENS` | survey-service, ops-feedback, question-authoring, model-lab, synthetic-data | operator, ops-feedback, question-authoring, model-lab, release-gate-collector |
| question-authoring | `QA_READ_TOKENS`, `QA_AUTHOR_TOKENS` | release-gate, synthetic-data, model-lab | 저자(actor:역할) |
| ops-feedback | `OPS_READ_TOKENS`, `OPS_INGEST_TOKEN` | synthetic-data, model-lab, question-authoring | 수집: survey-service |
| model-registry | `MODEL_REGISTRY_READ_TOKENS`, `MODEL_REGISTRY_WRITE_TOKENS` | release-gate, model-lab | model-lab |
| job-ops-feedback | `OPS_DEID_SALT` | | 운영 중 바꾸지 않는다 |

`scripts/gen-secrets.sh`가 `secrets/tokens/<서버>-<read|write>-<역할>`로 역할마다 다른 토큰을 만들고, 서비스는 `secrets/<서비스>.env`에서 **자기 것만** 받는다(서버용 목록과 자기가 호출할 이웃용 토큰). 클라이언트가 이웃 토큰을 받는 환경 변수의 이름은 각 영역 런북이 정한 것을 쓴다(survey: `SURVEY_*_TOKEN_ENV`로 이름 지정, gate: `GATE_I1_TOKEN`·`GATE_I3_TOKEN`, ops 잡: 설정의 `{env: 이름}`).

비밀 값은 이미지·리포지토리에 없다. 서비스는 자기 `env_file`(`secrets/<서비스>.env`)만 받는다. 클라이언트가 어떤 환경 변수 이름으로 토큰을 받는지는 클라이언트 SDK가 아직 없어 정할 수 없다(CR-D01).

## 6. 서비스 표

[boundary.md](boundary.md)의 표를 본다.

## 7. 주기 잡 스케줄러 (D39): 호스트 스케줄러를 고른 근거

후보: (a) 컨테이너 안 cron/supercronic, (b) ofelia 같은 docker 소켓 스케줄러, (c) 호스트에서 도는 가벼운 스케줄러(`scripts/scheduler.py`) + `docker compose run --rm`.

- (a)는 잡이 서로 다른 이미지에서 돌아야 해서 cron 컨테이너가 잡마다 이미지를 갖거나 docker를 불러야 한다. (b)는 컨테이너에 docker 소켓을 줘야 하므로 서버 권한을 넘긴다. 선택은 (c): 잡은 그 영역 이미지·볼륨·네트워크로 `docker compose run --rm`(프로필 `jobs`)에서 한 번 돌고 끝난다. 스케줄러는 소켓을 컨테이너에 주지 않는다.
- `tick`(한 번 보고 끝)은 cron이나 systemd timer가 부르고, `loop`는 직접 돌릴 때 쓴다. 상태는 `state/scheduler.json`. 같은 잡이 실행 중이면 건너뛰고(flock), 기한 전에는 아무것도 하지 않는다(멱등).
- 주기는 `config/jobs.yaml`의 `interval_seconds`. **지금은 모두 `null`(미정)이고, null이면 실행하지 않는다.** 이 주기는 사용자 결정이다. 코드에 기본값이 없다.
- `where: gpu-external`(release-gate 승인 평가 워커, synthetic-data, model-lab 파이프라인)은 서빙 서버 밖 GPU 서버의 일이다(D40). Compose에 넣지 않았고 스케줄러도 실행하지 않는다. 승인 평가 워커의 **실행기 구현이 release-gate에 없다**(CR-D10).
- 구성된 잡: `job-ops-feedback`(`python -m ops_feedback.job --config /config/job.yaml`), `job-release-gate-collect`(`python -m release_gate collect`, 후보 수집기 run-once), `backup`. 둘 다 서비스와 같은 이미지·네트워크로 `docker compose run --rm`. 설정 파일 값(비식별 기준 등)은 사용자 결정이라 운영 설정은 없고, 시험용 설정은 `test/ops-job/`.

## 8. 백업·복구 (O16 미정)

- `backup.sh`: 저장소마다 스냅샷 디렉터리(`<BACKUP_DIR>/<저장소>/<UTC 시각>/`)에 SQLite는 backup API로 일관된 사본, 나머지 파일은 복사, `MANIFEST.json`에 파일별 sha256. `.partial`에 쓰고 완료 뒤 이름을 바꾼다. SQLite를 먼저, 나머지 파일(게이트의 `releases/`)을 나중에 복사한다(릴리스 파일은 불변이라 DB 행이 가리키는 파일이 사본에 있다). survey-data의 `releases/` 작업 폴더는 게이트 묶음에서 다시 적재되는 사본이라 제외한다.
- **설정이 없으면 거부한다**: `config/backup.env`(또는 `BACKUP_CONFIG`)에 `BACKUP_DIR`와 정수 `BACKUP_RETENTION_DAYS`가 있어야 하고, 아니면 종료 코드 2다. 코드에 기본값이 없다. 주기는 `config/jobs.yaml`의 `backup.interval_seconds`. 허용 중단 시간·복구 시점(O16)이 정해지면 이 둘을 정한다.
- 보관 기간을 넘긴 스냅샷은 새 백업이 끝난 뒤 지운다(저장소마다 최신 하나는 항상 남긴다).
- `restore.sh <저장소> <스냅샷> --yes`: 그 볼륨을 쓰는 컨테이너가 있으면 거부, 해시 검증 후 볼륨을 비우고 복원, 소유자 10001. E2E가 4개 저장소를 실제로 지웠다가 복구하고(논리 지문 일치, ops는 같은 Trace 재전송이 DUPLICATE, qa는 두 문항 버전이 읽기 전용 SDK로 읽히고 해시 일치) 서비스를 다시 띄운다.
- 서버 밖 사본, 암호화, 백업 대상의 오프사이트 전송은 미정(O16과 함께 사용자 결정이 필요).

## 9. 서버 밖 외부 감시 자리 (D10)

- 구성: 서버 밖 감시자가 gateway의 `/healthz`(공개 주소가 정해지면)를 주기로 호출하고 실패 시 유지보수 담당에게 알린다. 서버 전체 중단은 비보증이다.
- 이 저장소의 자리: `config/external-monitor.example.yaml`(감시 대상 URL 목록과 알림 대상 자리, 실제 서비스·주소·연락처는 미정이라 값 없음).
- 미정: 감시 서비스 선택, 공개 주소, 알림 채널. 사용자 결정.

## 10. 컨테이너 규칙(D22) 적합성

| 규칙 | 상태 |
| --- | --- |
| 설정은 환경 변수로만 | 확인(각 이미지). deploy도 env_file/환경 변수만 |
| 비밀 값 이미지·리포지토리에 없음 | 확인. `secrets/` gitignore, `.env.example`만 |
| 로그 표준 출력 | 확인(`docker logs`), json-file 회전만 설정 |
| 비root | 확인(E2E: uid≠0). gateway도 10001 |
| `/healthz` `/readyz` | 4개 서비스 확인. gateway도 둔다 |
| 이미지 라벨(커밋, 계약, 라이브러리 버전) | 확인: 5개 이미지 모두 `io.openit.*` 6개(E2E가 검사) |
| 스모크 고정 포트 금지 | 확인. 컨테이너 포트는 Docker 배정을 읽는다. 레지스트리만 사정이 있다(3절) |
| 이름에 deploy 접두어 | 프로젝트 이름 `deploy`/`deploy-e2e-<pid>`로 컨테이너·네트워크·볼륨에 붙는다 |
| 이웃 대신 메모리 구현으로 혼자 시험 | 영역 단독 시험은 각 영역 몫. deploy의 E2E는 이제 실제 이웃 서비스와 만난다 |

## 11. 시험 자료와 운영 설정의 분리

- `compose.test.yaml`, `test/`, `build/`, `state/`만 시험용이다. `compose.yaml`과 `config/`는 시험 자료를 참조하지 않는다(E2E가 `compose.yaml`·`config/`에 시험용 정책·실행기·시험 워커가 없음을 확인한다).
- 시험 자료: `test/policy/test-gate-policy.json`(시험용 게이트 정책, 임계치 무의미, `compose.test.yaml`에서만 `GATE_POLICY_FILE`로 연결), `test/gate-runner/test_gate_runner.py`(시험용 승인 평가 실행기, 고정 지표), `test/ops-job/test-ops-job.yaml`(시험용 잡 설정), `test/fixtures/e2e-test-adapter/`(시험용 PEFT 형식 어댑터). 시험용 ID에도 `test`를 넣는다(`qs-e2e-test`, `pkg-e2e-test-*`).
- 운영 게이트에는 정책이 없다: `can_pass:false`가 정상이다(D38, O11). 시험 구성에서만 `can_pass:true`가 된다.
