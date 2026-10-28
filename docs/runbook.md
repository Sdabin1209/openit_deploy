# 런북: deploy

경로는 모두 이 리포지토리 기준이다. 스크립트는 표준 `docker` CLI와 설정된 데몬(`DOCKER_HOST`/context) 하나의 경로만 쓴다(다른 실행 파일은 `DOCKER` 변수). 환경 문제는 코드가 숨기지 않고 `scripts/doctor.sh`가 진단한다([SETUP.md](SETUP.md)).

## 1. 설치: 두 가지 경우

설치 가이드는 [SETUP.md](SETUP.md). 띄우고 화면을 눌러 보는 방법은 [RUN.md](RUN.md). 유일한 전제는 **형제 폴더 배치**다: deploy의 상위 폴더에 리포들이 나란히 있고 폴더 이름이 `head/workspace.yaml`과 같다. 루트 폴더 이름과 위치는 자유다(절대 경로는 어디에도 박혀 있지 않다). 확인: `bash scripts/check-relocatable.sh`(정적 검사 + 다른 루트 이름에 clone해 `e2e.sh --fast`).

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

- 이름 구분: `publish-image.sh`(단수) = 영역 CI가 이미지 하나를 올릴 때, `publish-images.sh`(복수) = 로컬에서 `build-images.sh`로 만든 이미지 전체를 올릴 때.
- 이미지 게시(D24): 영역 CI가 `scripts/publish-image.sh <서비스> <이미지> --registry <주소>`로 올리고 digest를 잠금에 기록한다. 계약과 실패 시 동작은 [ci.md](ci.md). 시험: `bash scripts/test-publish.sh`.

- **적용 전에 백업한다(4-5절)**: `bash scripts/backup-all.sh`가 성공(종료 코드 0)한 것을 확인한 뒤에만 적용한다. DB 마이그레이션이 있는 버전은 롤백이 이미지만 되돌린다는 점(4-5절)을 먼저 읽는다.
- 새 버전 적용: 영역 이미지를 빌드·게시 → `publish-images.sh <영역>`이 잠금을 갱신(이전 것은 `locks/history/`) → `up.sh deploy`(바뀐 서비스만 교체). 잠금 파일을 커밋한다.
- 롤백: `bash scripts/rollback.sh [--to <잠금 파일>] [--no-apply] [프로젝트]`. 기본은 history에서 현재와 다른 가장 최근 잠금. 되돌린 뒤 `/readyz`를 본다. 롤백을 되돌리려면 같은 명령을 한 번 더(현재 잠금도 history에 남는다).
- 내용 축(릴리스 활성 포인터) 되돌리기는 게이트의 몫이다(`POST /v1/rollback`). deploy가 하지 않는다.
- 지원하지 않는 계약 버전의 묶음 거부는 서비스가 한다. survey-service는 `/readyz`의 `release_loader.rejections`로 낸다.

## 2-1. 화면을 직접 눌러 보는 데모

`bash scripts/demo.sh up`(승인을 사람이 해 보려면 `--stop-before-approval`, 이후 `demo.sh activate`), `status`, `down`, `reset`. 상시 구성과 따로 `deploy-demo` 프로젝트로 뜬다. 자세한 안내와 한계는 [SETUP.md](SETUP.md) "데모" 절.

## 3. 상태 보기와 내리기

수명주기는 한 세트다: 올리기 `up.sh` / 상태 `status.sh` / 내리기 `down.sh`. `dc` 는 `scripts/lib.sh` 안의 셸 함수라 터미널에서 직접 칠 수 없다. 아래 스크립트를 쓴다.

```
bash scripts/status.sh                          # deploy, deploy-demo, deploy-registry 의 컨테이너·gateway 주소·/readyz 요약
bash scripts/down.sh deploy --stop              # 멈추기만(이어 가기: docker compose -p deploy start)
bash scripts/down.sh deploy                     # 컨테이너·네트워크 제거, 데이터 볼륨 유지(= --remove)
bash scripts/down.sh deploy --purge             # 볼륨까지 삭제(되돌릴 수 없음): 목록을 보이고 프로젝트 이름을 쳐야 진행
bash scripts/down.sh deploy --registry          # 로컬 레지스트리도 내림(이미지는 볼륨에 남음)
```

허용 프로젝트 이름은 `deploy`·`deploy-*` 뿐이다. 비대화형 삭제는 `--purge --yes-purge-<프로젝트>` 를 명시해야 한다. 직접 확인하려면:

```
docker compose -p deploy ps                                     # healthy 여부
docker compose -p deploy logs -f survey-service                 # 로그는 표준 출력
curl -s http://127.0.0.1:$(docker port deploy-gateway-1 8080/tcp | sed 's/.*://')/healthz
```

컨테이너가 **실제로** 비root·읽기 전용·cap_drop ALL·자원 한도를 갖는지는 `bash scripts/check-containers.sh [프로젝트...]`(기본 deploy, deploy-registry)가 `docker inspect`로 읽어 FAIL/WARN으로 알린다(읽기 전용). compose 파일에 적은 것이 아니라 떠 있는 컨테이너를 본다. 자체 시험 `bash scripts/test-check-containers.sh`. 자원 한도 변수는 `config/resource-limits.env.example`(값은 측정 안 함, [adr/0023-compose-resource-limits.md](adr/0023-compose-resource-limits.md)).

각 서비스의 `/readyz` 해석은 영역 런북을 본다(survey: `problems`, gate: `can_pass`·`judging`).

## 4. 백업과 복구 (PostgreSQL 기준, restic)

