# 0038. 백업은 restic 저장소 하나, 암호는 파일

- 상태: 채택 (Supersedes [0020](0020-backup-tool-and-encryption.md))
- 날짜: 2026-10-29

## 맥락

0020의 백업은 직접 만든 `backup_tool.py`(파일 복사, SQLite backup API, SHA-256 MANIFEST, 복원, 지문)와 셸(`backup-lib.sh`의 age/gpg 파일별 공개키 암호화, find 기반 보관 삭제, tar 묶기)로 이루어졌다. D111은 백업 도구를 표준 도구(restic)로 바꾸라고 했다.

## 결정

restic 저장소 하나에 모든 백업을 둔다. 운영(D112)은 **서버 밖 append-only 저장소**(restic `rest-server --append-only`, `BACKUP_REPOSITORY=rest:https://…`, 서버 자격은 `BACKUP_REST_CREDENTIAL_FILE`)이고, 개발·시험은 로컬 폴더(`BACKUP_DIR/restic`)다. restic은 `locks/images.lock`의 digest 고정 이미지(`RESTIC_IMAGE`, restic 0.18.0)를 `docker run`으로 부른다(호스트에 설치하지 않는다). 저장소 암호는 `BACKUP_PASSWORD_FILE`(`RESTIC_PASSWORD_FILE`)로만 준다.

- 파일 저장소: 볼륨을 읽기 전용으로 붙여 `restic backup /data --host <저장소> --tag set-<시각>`(datasets-data는 `.tmp` 제외).
- PostgreSQL: `pg_dump -Fc | restic backup --stdin --stdin-filename <db>.dump --host pg-<db>`. 평문 덤프가 디스크에 쓰이지 않는다. 덤프가 중간에 실패하면 이 실행의 스냅샷을 모두 forget한다.
- secrets/: 같은 저장소에 `--host secrets`.
- 보관: `restic forget --keep-within <N>d --keep-last 1 --prune`(host별로 최신 하나는 남긴다. 옛 `backup_prune`과 같은 규칙). 로컬 모드는 백업 스크립트가 하고, **append-only 모드에서는 서버에 지울 권한이 없으므로 저장소 쪽 `scripts/backup-prune.sh`(저장소 파일 접근 + 저장소 암호)가 한다.**
- 덤프가 중간에 실패하면: append-only에서는 만든 스냅샷을 지울 수 없으므로 **만들지 않는다**. `pg_dump` 종료 코드를 알 때까지 파이프를 열어 두고, 실패면 EOF 전에 restic 컨테이너를 죽인다. 여러 데이터베이스 중 일부만 성공한 실행은 성공한 것의 스냅샷이 남는다(같은 `set-` 태그에 5개가 모두 있는 세트만 완성본).
- 복구: `restic restore <스냅샷>:/data --verify`(볼륨, root로 실행해 소유자·모드가 백업 때 값 그대로), `restic dump ... | pg_restore`(데이터베이스).
- 정기 복원 시험: 임시 저장소로 `pg-backup` -> `restic dump` -> 임시 DB 복원 -> 행 지문 대조, 실제 저장소는 `restic check --read-data-subset=5%`.
- 삭제: `backup_tool.py`, age/gpg 암호화 코드와 키(`BACKUP_ENCRYPT_RECIPIENTS`, `BACKUP_ENCRYPT_TOOL`, `BACKUP_ALLOW_PLAINTEXT`), MANIFEST 해시 파일, `BACKUP_SECRETS_DIR/KEEP`. 옛 키가 설정에 남아 있으면 CRIT로 거부한다.

## 왜

- 표준: restic 문서의 암호화 저장소(AES-256-CTR + Poly1305-AES 인증), 내용 주소 방식 중복 제거, 스냅샷, `forget/prune`, `check`, `dump`/`restore --verify`. 내용 해시와 인증이 직접 만든 MANIFEST 해시와 같은 일을 한다.
- 시험으로 확인한 것(test-backup.sh 38건, test-backup-secrets.sh 15건): 저장소에 평문 표지(PGDMP, 비밀 마커)가 없다, 틀린 암호는 거부된다, 데이터 파일 1바이트 손상을 `restic check --read-data`가 잡는다, 중도 실패한 덤프의 스냅샷이 남지 않는다, 보관 정리가 host별 최신 하나를 남긴다, 복구된 파일의 소유자·모드가 같다, secrets 복원 뒤 `deid-salt`가 같은 값이다.

