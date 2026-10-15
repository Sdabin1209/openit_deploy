# deploy 설계

> 확인한 것은 이 문서에 "확인"으로, 제안은 "제안", 정해지지 않은 것은 "미정"으로 표시한다. 영역 코드(src)는 읽지 않았고, 아래 서비스 사실은 각 영역의 `docs/boundary.md`, `docs/runbook.md`, `Dockerfile`, `scripts/`와 실제로 이미지를 띄워 본 결과다.

## 1. 구성 한눈에

```
 (외부)                      edge                 serving                   release (internal)        logs (internal)
 클라이언트 ──▶ gateway ─────────────┐
 (공개 API는 O06 대기)               └▶ survey-service ──────▶ ops-feedback-ingest ◀───────────────────────┐
                                        │  (edge, serving)   (serving, logs)  ▲                            │
                                        └──────────────────▶ release-gate ───┼──▶ question-authoring     job-ops-feedback
                                                              (serving, release)   (authoring, release)   (logs, release)
 authoring: question-authoring 의 저작 API 면 (관리자 콘솔은 gateway 뒤에 둘 자리, 미정)
```

| 네트워크 | 성격 | 붙는 서비스 | 용도 |
| --- | --- | --- | --- |
| edge | 일반(호스트 포트 가능) | gateway, survey-service | 외부 입구. 호스트 포트를 여는 것은 gateway뿐이다(D11) |
| serving | internal | survey-service, ops-feedback-ingest, release-gate | 서비스 런타임 경로: I4 읽기, I6 수집 |
| authoring | internal | question-authoring | 저작 |
| release | internal | release-gate, question-authoring, job-ops-feedback | 게이트 입력(I1)·요청(I5 롤백) |
| logs | internal | ops-feedback-ingest, job-ops-feedback | 원본 Trace 저장소 접근 |

확인: E2E가 매번 도달 가능(survey→ops, survey→gate, gate→qa)과 차단(survey→qa, qa→ops, ops→qa, release-gate→인터넷)을 검사한다. internal 네트워크의 서비스는 바깥 인터넷으로 나가지 못한다. 한계: 같은 네트워크에 있는 서비스끼리는 서로 닿는다(예: gate→ops-ingest). 인증(토큰)이 막는다.

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

| 토큰 | 소유 서비스 환경 | 클라이언트 |
| --- | --- | --- |
| 게이트 쓰기: operator, ops-feedback, release-gate-collector, question-authoring, model-lab | release-gate `GATE_WRITE_TOKENS=역할=토큰,...` | 각 역할의 클라이언트만 자기 토큰을 받는다 |
| 게이트 읽기 | `GATE_READ_TOKEN` (**하나뿐**) | survey-service가 쓴다. 영역마다 다른 읽기 토큰은 게이트가 지원하지 않는다 → CR-D02 |
| 수집 토큰 | ops-feedback-ingest `OPS_INGEST_TOKEN` | survey-service만 |
| 저작 토큰 | question-authoring `QA_AUTHOR_TOKENS` (토큰:actor:역할) | 저자·콘솔 |
| 비식별 salt | job `OPS_DEID_SALT` | 운영 중 바꾸지 않는다 |

비밀 값은 이미지·리포지토리에 없다. 서비스는 자기 `env_file`(`secrets/<서비스>.env`)만 받는다. 클라이언트가 어떤 환경 변수 이름으로 토큰을 받는지는 클라이언트 SDK가 아직 없어 정할 수 없다(CR-D01).

## 6. 서비스 표

[boundary.md](boundary.md)의 표를 본다.

## 7. 주기 잡 스케줄러 (D39): 호스트 스케줄러를 고른 근거

후보: (a) 컨테이너 안 cron/supercronic, (b) ofelia 같은 docker 소켓 스케줄러, (c) 호스트에서 도는 가벼운 스케줄러(`scripts/scheduler.py`) + `docker compose run --rm`.

- (a)는 잡이 서로 다른 이미지에서 돌아야 해서 cron 컨테이너가 잡마다 이미지를 갖거나 docker를 불러야 한다. (b)는 컨테이너에 docker 소켓을 줘야 하므로 서버 권한을 넘긴다. 선택은 (c): 잡은 그 영역 이미지·볼륨·네트워크로 `docker compose run --rm`(프로필 `jobs`)에서 한 번 돌고 끝난다. 스케줄러는 소켓을 컨테이너에 주지 않는다.
- `tick`(한 번 보고 끝)은 cron이나 systemd timer가 부르고, `loop`는 직접 돌릴 때 쓴다. 상태는 `state/scheduler.json`. 같은 잡이 실행 중이면 건너뛰고(flock), 기한 전에는 아무것도 하지 않는다(멱등).
- 주기는 `config/jobs.yaml`의 `interval_seconds`. **지금은 모두 `null`(미정)이고, null이면 실행하지 않는다.** 이 주기는 사용자 결정이다. 코드에 기본값이 없다.
- `where: gpu-external`(release-gate 승인 평가 워커, synthetic-data, model-lab 파이프라인)은 서빙 서버 밖 GPU 서버의 일이다(D40). Compose에 넣지 않았고 스케줄러도 실행하지 않는다. 후보 수집기는 gate-service 안에서 `GATE_POLL_SECONDS` 주기로 돈다(별도 잡 아님).
- 구성된 잡: `job-ops-feedback`(`python -m ops_feedback.job --config /config/job.yaml`; 설정 파일 형식은 ops-feedback이 알려 줘야 한다 → CR-D05), `backup`.

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
| 이미지 라벨(커밋, 계약, 라이브러리 버전) | 라벨은 있으나 **키 이름이 영역마다 다르다** → CR-D06 |
| 스모크 고정 포트 금지 | 확인. 컨테이너 포트는 Docker 배정을 읽는다. 레지스트리만 사정이 있다(3절) |
| 이름에 deploy 접두어 | 프로젝트 이름 `deploy`/`deploy-e2e-<pid>`로 컨테이너·네트워크·볼륨에 붙는다 |
| 이웃 대신 메모리 구현(가짜 SDK)으로 혼자 시험 | survey-service는 영역이 준 시험용 대역(tests/smoke_fakes)으로 대신(E2E 표시). 그 밖의 이웃 가짜 SDK는 이 구성에서 쓸 곳이 없었다 |

## 11. 시험 자료와 운영 설정의 분리

- `compose.test.yaml`, `test/`, `build/`, `state/`만 시험용이다. `compose.yaml`과 `config/`는 시험 대역을 참조하지 않는다(E2E가 `compose.yaml`에 GPU 잡·시험 대역이 없음을 확인).
- 시험용 어댑터는 `test/fixtures/e2e-test-adapter/`(이름에 test). 시험용 ID에도 `test`를 넣는다(`qs-e2e-test`, `pkg-test-*`, `rel-e2e-test`).