저장소는 PostgreSQL 한 서버(5개 데이터베이스: survey, qa, ops_log, ops_failure, gate)와 파일 볼륨(gate-data 번들, models-data 모델 패키지, datasets-data, gateway-data, 레지스트리 볼륨)이다. 백업은 **restic 저장소 하나**(`$BACKUP_DIR/restic`)에 둔다. 근거와 한계: [adr/0038-restic-backup.md](adr/0038-restic-backup.md)(옛 [0020](adr/0020-backup-tool-and-encryption.md)을 대체).

### 4-1. 설정과 규칙 (백업 없이 운영하지 않는다, D88 U6)

```
cp config/backup.env.example config/backup.env    # BACKUP_DIR(서버 밖), BACKUP_RETENTION_DAYS(예시 14), BACKUP_PASSWORD_FILE(restic 저장소 암호 파일) 를 적는다
bash scripts/backup-check.sh                       # 읽기 전용 점검. 문제가 있으면 CRIT 와 종료 코드 2
```

- 설정이 없거나 불완전하면 `backup.sh`, `pg-backup.sh`, `backup-all.sh`가 "CRIT:" 한 줄과 종료 코드 2로 실패한다. systemd가 실패를 남기고 `job-metrics.sh`가 `openit_job_last_exit_status`로 내보내 `JobFailed` 경보(critical)가 된다. `doctor.sh --up --backup`과 운영 프로젝트(`deploy`)의 `up.sh`는 기동 전에 같은 점검을 하고 FAIL로 막는다. 옛 키(`BACKUP_ENCRYPT_RECIPIENTS` 등)가 남아 있어도 거부한다.
- 암호화는 restic이 한다(AES-256, 인증된 암호화, 내용 해시로 무결성 검증). **저장소 암호가 서버에 있어야 자동 백업이 돈다**(옛 공개키 방식과 다르다: 서버가 뚫리면 백업도 읽힌다는 점을 감수한다, ADR 0038). 암호 파일은 모드 400/600, `BACKUP_DIR` 밖이어야 한다. **암호를 잃으면 모든 백업을 영영 못 푼다.** 서버 밖 2곳 이상에 따로 보관한다.
- 보관 14일(설정). 저장소(host)마다 가장 최근 하나는 기간이 지나도 남는다(`restic forget --keep-within --keep-last 1 --prune`).

### 4-2. 무엇이 어떻게 백업되나

| 대상 | 방법 | restic 스냅샷 | 같은 시점 여부 |
|---|---|---|---|
| 5개 데이터베이스 | `pg-backup.sh`: 병렬로 동시에 시작한 `pg_dump -Fc`를 `restic backup --stdin`으로 바로 저장(평문 덤프가 디스크에 쓰이지 않는다) | host `pg-<db>`, 파일 `<db>.dump`, 태그 `set-<UTC 시각>`·`pg-<서버 버전>` | 각 데이터베이스 안에서는 단일 스냅샷. **데이터베이스 사이는 같은 시점이 아니다**: 덤프 시작 시각 차이가 덤프 하나의 시간 이하이고, 같은 실행의 스냅샷은 같은 `set-` 태그다 |
| gate-data(번들), models-data(모델 패키지), datasets-data, gateway-data(내부 CA), registry-data(레지스트리 이미지, 프로젝트 `deploy-registry`) | `backup.sh`: 볼륨을 읽기 전용으로 붙여 `restic backup` | host `<저장소>`, 경로 `/data` | 볼륨 단위 |
| secrets/ | `backup-secrets.sh` | host `secrets` | 4-6절 |

`backup-all.sh`(systemd의 backup 잡, 매일)가 셋을 모두 돌린다. 레지스트리 볼륨이 이 서버에 없으면 건너뛴다고 출력한다. 덤프가 중간에 실패하면 이 실행이 만든 스냅샷을 모두 지우고 실패(종료 코드 1)한다.

### 4-3. 복구 절차

1. 서비스 멈추기: 복구할 데이터베이스를 쓰는 서비스를 멈춘다(`docker compose -p deploy stop <서비스>`). 다른 접속이 있으면 `pg-restore.sh`가 거부한다.
2. 볼륨을 잃은 경우: `docker compose -p deploy up -d --wait postgres`. 초기화 스크립트가 빈 데이터베이스와 계정을 만든다.
3. 새 서버라면 저장소와 암호 파일을 먼저 놓는다(`BACKUP_DIR`에 `restic/` 폴더, `BACKUP_PASSWORD_FILE`에 서버 밖 보관본의 암호). 어떤 스냅샷이 있는지: `docker run --rm -v $BACKUP_DIR:/backup -v $BACKUP_PASSWORD_FILE:/pw:ro -e RESTIC_REPOSITORY=/backup/restic -e RESTIC_PASSWORD_FILE=/pw <RESTIC_IMAGE> snapshots`(RESTIC_IMAGE 는 `locks/images.lock`).
4. `bash scripts/pg-restore.sh <db> latest --yes`(또는 스냅샷 ID). 파일 저장소는 `bash scripts/restore.sh <저장소> latest --yes`(서비스 정지 필요, 볼륨을 비우고 `--verify`로 내용 해시를 확인하며 복원, 소유자·모드는 백업 때 값 그대로). 데이터베이스 5개는 가능하면 **같은 백업 세트(같은 `set-` 태그)**의 스냅샷 ID로 복구한다.
5. 복호 단계는 없다(restic이 저장소 암호로 직접 읽는다). 평문 파일이 디스크에 남지 않는다.
6. `bash scripts/up.sh deploy`, 그다음 gateway `/readyz`와 `bash scripts/check-monitoring-live.sh deploy`(감시 스택이 떠 있을 때).
7. 게이트 INTEGRITY_ERROR(릴리스 파일 변조): 해당 릴리스를 활성화하지 말고, 활성이면 롤백 요청 후 이 절차로 gate 데이터베이스와 gate-data를 같은 세트로 복구한다(게이트 런북).

