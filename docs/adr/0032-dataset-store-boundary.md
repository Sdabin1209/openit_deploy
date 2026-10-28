# 0032. dataset-store(I2)의 서비스 경계, 네트워크, 볼륨, 백업

- 상태: 채택(2026-10-28). 확인한 것은 이 PC 한 환경에서 (1) 이미지 빌드, (2) compose 설정 렌더링, (3) 같은 강화 옵션(읽기 전용, cap_drop ALL, no-new-privileges, 512m, pids 256)으로 띄운 단독 컨테이너에 E2E 단계 7d 의 단언을 돌려 통과, (4) 유휴 상태의 `docker stop` 0.7초, (5) 재시작 전후 `datasets-data` 지문 동일이다. 전체 스택 E2E 는 아직 돌리지 않았다(아래 "확인하지 못한 것").
- 근거 결정: D100(I2 도 HTTP), D49(이웃 저장소 볼륨 공유 금지, 영역 사이는 HTTP), D84(비밀은 파일), D22(컨테이너 점검), D24(digest 잠금).

## 맥락

synthetic-data 가 I2 DatasetStore HTTP 서버(`python -m synthetic_data.service`, 이미지 이름 dataset-store)를 완성했다(synthetic-data 커밋 8514220, ADR 0011·0012). 소비자 model-lab 은 데이터셋을 파일 저장소 볼륨으로 읽던 것을 HTTP 로 바꾼다. deploy 는 이 서비스를 스택에 올리면서 경계(누가 닿는가), 볼륨, 백업, 종료 시간을 정해야 한다.

## 결정

1. 서비스 `dataset-store` 를 `compose.yaml` 에 model-registry 와 같은 강화 설정(읽기 전용 루트, `cap_drop: ALL`, `no-new-privileges`, 자원 한도, 로그 회전, healthcheck)으로 둔다. 이미지는 `locks/images.lock` 의 `DATASET_STORE_DIGEST` 로만 참조한다(D07).
2. 전용 internal 네트워크 `datasets` 에만 붙인다. gateway, 다른 서비스, 호스트 포트 모두 붙이지 않는다. 시험 override(`compose.test.yaml`)만 별도 `test-ds` 와 `127.0.0.1` 임의 포트를 더한다.
3. 전용 볼륨 `datasets-data` 를 `/data` 에 마운트한다. 쓰기는 이 서버만 한다.
4. 비밀은 `dataset-store-read-tokens`(역할 `model-lab`)와 `dataset-store-write-tokens`(역할 `synthetic-data`) 두 파일을 `NAME_FILE` 로 받는다. `gen-secrets.sh` 가 만든다.
5. `datasets-data` 를 `backup.sh` 의 기본 저장소에 넣고 E2E 백업·복구(볼륨 삭제, 복구, 지문 일치)에 포함한다. 서버의 요청 임시 폴더 `.tmp` 는 백업과 지문에서 뺀다.
6. `stop_grace_period: 40s`.
7. 이미지는 계약 v2.1.0(I2 HTTP 면이 2.1.0 부터)으로 빌드한다. 기준 태그(v2.0.2)와 달라서 `lib.sh` 에 `DEPLOY_BC_TAG_DS` 를 따로 둔다.

## 왜

