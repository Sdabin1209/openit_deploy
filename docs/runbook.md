# 런북: deploy

경로는 모두 이 리포지토리 기준이다. WSL에서는 데몬에 닿는 `docker`(통합)를 쓰고, 안 되면 `docker.exe`를 쓴다(`scripts/lib.sh`가 고른다).

## 1. 설치: 두 가지 경우

설치 가이드는 [SETUP.md](SETUP.md). 유일한 전제는 **형제 폴더 배치**다: deploy의 상위 폴더에 리포들이 나란히 있고 폴더 이름이 `head/workspace.yaml`과 같다. 루트 폴더 이름과 위치는 자유다(절대 경로는 어디에도 박혀 있지 않다). 확인: `bash scripts/check-relocatable.sh`(정적 검사 + 다른 루트 이름에 clone해 `e2e.sh --fast`).

### (A) 개발·CI 워크스페이스 (소스가 있고 빌드·E2E를 한다)

설치 방법 전체(환경 유형별, 워크스페이스 구성, 첫 실행, 증상별 표)는 **[SETUP.md](SETUP.md)** 한 문서에 있다. 요약: `head/setup.sh`로 형제 리포를 받고 -> `bash scripts/doctor.sh` -> `bash scripts/e2e.sh`(인도 전 필수) / 개발 중에는 `--fast --reuse-build`. 수동 순서: `registry.sh up` -> `build-images.sh` -> `publish-images.sh`(잠금 `locks/images.lock` 갱신) -> `gen-secrets.sh` -> `.env.example`을 `.env`로 복사해 `DEPLOY_REGISTRY` 확인 -> `up.sh deploy`.

### (B) 운영·테스트 서버 (소스 없이 deploy 리포 + 레지스트리의 digest 이미지로 띄우는 것이 장기 형태)

현재 구현 상태(실제로 확인함: `bash scripts/check-standalone.sh`):
- **되는 것**: 형제 리포·`build/`·`.venv`가 없는 deploy 리포 사본 하나와, 잠금(`locks/images.lock`)의 digest 이미지를 가진 레지스트리만으로 `gen-secrets.sh` -> `up.sh`가 운영 구성(compose.yaml만)을 끝까지 띄운다(모든 컨테이너 healthy). `up.sh`/`check-compose.sh`/`compose.yaml`은 워크스페이스나 `build/`를 읽지 않는다(문진 스키마는 survey-service 이미지의 패키지에서 `model-serving-schema`가 꺼내 `schema-data` 볼륨에 둔다). 롤백(`rollback.sh`)과 백업·복구도 deploy 리포 안의 파일만 쓴다.
- **서버에서 해야 하는 일**: `python3`, `docker compose`, 외부 이미지(gateway, registry, 유틸) 받기(`lock-third-party.sh`가 digest를 이미 고정했으면 digest로 pull), `scripts/gen-secrets.sh`로 비밀 생성(`secrets/`), `.env`에 `DEPLOY_REGISTRY` 지정, 로컬 레지스트리 기동(`registry.sh up`, 운영 `127.0.0.1:5000`).
- **아직 안 되는 것(미정)**: (1) 영역 이미지가 서버의 레지스트리에 **들어가는 길**. 목표는 영역 CI가 `publish-image.sh`로 올리는 것([ci.md](ci.md))인데 CI가 서버 레지스트리에 닿는 방법(self-hosted runner, VPN, 터널)과 레지스트리 TLS·인증·도메인이 정해지지 않았다. 지금 레지스트리에 이미지를 채우는 방법은 (A)의 `publish-images.sh`뿐이다. 레지스트리 볼륨을 다른 서버로 옮기는 절차(이관)도 정하지 않았다. (2) 잠금 파일(`locks/images.lock`)을 서버가 받는 방법(deploy 리포 pull인지)이 정해지지 않았다. (3) 운영 도메인·TLS, 사람 계정 인증 방식, 백업 설정(O16)은 사용자 결정 전이다.

### 운영 구성에서 알려진 상태