### 4-4. 복원 시험

- 자동(주 1회, systemd 잡 `backup-restore-test`): `bash scripts/backup-restore-test.sh`. 임시 암호·임시 저장소로 지금 운영 데이터를 백업하고, `restic dump`로 임시 데이터베이스(`rt_*`)에 복원한 뒤 원본과 행 지문(스키마·행 집합 해시·행 수)을 대조한다. 실제 저장소는 데이터베이스마다 스냅샷이 있는지 보고 `restic check --read-data-subset=5%`로 구조와 데이터 일부를 다시 읽는다(전체 읽기는 시험 전용 `RESTIC_CHECK_FULL=1`).
- 사람(분기마다 1회 권장, 근거 없음: 시작값): 서버 밖 보관본의 암호로 최신 스냅샷을 시험 서버나 임시 프로젝트에 4-3 절차대로 복구하고 서비스가 뜨는지 본다. 암호를 잃지 않았다는 유일한 확인이다.
- 전체: `scripts/e2e.sh`가 지웠다 복구하는 왕복을 한다(시험용 임시 암호). 서버 단독 자체 시험: `bash scripts/test-backup.sh`(암호화·복원·손상 감지·보관 기간), `bash scripts/test-backup-secrets.sh`, `bash scripts/test-postgres.sh`(모두 Docker 필요).

### 4-5. 업그레이드·롤백과 백업

- **업그레이드 전에 백업한다**: `bash scripts/backup-all.sh`를 먼저 돌려 성공(종료 코드 0)을 확인하고 `up.sh`로 새 이미지를 적용한다. 실패하면 적용하지 않는다.
- `rollback.sh`는 이미지 digest만 되돌린다(DB는 되돌리지 않는다). 새 이미지가 DB 스키마를 올렸다면 이전 이미지가 그 스키마를 읽는지는 **각 영역의 마이그레이션 정책에 달려 있다. deploy는 이를 확인하지 못했다(확인 못 함)**. 안전한 순서: (1) 업그레이드 전 백업, (2) 문제가 있으면 이미지를 되돌리고, 스키마가 호환되지 않으면 (3) 4-3 절차로 DB를 업그레이드 전 백업에서 복구한다.
- PostgreSQL 주 버전(16 고정)은 덤프·복원 방식으로만 올린다(새 버전 서버에 복원). 볼륨을 새 주 버전 이미지에 그대로 붙이지 않는다.

### 4-6. secrets/ 백업과 복구

> **위험: 저장소 암호를 잃으면 이 백업(DB 백업 포함)은 영영 풀 수 없다.** 암호는 서버 밖 서로 다른 안전한 곳 2곳 이상(예: 금고의 오프라인 매체 + 담당자 비밀번호 관리자)에 둔다. 암호 파일이 `secrets/` 안에 있으면 그 파일은 스냅샷에서 뺀다.

- `bash scripts/backup-secrets.sh`(backup 잡이 `backup-all.sh`로 매일 함께 돌린다): `secrets/` 전체를 같은 restic 저장소에 `--host secrets`로 저장한다. 보관은 `BACKUP_RETENTION_DAYS` 하나다(옛 `BACKUP_SECRETS_KEEP`·`BACKUP_SECRETS_DIR`은 없어졌다. 접근 권한을 나누고 싶으면 별도 `BACKUP_DIR`의 별도 설정으로 한 번 더 돌린다).
- 복구(서버를 새로 세울 때): (1) 암호 파일과 `restic/` 저장소를 놓는다(4-3의 3). (2) `bash scripts/restore-secrets.sh latest secrets --yes`(비어 있지 않은 폴더는 거부, restic이 내용 해시를 검증, 모드는 `lib.sh secret_mode`대로 바로잡고 값은 건드리지 않는다). (3) `bash scripts/check-secret-perms.sh secrets`.
- 이 복구 시험은 `bash scripts/test-backup-secrets.sh`(secrets/를 통째로 지우고 되살려 `deid-salt`가 같은 값으로 돌아오는지 확인)가 한다. 실제 암호로 푸는 시험은 4-4절의 사람 시험에 secrets 복원도 포함한다.
- 한계: secrets/가 백업된 시점 이후에 회전한 토큰은 사라진다(회전 뒤 즉시 `backup-secrets.sh`를 한 번 돌린다). 암호 하나로 모든 백업이 풀리므로 암호는 그만큼 중요하다.

## 5. 주기 잡

주기 실행은 systemd timer가 한다(ADR 0036). 잡마다 `config/systemd/openit-<잡>.service|timer`가 있다(예시이며 이 리포는 설치하지 않는다).

```
sudo cp config/systemd/openit-*.service config/systemd/openit-*.timer /etc/systemd/system/   # 경로 /srv/deploy 와 User=openit 을 서버에 맞게 고친 뒤
sudo systemctl daemon-reload && sudo systemctl enable --now 'openit-*.timer'
systemctl list-timers 'openit-*'                       # 다음 실행 시각
journalctl -u openit-release-gate-collector.service -n 30   # 마지막 결과와 종료 코드
```

- 주기: release-gate-collector 600초, ops-feedback-job 3600초, 백업·정리 잡 86400초는 사용자 결정(D85, 표준 주기). backup-restore-test 604800초는 시작값(근거 없음). 값은 각 `.timer`의 `OnUnitActiveSec`에 있고 출처는 ADR 0036. backup 잡은 `config/backup.env`가 없으면 거부한다.
- 같은 잡이 실행 중이면 oneshot 서비스라 timer가 다시 시작하지 않는다. 한 번 지금 실행: `sudo systemctl start openit-backup.service`.
- 잡 하나를 지금 실행: `bash scripts/run-job.sh job-ops-feedback`(설정 파일 `OPS_JOB_CONFIG`가 있어야 한다. 없으면 거부).
- `gpu-external` 잡은 GPU 서버에서 돈다(D40). 서빙 서버의 Compose·스케줄러가 실행하지 않는다.