- 별도 네트워크: 기존 원칙은 "호출 경로마다 전용 네트워크"(ADR 0031, `compose.yaml` networks 주석)다. model-registry 는 release 네트워크(release-gate 가 읽는다)에 있지만 dataset-store 의 소비자는 compose 안에 없다(model-lab 은 GPU 호스트 쪽 잡). release 에 두면 release-gate·question-authoring 이 불필요하게 닿는다(읽기 토큰은 없지만 도달 가능성 자체가 공격면이다). 소비자가 compose 안에 생기면 그때 그 서비스만 `datasets` 에 붙인다.
- internal: true: 학습 데이터셋(비식별 실패 사례에서 만든 시드가 들어간다)을 가진 서비스가 바깥으로 나갈 이유가 없고, 나가는 길이 없으면 침해돼도 반출이 어렵다. 키오스크·직원 경로(gateway)는 `datasets` 에 붙지 않고 Caddyfile 에 dataset-store 경로가 없다. e2e.sh 가 (a) 다른 서비스에서 dataset-store 가 닿지 않는 것, (b) 네트워크 구성원이 dataset-store 하나뿐인 것, (c) Caddyfile 에 이름이 없는 것을 확인한다.
- 볼륨 하나와 HTTP: D49 는 이웃 볼륨 공유를 금지한다. 쓰기 주체(synthetic-data 서버)와 읽기 주체(model-lab)가 같은 볼륨을 보지 않고 토큰으로 역할을 나눈다(쓰기 역할은 synthetic-data 하나, HTTP.md ## I2).
- 읽기 토큰 대상은 model-lab 하나: 읽기 호출자는 계약상 model-lab 이다. 쓰기 토큰으로도 읽을 수 있으므로(synthetic-data ADR 0012) synthetic-data 용 읽기 토큰을 따로 만들지 않는다. 호출자를 늘리면 역할 파일에 줄을 더한다(`gen-secrets.sh` 의 `DS_R`).
- 백업에 넣는 이유: 게시된 버전은 불변이고 모델 패키지의 계보(`lineage.dataset` 의 id·버전·content_hash)가 가리킨다. 볼륨을 잃으면 같은 데이터로 재학습·재현할 수 없다. 원본 jsonl 은 데이터셋 담당의 서버에 있을 수 있으나, 이 저장소의 게시 사본이 계보의 기준이고 그 원본의 보존은 deploy 가 확인하지 못한다. 크기는 측정하지 않았다(synthetic-data ADR 0008 은 수 MB 규모로 추정, 실제 C1 6개는 64,459행). 백업은 암호화한 tar 이며(ADR 0020) 용량이 크면 보관 기간으로 조절한다.
- `.tmp` 제외: 서버는 시작 때 `/data/.tmp` 를 비우고 다시 만든다(synthetic-data ADR 0012). 복구할 데이터가 아니고, 지문에 들어가면 서버를 껐다 켤 때마다 지문이 달라진다.
- 종료 시간: 서버는 SIGTERM 에서 진행 중 요청을 끝까지 기다린다(non-daemon 스레드). 요청 소켓 timeout 이 30초(기본)이므로 멈춘 요청은 30초 안에 끝나고, 여유 10초를 더해 40초로 했다. 이 값은 release-gate 의 40초(하드 상한 35초 + 5초)와 같은 모양이지만 **하드 상한은 synthetic-data 가 확정하지 않았다**: 정상으로 느리게 받는 큰 읽기·게시는 30초 소켓 timeout 이 매번 갱신되므로 더 걸릴 수 있다(측정 안 함). 강제 종료돼도 게시는 임시 폴더에 쓴 뒤 rename 하므로 반쯤 쓴 버전이 보이지 않는다(synthetic-data ADR 0008·0012, 그 영역의 주장이며 deploy 는 SIGKILL 으로 확인하지 않았다).
- 자원 한도 512m/1.0/256: model-registry 와 같은 값. 측정하지 않았다(ADR 0023 과 같은 시작값). 서버가 파일을 메모리로 올리는 읽기(`open_file`)가 있어 큰 파일에서 OOM 이 날 수 있다.
- 계약 태그 분리: 기준 태그(v2.0.2)를 올리는 일은 태그 push 이후 한 번에 한다(STATUS). dataset-store 는 I2 서버라 v2.1.0 이 필요해 `DEPLOY_BC_TAG_DS` 로 따로 두고, 기준이 올라가면 지운다. `check-versions.sh` 는 synthetic-data 의 `Dockerfile*` 표기를 이 항목(`DEPLOY_BC_TAG_DS`)과, 같은 리포의 나머지 파일(requirements.lock 등, 호스트 실행용)을 `DEPLOY_BC_TAG_SD` 와 대조한다.

## 검토한 대안과 버리는 이유

- release 네트워크에 두기(model-registry 와 같은 방식): release-gate 외에 question-authoring 도 닿는다. 소비자가 없는 접근을 열 이유가 없다.
- 호스트 포트(127.0.0.1)를 운영에도 열기: GPU 호스트의 model-lab 이 접근해야 하는 날이 오면 필요할 수 있다. 지금 소비자 배치(model-lab 이 같은 호스트 안인지 GPU 서버인지)가 미정이라 열지 않았다. 필요해지면 포트 게시나 별도 override 를 새 ADR 로 정한다(gateway 로 노출하지 않는다는 원칙은 유지).
- gateway 로 노출: 키오스크·직원 경로와 학습 데이터 경로를 같은 입구에 두면 직원 계정 하나의 침해가 학습 데이터 접근으로 이어진다.
- 볼륨을 model-lab 과 공유(읽기 전용 마운트): D49 가 금지한다.
- 백업 제외(원본에서 재생성 가능하다고 보기): 재생성 가능한지 확인하지 못했고, 불변 버전이 계보의 기준이라 제외하지 않는다.

## 결과

- 얻는 것: model-lab 이 HTTP 로 데이터셋을 읽을 수 있고(소비자 쪽 구성은 그 영역), 경계가 compose 구조와 E2E 차단 검사로 확인된다. 볼륨 손실에서 복구할 수 있다.
- 감수하는 것: 백업 용량이 늘고, 운영에서 GPU 호스트가 이 서비스에 닿는 경로는 아직 없다. `locks/images.lock` 에는 dataset-store 의 digest 가 레지스트리에 게시되기 전까지 없다(`publish-images.sh` 로 생긴다). 그 전에는 `docker compose` 가 `DATASET_STORE_DIGEST` 필수 변수 오류를 낸다.
- 확인하지 못한 것: 전체 스택 E2E(헤드가 별도로 돌린다), `compose.yaml` 로 띄운 컨테이너의 `check-containers.sh` 결과, 요청이 진행 중일 때의 종료 시간(유휴 0.7초만 쟀다), 백업·복구 왕복(`backup.sh`/`restore.sh` 로 `datasets-data` 를 지우고 되살리는 것).

## 되돌리는 조건

- model-lab 이 compose 안의 서비스가 되면 그 서비스를 `datasets` 네트워크에 붙인다(구조 변경 없음).
- 소비자가 호스트 밖이면 접근 방식을 새 ADR 로 정한다(TLS 포함, ADR 0031 의 범위 밖이 된다).
- synthetic-data 가 종료 하드 상한을 확정하면 `stop_grace_period` 와 `test_e2e_constants.py` 의 대조 시험을 그 값에 맞춘다.