운영 구성(`compose.yaml`만)에서는 모든 영역 사이 호출이 HTTP로 연결되어 서비스가 뜬다. 다만 (1) 출고는 사람 승인이다(D53): 자동 검사를 통과한 제출은 `AWAITING_APPROVAL`에서 기다리고(`/readyz`의 `awaiting_approval`), 승인자(역할 release-approver)가 `GET /v1/submissions/{id}/review-report`를 보고 `POST /v1/approvals`로 결정한다(게이트웨이 `/admin/`). 승인 전에는 PASS가 없다. (2) survey-service는 활성 릴리스가 없는 동안 `/readyz` 503 `no_active_release`다(정상). (3) 모델 백엔드는 `fake`뿐이다(CR-D08, GPU 변형은 서빙 서버 밖). (4) ops-feedback 잡은 설정 파일(`OPS_JOB_CONFIG`, 사용자 결정 값)이 있어야 돈다. (5) HTTPS와 사람 계정 인증 방식은 미정이다(개발·E2E는 기본 인증).

## 2. 적용과 롤백 (코드 축)

- 이미지 게시(D24): 영역 CI가 `scripts/publish-image.sh <서비스> <이미지> --registry <주소>`로 올리고 digest를 잠금에 기록한다. 계약과 실패 시 동작은 [ci.md](ci.md). 시험: `bash scripts/test-publish.sh`.

- 새 버전 적용: 영역 이미지를 빌드·게시 → `publish-images.sh <영역>`이 잠금을 갱신(이전 것은 `locks/history/`) → `up.sh deploy`(바뀐 서비스만 교체). 잠금 파일을 커밋한다.
- 롤백: `bash scripts/rollback.sh [--to <잠금 파일>] [--no-apply] [프로젝트]`. 기본은 history에서 현재와 다른 가장 최근 잠금. 되돌린 뒤 `/readyz`를 본다. 롤백을 되돌리려면 같은 명령을 한 번 더(현재 잠금도 history에 남는다).
- 내용 축(릴리스 활성 포인터) 되돌리기는 게이트의 몫이다(`POST /v1/rollback`). deploy가 하지 않는다.
- 지원하지 않는 계약 버전의 묶음 거부는 서비스가 한다. survey-service는 `/readyz`의 `release_loader.rejections`로 낸다.

## 3. 상태 보기

```
docker compose -p deploy ps                                     # healthy 여부
docker compose -p deploy logs -f survey-service                 # 로그는 표준 출력
curl -s http://127.0.0.1:$(docker port deploy-gateway-1 8080/tcp | sed 's/.*://')/healthz
```

각 서비스의 `/readyz` 해석은 영역 런북을 본다(survey: `problems`, gate: `can_pass`·`judging`).

## 4. 백업과 복구

백업 설정이 정해지기 전에는 백업을 돌릴 수 없다. 이것은 의도다(O16).

```
cp config/backup.env.example config/backup.env    # BACKUP_DIR, BACKUP_RETENTION_DAYS 를 사용자 결정대로 적는다
bash scripts/backup.sh [저장소...]                  # survey-data qa-data ops-data gate-data. 서비스가 떠 있어도 된다
# 복구: 해당 서비스를 먼저 멈춘다
docker compose -p deploy stop survey-service        # 저장소를 쓰는 서비스
bash scripts/restore.sh qa-data <BACKUP_DIR>/qa-data/<시각> --yes
bash scripts/up.sh deploy
```

- 설정이 없거나 비어 있으면 `backup.sh`는 종료 코드 2로 거부한다.
- 복구는 해시 검증 후 볼륨을 비우고 채운다. 게이트는 `registry.sqlite3`와 `releases/`가 한 쌍이므로 같은 스냅샷에서 함께 복구한다(스크립트가 그렇게 한다).
- 게이트 INTEGRITY_ERROR(릴리스 파일 변조): 해당 릴리스를 활성화하지 말고, 활성이면 롤백 요청 후 이 절차로 복구(게이트 런북).
- 복구 시험: `scripts/e2e.sh`가 실제로 지웠다 복구하며 검증한다.

## 5. 주기 잡

```
.venv/bin/python scripts/scheduler.py --config config/jobs.yaml --state state/scheduler.json status
.venv/bin/python scripts/scheduler.py --config config/jobs.yaml --state state/scheduler.json tick     # cron/systemd timer 가 1분마다 부른다
```