### 5-0. synthetic-data 잡의 게시 대상 설정 (dataset-store, D100)

잡(import·run)은 compose 밖(호스트 또는 GPU 호스트)에서 돈다. 게시 대상은 dataset-store(I2 HTTP)다. 설정 예(`output.store`만, 나머지는 영역 README):

```json
"output": {"work_dir": "<임시 경로>", "store": {"kind": "http", "base_url": "http://<dataset-store 주소>:<포트>", "timeout": 60}}
```

쓰기 토큰은 설정이 아니라 환경 변수 `DATASET_STORE_WRITE_TOKEN_FILE`(단수, 잡 쪽)에 파일 경로로 준다: `secrets/tokens/dataset-store-write-synthetic-data`. 서버 쪽 `DATASET_STORE_WRITE_TOKENS_FILE`(복수, 역할=토큰 목록)과 이름이 다르다(synthetic-data ADR 0013). 요구: 잡 실행 환경의 boundary-contracts 가 v2.1.0 이상. 닿는 경로: `datasets` 네트워크는 internal 이라 호스트 밖에서 닿지 않는다. 시험 구성(`compose.test.yaml`)은 `127.0.0.1` 임의 포트를 연다. 운영에서 GPU 호스트가 닿는 방법은 정하지 않았다(ADR 0032 "검토한 대안"). E2E 단계 7d 가 호스트에서 잡을 이 설정으로 돌려 확인한다.

## 5-1. 상태 감시 (FAULT_POLICY 13·14, ADR 0037)

Prometheus + blackbox_exporter + json_exporter + node_exporter + Alertmanager(`compose.monitoring.yaml`, 설정 `config/prometheus/`)가 이 서버의 상태를 본다. 서버 전체가 죽으면 이 스택도 죽으므로 서버 밖 감시(9절)는 따로 둔다.

```
COMPOSE_EXTRA=compose.monitoring.yaml bash scripts/up.sh deploy     # 감시 스택까지 올린다
bash scripts/check-monitoring-live.sh deploy                          # 탐침·지표가 실제로 읽히는지 확인(Prometheus API)
docker compose -p deploy port prometheus 9090                         # 화면/API 는 127.0.0.1 에만 열린다(Docker 배정 포트)
```

| 대상 | 읽는 곳 | 경보(규칙 `config/prometheus/rules/openit.yml`) |
|---|---|---|
| 디스크 사용률 | node_exporter filesystem | 80% 이상 DiskUsageWarning, 90% 이상 DiskUsageCritical |
| 살아 있음·준비됨 | blackbox: gateway `/healthz`, release-gate·model-serving `/readyz` | 2xx 가 아니거나 닿지 못함이 2분 지속되면 ProbeDown(critical) |
| 서버 밖 대상 | `config/prometheus/external-targets.yml`(공개 주소가 정해지면 채운다) | 같은 ProbeDown |
| release-gate 판정 루프 | json_exporter 가 `/readyz` 의 `judging_loop` 를 읽는다 | 연속 실패 1~2회 warning, 3회 이상 critical, `upstream_auth_failed` critical, 마지막 실행 900초 초과 warning |
| 주기 잡 결과 | systemd 서비스의 `ExecStopPost=scripts/job-metrics.sh`가 node_exporter textfile(`state/metrics/*.prom`)로 남긴다 | 마지막 실행 실패 JobFailed(critical), 마지막 성공이 주기의 2배+60초를 넘으면 JobStale(critical). 백업 잡이면 '백업이 2일 넘게 안 됐다' |

옛 `check-health.sh`와의 차이(알려진 것): (1) 백업 파일을 직접 열어 나이를 보지 않고 `backup` 잡의 마지막 성공 시각으로 본다. (2) 백업 암호화 설정 경고(평문 허용)는 없다: restic 저장소(3단계)는 항상 암호화다. (3) 판정 루프가 "한 번도 돌지 않았다"(`last_run_at` null)는 지표가 없어 경보가 없다. (4) gateway HTTPS 탐침은 서버 밖 감시의 몫이다. (5) '시작했지만 끝나지 않음 1시간'은 `TimeoutStartSec=3600`이 서비스를 죽이고 JobFailed 가 된다.

경보 규칙 시험: `bash scripts/test-monitoring.sh`(promtool check/test rules + 변이 시험 + Docker 로 가짜 서비스에 실패를 주입해 경보가 firing 되는지). 정적만: `--static`. 한계값은 옛 점검 값 그대로이고 `for:` 값은 시작값이다(측정 안 함, ADR 0037).

**알림 수단 연결 지점(미정, 만들지 않았다).** 경보를 "누구에게 어떻게" 보낼지는 사용자 결정이다. 지금 `config/prometheus/alertmanager.yml`에는 수신자가 없어 경보는 Alertmanager 화면/API에서만 보인다. 수단이 정해지면 그 파일의 `receivers`에 넣는다(비밀은 파일로).

## 5-2. 자동 롤백 요청(D3): 운영 잡 설정에 `rollback`·`gate_service`가 없는 이유

