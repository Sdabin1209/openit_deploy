# 런북: deploy

경로는 모두 이 리포지토리 기준이다. WSL에서는 데몬에 닿는 `docker`(통합)를 쓰고, 안 되면 `docker.exe`를 쓴다(`scripts/lib.sh`가 고른다).

## 1. 처음 설치 (서버)

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
bash scripts/lock-third-party.sh          # gateway, registry, 유틸 이미지를 받아 digest 고정
bash scripts/registry.sh up               # 로컬 레지스트리 (운영 127.0.0.1:5000)
bash scripts/build-images.sh              # 영역 이미지 빌드 (build/ctx 사본에서)
bash scripts/publish-images.sh            # push + digest 잠금 갱신 (locks/images.lock, 이전 것은 locks/history)
bash scripts/gen-secrets.sh               # secrets/ (gitignore) 에 토큰 생성
cp .env.example .env                      # DEPLOY_REGISTRY 등 확인
bash scripts/up.sh deploy                 # 운영 구성. 주의: 아래 "알려진 한계"
```

운영 구성(`compose.yaml`만)의 상태: 모든 영역 사이 호출이 HTTP로 연결되어 5개 서비스가 뜬다. 다만 (1) release-gate는 통과 기준(O11)이 없어 `can_pass:false`(정상)이고, (2) survey-service는 활성 릴리스가 없는 동안 `/readyz` 503 `no_active_release`, (3) 모델 백엔드는 `fake`뿐이다(CR-D08), (4) 승인 평가 실행기가 없어(CR-D10) 설사 정책이 있어도 PASS가 나지 않는다. ops-feedback 잡은 설정 파일(`OPS_JOB_CONFIG`, 사용자 결정 값)이 있어야 돈다.

## 2. 적용과 롤백 (코드 축)

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

시험용 정책으로 판정·릴리스를 지나가는 구성은 `compose.test.yaml`뿐이다(`TEST_POLICY_FILE`, `TEST_RUNNER_DIR`). 운영에는 연결하지 않는다.

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
| docker.exe로 compose 환경 변수가 안 보임 | 윈도 프로그램은 WSL 환경 변수를 받지 못한다 | `--env-file`로 넘긴다(`lib.sh`의 `envfile`) |