## 값의 출처

| 값 | 출처 |
| --- | --- |
| 보관 14일 | D88 U4 사용자 결정(설정값), 측정 안 함 |
| 정기 점검 `--read-data-subset=5%` | 시작값. 근거: 매주 전체를 읽으면 원격 대상에서 비용이 크다는 판단. 측정 안 함 |
| 컨테이너 권한(root + CHOWN/DAC_OVERRIDE/FOWNER, 나머지 cap 제거) | 볼륨 안 파일이 uid 10001 소유 0600이라 읽으려면 root가 필요하다는 제약. 필요한 capability만 시험으로 확인 |
| 캐시를 컨테이너 tmpfs에 둠 | 캐시가 저장소 크기를 늘리지 않게. 작은 저장소라 재생성 비용은 무시, 측정 안 함 |

## 검토한 대안과 버리는 이유

- 자체 도구 유지: D89에 어긋난다.
- borg: 원격 서버 쪽에 borg가 필요하다. restic은 local, sftp, S3 등 백엔드가 같은 이미지로 되고 이미지 하나로 끝난다. 두 도구를 비교 측정하지는 않았다.
- pg_basebackup/WAL 보관(PITR): 0020이 이미 O16(허용 중단 시간·복구 시점) 결정 전이라 논리 백업으로 두었고 이 결정도 같은 전제다.
- age/gpg 공개키 암호화를 restic 위에 얹기: restic은 공개키 모드가 없다. 파일을 따로 암호화하면 중복 제거를 못 쓰고 옛 구조를 다시 만든다.

## 결과

- 얻는 것: 자체 코드 약 140줄과 MANIFEST·tar·파일별 암호화·`.partial` 정리 코드가 사라진다. 중복 제거로 일일 백업 증분이 작아진다(크기는 측정 안 함). 평문 덤프가 디스크에 쓰이지 않는다. 손상 검증이 표준 명령이다.
- **감수하는 것(0020의 보증이 일부 약해진다)**: 0020은 서버에 공개키만 두어 서버가 뚫려도 백업 내용이 읽히지 않았다. restic은 대칭 암호라 자동 백업을 위해 **암호가 서버에 있어야 한다. 서버가 침해되면 백업을 읽을 수는 있다.** 그러나 저장소가 서버 밖 append-only라 **지우거나 고칠 수는 없다**(랜섬웨어·파괴 대비, 사용자 결정 D112). 시험으로 확인했다(test-backup.sh): 서버 자격의 `restic forget`은 403, 스냅샷·데이터 파일 DELETE와 기존 파일 덮어쓰기(POST)는 403, 자격 없는 접근은 401. 한계: append-only는 rest-server 설정에 기댄다(서버 쪽 `--append-only`가 꺼져 있으면 보증이 없다: 저장소 쪽에서 확인, runbook 4-7). 락 파일은 지울 수 있다(restic 동작에 필요). 암호를 잃으면 모든 백업을 못 푼다. 로컬 폴더 모드는 서버가 지울 수 있어 개발·시험 전용이다(`backup-check.sh`가 경고).
- SQLite backup API 경로는 없어졌다. 운영 볼륨에는 SQLite가 없다(D85). 개발·시험용 SQLite는 백업 대상이 아니다.
- 옛 age 분기(이 PC에서 한 번도 실행 못 했음)와 gpg 분기가 함께 사라져 "age는 미실행" 한계가 없어진다.
- 옛 백업(0020 형식)은 이 도구로 복원할 수 없다. 전환 시점에 새 백업을 먼저 한 번 받아 두고 옛 백업은 옛 절차(ADR 0020)로 푼다.

## 되돌리는 조건

서버 침해 시 백업을 읽히는 위험까지 받아들이지 않으면(개인정보) 암호가 서버에 없는 구조(서버 밖 pull 방식, 또는 공개키 암호를 restic 앞에 두는 구조)를 새 ADR로 정한다. 그 경우 중복 제거 이점은 줄어든다.