의도된 것이다. 근거: (1) `config/ops-feedback-job.yaml` 머리말이 "rollback과 retention 값은 사용자 결정 전이라 비워 둔다"고 쓰고 `rollback: null`로 둔다. (2) ops-feedback `docs/runbook.md`는 `rollback.*`을 사용자가 정할 기준 수치로 분류하고, `rollback` 항목이 없으면 롤백 평가를 하지 않는다. (3) 연결 쪽은 이미 준비돼 있다: compose의 `job-ops-feedback`은 `OPS_GATE_READ_TOKEN_FILE`·`OPS_GATE_WRITE_TOKEN_FILE`(역할 ops-feedback의 게이트 읽기·쓰기 토큰)을 받고, E2E 단계 8이 같은 쓰기 토큰으로 `request_rollback`을 HTTP로 부른다. 없는 것은 기준 수치와 `gate_service` 팩토리 선언뿐이다. 이 문서는 값을 채우지 않는다(자동 롤백 기준은 사용자 결정).

기준이 정해지면 `config/ops-feedback-job.yaml`의 `rollback: null`을 아래로 바꾸고 `gate_service`를 더한다. **숫자는 자리표시자이며 권고가 아니다.**

```yaml
rollback:
  window_hours: <사용자 결정>
  min_turns: <사용자 결정>
  max_failure_rate: <사용자 결정>
  counted_review_statuses: [PENDING, CONFIRMED]   # 예시(ops-feedback config/job.example.yaml)
  requested_by_role: ops-feedback
  auto_submit: false        # 처음에는 false: 요청을 aux(kind rollback_request)에만 기록하고 게이트에 보내지 않는다
gate_service:               # auto_submit: true 일 때 I5 request_rollback
  factory: "boundary_contracts.clients:HttpGateService"
  args: {base_url: "http://release-gate:8080", token: {secret: OPS_GATE_WRITE_TOKEN}}
```

확인 방법(이 단계들은 아직 실행하지 않았다): (1) `auto_submit: false`로 `bash scripts/run-job.sh job-ops-feedback`를 돌리고 출력 JSON 한 줄(종료 코드 1이면 `errors`)과 ops-feedback 영역 runbook의 `rollback_request` 기록을 본다. (2) 시험 프로젝트(`scripts/demo.sh` 또는 `e2e.sh --keep`)에서 `auto_submit: true`로 바꿔 게이트의 영수증(`rollback_receipt`)과 `GET /v1/active-pointer`를 본다. 운영에서 먼저 켜지 않는다. 시험 프로젝트는 `OPS_JOB_CONFIG`로 별도 파일을 가리킨다(`test/ops-job/`). 값 `{secret: 이름}`이 이 이미지 버전에서 받아들여지는지는 ops-feedback 예시 파일의 문구를 따랐을 뿐 deploy에서 실행해 보지 않았다.

## 6. 시험

- **인도 전에는 옵션 없는 전체 모드(`bash scripts/e2e.sh --reuse-build`)가 필수다.** 스케줄러, 백업·복구, 코드 축 롤백까지 돌고 약 4~5분(이미지 빌드 제외)이 걸린다.
- 개발 중에는 `--fast`(예: `bash scripts/e2e.sh --fast --reuse-build`)를 쓴다. 단계 1~8과 단계 9 앞부분(compose 기동 검사)만 돌고 스케줄러, 백업·복구, 롤백은 생략한다. 요약에 생략한 구간과 "전체 합격 아님"이 표시되고, 종료 코드는 돌린 검사 기준이다.

E2E의 승인자는 시험용 release-approver 토큰을 쓰는 스크립트다(`secrets/tokens/gate-write-release-approver`). 운영에서는 승인자에게만 이 역할의 토큰을 준다. 공개 API 토큰: `secrets/tokens/survey-api-kiosk`(프론트), `survey-api-staff`(직원 콘솔, 내부 경로).

```
bash scripts/e2e.sh [--keep] [--keep-images] [--reuse-build]
```

임시 프로젝트 `deploy-e2e-<pid>`와 임시 레지스트리를 만들고 끝나면 지운다(`--keep`은 남김). 끝의 요약에 단계별 REAL / TEST-SUB / BLOCKED가 나온다. 종료 코드 0은 "실행한 검사가 모두 통과"이지 시나리오 전체 합격이 아니다(BLOCKED 단계가 있는 동안).

## 7. 비밀 값

`scripts/gen-secrets.sh`가 `secrets/`에 만든다(없는 것만). 이미지·리포지토리에 넣지 않는다. 서비스는 compose `secrets:`로 자기 파일만 `/run/secrets`에 받는다(D84, [RUN.md](RUN.md) "비밀 파일").

**권한.** 폴더 700. 호스트 전용 파일(계정 암호·해시, 기기 토큰 원본)은 600, 컨테이너가 읽는 파일은 644(폴더 700 안; compose가 파일 secrets의 모드를 바꾸지 못하기 때문, [adr/0022-secret-file-permissions.md](adr/0022-secret-file-permissions.md)). `gen-secrets.sh`는 실행할 때마다 모드를 바로잡고 `scripts/check-secret-perms.sh`(doctor --up)가 어긋남을 FAIL로 알린다.

**평문 암호 최소화.** 게이트웨이 계정은 bcrypt 해시만 Caddy 파일에 들어간다. 평문 암호 파일(`account-<id>-password`, 600)은 해시를 만들 때만 생기고 E2E 시험 계정이 쓴다. 운영에서는 계정 암호를 사람에게 전달한 뒤 `bash scripts/gen-secrets.sh --drop-plaintext`로 평문 파일을 지운다(해시가 남아 로그인은 그대로). 지운 평문은 되살리지 않는다. 운영 계정은 OIDC 도입 전까지 아래 회전 절차로 관리한다.