- cron 예: `* * * * * cd /srv/deploy && .venv/bin/python scripts/scheduler.py --config config/jobs.yaml --state state/scheduler.json tick >> state/scheduler.log 2>&1`
- `interval_seconds: null`은 "주기 미정"이라 실행하지 않는다. 주기는 사용자가 정한 뒤 `config/jobs.yaml`에 적는다.
- 잡 하나를 지금 실행: `bash scripts/run-job.sh job-ops-feedback`(설정 파일 `OPS_JOB_CONFIG`가 있어야 한다. 없으면 거부).
- `gpu-external` 잡은 GPU 서버에서 돈다(D40). 서빙 서버의 Compose·스케줄러가 실행하지 않는다.

## 6. 시험

- **인도 전에는 옵션 없는 전체 모드(`bash scripts/e2e.sh --reuse-build`)가 필수다.** 스케줄러, 백업·복구, 코드 축 롤백까지 돌고 약 4~5분(이미지 빌드 제외)이 걸린다.
- 개발 중에는 `--fast`(예: `bash scripts/e2e.sh --fast --reuse-build`)를 쓴다. 단계 1~8과 단계 9 앞부분(compose 기동 검사)만 돌고 스케줄러, 백업·복구, 롤백은 생략한다. 요약에 생략한 구간과 "전체 합격 아님"이 표시되고, 종료 코드는 돌린 검사 기준이다.

E2E의 승인자는 시험용 release-approver 토큰을 쓰는 스크립트다(`secrets/tokens/gate-write-release-approver`). 운영에서는 승인자에게만 이 역할의 토큰을 준다. 공개 API 토큰: `secrets/tokens/survey-api-kiosk`(프론트), `survey-api-staff`(직원 콘솔, 내부 경로).

```
bash scripts/e2e.sh [--keep] [--keep-images] [--reuse-build]
```

임시 프로젝트 `deploy-e2e-<pid>`와 임시 레지스트리를 만들고 끝나면 지운다(`--keep`은 남김). 끝의 요약에 단계별 REAL / TEST-SUB / BLOCKED가 나온다. 종료 코드 0은 "실행한 검사가 모두 통과"이지 시나리오 전체 합격이 아니다(BLOCKED 단계가 있는 동안).

## 7. 비밀 값

`scripts/gen-secrets.sh`가 `secrets/`에 만든다(없는 것만). 이미지·리포지토리에 넣지 않는다. 회전: 해당 파일을 지우고 다시 만든 뒤 소유 서비스와 그 클라이언트를 재시작한다. 서비스는 자기 `env_file`만 받는다.

## 8. 흔한 문제

| 증상 | 확인 | 조치 |
| --- | --- | --- |
| `push` 가 connection refused (Docker Desktop) | 데몬이 VM 안이라 `127.0.0.1` 게시 포트에 못 닿는다 | 시험에서는 `REGISTRY_HOST_BIND=0.0.0.0`, 지정 포트. 리눅스 서버는 해당 없음 |
| 새 잠금을 적용해도 컨테이너가 안 바뀜 | 셸에 같은 이름의 `*_DIGEST` 변수가 남아 있나 | `dc`가 지우지만 compose를 직접 부를 때는 `env -u`로 지운다 |
| 컨테이너가 `operation not permitted`로 안 뜸 | `cap_drop: ALL`과 파일 권한이 있는 바이너리 | 필요한 capability만 `cap_add` (gateway의 `NET_BIND_SERVICE`) |
| SQLite `unable to open database file` (백업·읽기) | WAL 모드 DB를 읽기 전용 마운트로 연 것 | 백업 도구처럼 쓰기 가능 마운트로 읽기 전용 연결을 쓰고 만든 `-wal/-shm`을 지운다 |
| 빌드가 `error getting credentials … docker-credential-desktop.exe: exec format error` 로 실패 | interop이 꺼진 WSL에서 `~/.docker/config.json`의 `credsStore`가 윈도 도우미(desktop.exe)를 가리킨다 | `scripts/lib.sh`가 자동으로 `state/docker-config`(빈 설정, gitignore)로 `DOCKER_CONFIG`를 돌린다(안내 한 줄). 사용자 설정은 건드리지 않고 내용을 출력하지도 않는다. 정상 도우미면 건드리지 않는다 |
| docker.exe로 compose 환경 변수가 안 보임 | 윈도 프로그램은 WSL 환경 변수를 받지 못한다 | `--env-file`로 넘긴다(`lib.sh`의 `envfile`) |