**회전 절차.**
1. 계정 암호 한 개: 사람이 터미널에서 `bash scripts/rotate-account.sh <계정 ID> --apply`. 새 암호가 표준 출력에 한 번 나온다(해시만 저장). 해당 직원에게 안전한 경로로 전달하고 터미널 기록을 지운다. `--apply`는 게이트웨이를 다시 시작한다.
2. 서비스 토큰·DB 암호 한 개: 해당 파일을 지우고 `gen-secrets.sh`를 다시 실행(목록 값 파일도 새 값으로 다시 쓴다). DB 암호는 `bash scripts/pg-roles.sh sync`로 서버의 계정 암호를 맞춘다. 그다음 소유 서비스와 그 클라이언트를 다시 만든다(`up.sh deploy`).
3. 기기 토큰: `bash scripts/kiosk-add-device.sh remove <ID> --apply` 후 `add <ID> --apply`, 새 토큰을 기기에 한 번 전한다.
4. 노출이 의심되면 전체 회전: `secrets/tokens/`를 안전한 곳에 옮겨 두고(분석용) 새로 `gen-secrets.sh`, `pg-roles.sh sync`, `up.sh deploy --force-recreate`, 모든 계정 암호 재전달, 기기 토큰 재전달. 노출 시각 이후의 접근 로그(Caddy json 로그)를 확인한다.
5. 토큰에는 만료가 없다. 회전은 수동이며 주기는 정하지 않았다(근거 없음, 사용자 결정 대기: 이 저장소의 OPEN_GAPS).

한계: 해시 생성 때 암호는 `docker run -i`의 표준 입력으로 전달되어 프로세스 목록(인자)에는 보이지 않는다(`scripts/test-hash-password-argv.sh`로 확인). 새 암호는 `rotate-account.sh`의 표준 출력에 한 번 나온다. docker 그룹 사용자는 어차피 모든 비밀에 닿는다(docker 그룹은 root와 같다).

## 8. 흔한 문제

| 증상 | 확인 | 조치 |
| --- | --- | --- |
| `push` 가 connection refused (Docker Desktop) | 데몬이 VM 안이라 `127.0.0.1` 게시 포트에 못 닿는다 | 시험에서는 `REGISTRY_HOST_BIND=0.0.0.0`, 지정 포트. 리눅스 서버는 해당 없음 |
| 새 잠금을 적용해도 컨테이너가 안 바뀜 | 셸에 같은 이름의 `*_DIGEST` 변수가 남아 있나 | `dc`가 지우지만 compose를 직접 부를 때는 `env -u`로 지운다 |
| 컨테이너가 `operation not permitted`로 안 뜸 | `cap_drop: ALL`과 파일 권한이 있는 바이너리 | 필요한 capability만 `cap_add` (gateway의 `NET_BIND_SERVICE`) |
| `pg_dump`/`pg_restore` 실패, 접속 거부 | postgres 컨테이너가 떠 있나(`docker compose -p deploy ps postgres`), 복구 대상 DB에 다른 접속이 있나 | 서비스를 멈추고 다시. 복구는 4-3절. (SQLite는 개발·시험용이며 운영 저장소가 아니다: adr/0021-postgres-single-container-sqlite-dev-only.md) |
| 빌드가 `error getting credentials … docker-credential-desktop.exe: exec format error` 로 실패 | interop이 꺼진 WSL에서 `~/.docker/config.json`의 `credsStore`가 윈도 도우미를 가리킨다 | 환경 설정 문제: `credsStore` 항목을 직접 지우거나 interop을 켠다(SETUP.md B절). doctor가 미리 FAIL로 알려 준다 |

## 9. gateway TLS, 로그인 시도, 기기 토큰 (D88/U5·U8, ADR 0005)

### 9-1. HTTPS와 내부 CA 루트 인증서 배포 (사람이 할 일)

- gateway는 HTTPS가 필수다. 컨테이너 8443이 HTTPS, 8080은 평문이지만 `/healthz`만 답하고 나머지는 `308`로 https 주소로 보낸다. 호스트 포트는 `GATEWAY_PORT`(평문), `GATEWAY_TLS_PORT`(HTTPS, 기본 8443; 운영에서 443을 쓰려면 `GATEWAY_TLS_PORT=443`과 `GATEWAY_PUBLIC_TLS_PORT=443`).
- 사이트 이름은 `GATEWAY_HOSTS`(기본 `localhost:8443, 127.0.0.1:8443`)다. 운영에서는 병원 내부 도메인으로 바꾼다(예: `GATEWAY_HOSTS=kiosk.hospital.local:8443`). 인증서는 Caddy 내부 CA가 발급하고, 루트와 발급 인증서는 볼륨 `gateway-data`(`/data/caddy/pki`)에 있어 재시작해도 유지된다(**볼륨을 지우면 루트가 바뀌어 모든 기기가 다시 신뢰해야 한다**; 이 볼륨은 CA 비밀키를 담으므로 유출·백업에 주의).
- 루트 인증서를 꺼낸다: `docker cp deploy-gateway-1:/data/caddy/pki/authorities/local/root.crt ./openit-root.crt`. 이 파일은 공개해도 되는 인증서다(비밀키는 서버에만 있다).
- 키오스크와 직원 PC의 신뢰 저장소에 `openit-root.crt`를 넣는다(루트 권한이 필요한 사람 일): Windows는 `certutil -addstore -f ROOT openit-root.crt`, Ubuntu는 `/usr/local/share/ca-certificates/`에 복사 후 `sudo update-ca-certificates`, Firefox는 별도 저장소(설정에서 가져오기). 브라우저를 다시 시작한다.
- 확인(서버나 PC에서): `curl --cacert openit-root.crt https://<도메인>:8443/healthz` 가 `ok`, `curl -I http://<도메인>:8080/` 가 `308`과 `Location: https://...`.
- 공인 인증서(ACME)로 바꾸려면 병원 정보가 필요하다(도메인, 80/443 개방). `config/Caddyfile`의 HTTPS 사이트에서 `tls internal` 줄을 지우고 `GATEWAY_HOSTS`에 공인 도메인을 적는다(Caddy가 발급·갱신).
- 서비스 사이(gateway→서비스→postgres)는 평문이다. 같은 서버의 Docker 내부 네트워크(서비스·DB 네트워크 internal)로 한정되며, 이 한계와 재검토 조건은 ADR 0005에 있다.
- 이 PC에서 확인한 것: E2E가 시험용 CA만 신뢰하는 클라이언트로 gateway에 https로 접속하고, 평문 308, HSTS·`X-Content-Type-Options`·`X-Frame-Options`, `/config.json` 404를 확인한다. 확인하지 못한 것: 실제 키오스크 브라우저의 신뢰 절차, 공인 인증서 전환.

### 9-2. 로그인 시도 속도 제한: 하지 않았다 (한계와 대안)

Caddy 기본 이미지에는 속도 제한 모듈이 없다(`caddy list-modules` 137개 중 rate/limit 없음, 확인). 모듈을 넣으려면 커스텀 이미지를 빌드해야 하고 이는 공급망에 새 위험을 더하므로 하지 않았다(ADR 0002). 대신:

1. 암호가 무작위 48자리 16진수(`gen-secrets.sh`의 `token_hex(24)`)라 무차별 대입이 현실적이지 않다. 사람이 쓰는 계정 암호를 바꿀 때도 같은 강도를 쓴다.
2. 네트워크 제한: gateway의 호스트 바인드(`GATEWAY_BIND`)를 병원 내부 주소로 한정하고 방화벽(예: nftables `limit rate`, 병원 방화벽)에서 접속 원본과 초당 접속 수를 제한한다(사람 일).
3. 실패 로그 감시: Caddy 접근 로그(JSON, stdout)에 `status: 401`과 원격 IP가 남는다. 같은 IP에서 짧은 시간에 401이 반복되면 차단하는 도구(fail2ban 등)를 호스트에 두고 Docker 로그(`docker logs deploy-gateway-1`)를 읽게 한다. 이 리포는 설치하지 않는다.
4. 한계: 위 둘은 이 리포의 시험으로 확인하지 못했다.

### 9-3. 키오스크 기기별 토큰 (U8): 발급, 배포, 회전, 폐기

- 목록 파일 `config/kiosk-devices.conf`(예시 `config/kiosk-devices.conf.example`, 한 줄에 기기 ID 하나)로 한꺼번에 만든다: `bash scripts/kiosk-add-device.sh from-list`. 한 대: `... add <기기 ID>`. 기기마다 토큰 파일 `secrets/tokens/kiosk-device-<ID>`와 **기기 산출물** `secrets/kiosk-config/<ID>.json`(`{"device_token":..., "allow_remote_stt":false}`, 모드 600)이 생기고 gateway 기기 목록(`gateway-devices.caddy`)이 갱신된다. 반영은 gateway 재시작(`--apply`).
- 산출물은 그 기기에만 전한다(사람 일). 기기의 정적 서버가 `CONFIG_FILE`로 이 파일을 마운트해 `/config.json`으로 낸다(kiosk-frontend 런북). **중앙 kiosk-frontend 컨테이너에는 어떤 기기의 파일도 마운트하지 않는다**(한 컨테이너가 모든 키오스크에 같은 토큰을 내면 기기별 토큰이 무의미하고, 인증 없는 경로로 토큰이 샌다). gateway도 `/config.json`을 404로 막는다.
- 회전: `bash scripts/kiosk-add-device.sh rotate <기기 ID> --apply`. 옛 토큰은 즉시 무효다. 새 산출물을 기기에 전한 뒤 기기를 다시 시작한다. 의심스러운 기기는 바로 회전하거나 폐기한다.
- 폐기: `bash scripts/kiosk-add-device.sh remove <기기 ID> --apply`(토큰 파일과 산출물을 지우고 목록에서 뺀다).
- survey-service가 기기별 토큰을 받는 설정(`SURVEY_KIOSK_DEVICE_TOKENS`)과 세션 소유 확인은 survey-service 영역 몫이다. gateway는 기기 토큰을 확인한 뒤 Authorization을 바꾸지 않고 그대로 넘기며 survey-service가 같은 기기 토큰 표로 세션 소유 기기를 확인한다(9-5절).

### 9-4. 저자 경로(question-authoring)를 gateway로 여는 구성 (D88/U9)

- 경로: `POST /v1/materials`, `/v1/drafts`, `/v1/drafts/*`, `POST /v1/reviews`. 개별 계정 인증(Basic) 뒤에서 역할 `author` 또는 `clinical-reviewer`만 통과하고(없으면 401, 다른 역할은 403), gateway가 서비스 토큰(`qa-gateway-token`, 서비스의 `QA_GATEWAY_TOKENS`)과 인증된 계정 ID(`X-Openit-User`)를 붙인다. 클라이언트가 보낸 `Authorization`·`X-Openit-User`는 덮어쓴다. 이웃 읽기 면(I1 `/v1/question-sets*`)은 열지 않는다.
- 역할표는 두 곳이다: gateway 계정(`config/gateway-accounts.conf`, 역할 `author`/`clinical-reviewer`)과 서비스(`config/question-authoring.env`의 `QA_USER_ROLES`, 사용자 ID=역할). **둘을 같게 둔다.** 현재 값은 시험 계정(`author-e2e`, `clinical-e2e`)이다. 운영에서는 실제 계정으로 바꾸고 시험 계정은 지운다(`gen-secrets.sh`는 계정 파일의 모든 계정에 암호를 만든다).
- 4-eyes는 서비스가 강제한다: 저자의 확인은 `clinical_basis_approved=false`이고 임상 근거 승인은 저자와 다른 `clinical-reviewer`가 `POST /v1/reviews`로 해야 `reviewed_only`에 나타난다(자기 승인 403).
- 본문 상한은 사이트 기본 8MiB(자료 업로드). 응답 헤더 대기는 15초(`proxy_limits`, 시작값).
- E2E 단계 `5a`가 gateway 경유로 위 흐름(401, 403, 등록·확인, 자기 승인 403, 위조 헤더 무시, 승인 뒤 `reviewed_only`, I1 404, 본문 상한)을 확인한다.

### 9-5. 기기 토큰은 gateway가 survey-service에 그대로 넘긴다 (D88/U8)

- gateway는 키오스크가 보낸 `Authorization: Bearer <기기 토큰>`을 기기 목록(`gateway-devices.caddy`)과 대조한 뒤, **헤더를 바꾸지 않고** survey-service에 넘긴다(직원·운영자·승인·검토·저자 경로는 예전처럼 서비스 토큰으로 바꿔 붙인다). survey-service는 같은 기기 토큰 표(`SURVEY_KIOSK_DEVICE_TOKENS_FILE` = `secrets/tokens/survey-kiosk-device-tokens`, 줄마다 `기기ID=토큰`)로 검증하고, 세션을 만든 기기만 그 세션에 접근하게 한다(다른 기기는 404). 별도 신뢰 헤더를 만들지 않아 gateway를 새 신뢰 경계로 만들지 않는다.
- 공유 서비스 키오스크 토큰(`SURVEY_API_TOKEN`)은 compose에서 뺐다. `/readyz`의 `kiosk_tokens.shared_kiosk_token`은 false이고 `device_tokens`는 기기 수다(E2E 5d가 확인).
- 기기 표는 `kiosk-add-device.sh add/remove/rotate/from-list/sync`가 gateway 목록과 함께 다시 쓴다. `--apply`는 gateway와 survey-service를 함께 다시 시작한다(survey가 표를 시작 때 읽는다). 폐기는 gateway에서 즉시(재시작 직후) 막히고 survey 표는 survey 재시작 뒤에 바뀐다.
- 기기 목록이 2대 이상일 때 예전 생성기가 Caddy `header` 매처(값을 하나만 받는다)에 값을 여러 개 넘겨 목록이 동작하지 않았다. `expression {http.request.header.Authorization} in [...]`로 고쳤다(이 PC에서 4대로 확인, 자체 시험이 5대로 `caddy validate`).

### 9-6. gateway CA 루트의 백업과 복원 (점검 M3)

- `gateway-data`(Caddy 내부 CA 루트 인증서와 **비밀키**, `/data/caddy/pki`)는 `scripts/backup.sh`가 다른 파일 저장소와 같은 restic 저장소(암호화)에 백업한다(기본 대상에 포함).
- **루트가 바뀌면(볼륨을 잃었거나 새 서버면) 모든 키오스크와 직원 PC가 새 루트를 다시 신뢰해야 한다. 백업에서 복원하면 루트가 유지되어 기기는 아무것도 하지 않아도 된다.** 복원: 서비스(gateway)를 멈추고 `bash scripts/restore.sh gateway-data latest --yes`(소유자·모드는 백업 때 값 그대로 돌아온다) 후 gateway를 시작한다. 복원 시험은 자체 시험(`test-backup.sh`)이 한다.

## 10. 병원 서버에 올리기 전 요건 (사용자가 확인하는 것)

이 절의 항목은 이 리포의 시험으로 확인되지 않는다. 각 항목이 왜 필요한지는 아래에 적는다.

### 10-1. 로그인 시도 제한이 없다 -> 내부망 제한, 강한 암호, 실패 로그 감시 (OPEN_GAPS L03)

- 왜: gateway(Caddy 기본 이미지)에는 속도 제한이 없고, 커스텀 이미지로 모듈을 넣으면 공급망 위험이 늘어 하지 않았다(§9-2, ADR 0002). 그래서 무차별 대입을 막는 장치가 gateway 안에 없다.
- 요건 1: `GATEWAY_BIND`를 병원 내부 주소로 한정하고 방화벽에서 접속 원본·초당 접속 수를 제한한다(인터넷에 직접 열지 않는다).
- 요건 2: 계정 암호는 `gen-secrets.sh`/`rotate-account.sh`가 만드는 무작위 48자리 16진수 강도를 유지한다(사람이 고른 짧은 암호로 바꾸지 않는다).
- 요건 3: 접근 로그의 401 반복(같은 IP)을 감시한다(§9-2의 3번, 감시 도구 설치는 호스트 몫).
- 확인한 것: Caddy 기본 모듈에 rate limit이 없다(§9-2). 확인하지 않은 것: 병원 방화벽 규칙과 감시 도구의 동작.

### 10-2. 저장 시 암호화가 없다 -> 데이터 볼륨은 암호화된 디스크여야 한다 (OPEN_GAPS L06)

- 왜: PostgreSQL(`pg-data`)과 파일 저장소 볼륨(`gate-data`, `models-data`)은 디스크에 평문으로 쓰인다. 이 리포는 DB 수준 암호화(TDE 등)를 켜지 않았다. 호스트 디스크가 분실·반출되면 문진 응답이 읽힌다. 백업은 별도로 restic 저장소에서 암호화된다(§4).
- 요건: Docker의 데이터 루트(볼륨이 놓이는 경로)가 있는 디스크를 OS 수준 전체 디스크 암호화(Linux는 LUKS/dm-crypt, Windows는 BitLocker)로 보호한다. 병원 서버에서 사용자가 직접 확인한다: 예) Linux `lsblk -f`에서 데이터 루트(`docker info --format '{{.DockerRootDir}}'`)가 crypt 장치 위에 있는지.
- 확인하지 못한 것: 대상 서버의 디스크 구성. 이 리포는 암호화 여부를 점검하지 않는다(서버 밖 사실이다).

