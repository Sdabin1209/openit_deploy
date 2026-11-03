# 0054. 컨테이너가 읽는 비밀 파일은 640 + 그룹, 컨테이너는 group_add

- 상태: 채택 (OPEN_GAPS L02, 2026-11-03)
- Supersedes: 0022 의 결정 3번(컨테이너가 읽는 파일은 644)과 그 "적용하지 않았다" 판단. 나머지(폴더 700, 호스트 전용 600)는 유지
- 날짜: 2026-11-03

## 맥락

compose 의 파일 secrets 는 호스트 소유자·그룹·모드를 그대로 마운트한다. 이미지는 uid 10001(postgres 는 999)이라 호스트 사용자 소유 600 파일을 읽지 못해, 컨테이너가 읽는 파일을 644 로 두었다(폴더 700 안). 0022 는 640 + `group_add` 가 격리 시험에서 통과했음에도 전체 변경 범위와 검증 수단이 없어 적용을 미뤘다. 이제 그 검증을 정적 시험 + 컨테이너 읽기 시험으로 한다.

## 결정

- `secret_mode`(scripts/lib.sh): compose.yaml 의 secrets·configs 가 가리키는 파일은 **640**, 호스트 전용 파일은 600, 다른 호스트로 옮겨 읽는 추론 서버용 셋(`model-runtime-tokens`, `gate-read-model-serving`, `external-inference`)은 644 그대로.
- 640 파일의 그룹은 `SECRETS_GID`. 기본값은 만드는 호스트 사용자의 주 그룹(`id -g`), `scripts/lib.sh` 가 내보낸다. `gen-secrets.sh`·`restore-secrets.sh`·게이트웨이 설정 쓰기가 `secret_fix` 로 모드와 그룹을 맞춘다.
- `compose.yaml` 의 모든 서비스·잡이 `group_add: [SECRETS_GID]`(앵커 `x-secretgid`)를 가진다. 변수가 없으면 compose 가 읽기 전에 멈춘다(`:?`).
- `check-secret-perms.sh` 는 640 이어야 하는 파일에 기타 접근이 있거나 그룹이 SECRETS_GID 와 다르면 FAIL.

## 왜

- 최소 권한: 644 는 같은 호스트의 모든 사용자 읽기, 640 은 그 그룹 구성원만이다. uid 를 바꾸지 않아 영역 이미지(uid 10001 전제)를 건드리지 않는다.
- `group_add` 는 Compose 표준 필드다. 이전 시험(0022)이 640 + group_add 로 읽힘을 보였고, 이번에 `scripts/test-secret-group-read.sh` 가 uid 10001 + group_add 는 읽고 group_add 없이는 못 읽는 대조군을 실제 컨테이너로 확인한다.
- 전용 그룹을 만들지 않고 주 그룹을 쓰는 이유: 새 그룹은 root 가 필요하다(0022 가 버린 대안). 주 그룹이면 `gen-secrets.sh` 가 root 없이 돈다.

## 검토한 대안과 버리는 이유

- 644 유지: 0022 의 현행. 폴더 700 이 막아 주므로 증분 이득이 작지만 L02 로 사용자가 올린 항목이다.
- 600 + 소유자 10001 로 chown: 호스트 사용자가 못 읽는다(0022).
- Docker secrets long syntax 의 uid/gid/mode: Compose(비 swarm)는 적용하지 않는다(0022 가 측정함).

## 결과

- 얻는 것: 컨테이너가 읽는 비밀이 그룹 구성원에게만 읽힌다. 설정 어긋남은 doctor/check-secret-perms 가 잡는다.
- 감수하는 것: gid 가 호스트마다 다르다. 다른 호스트로 비밀 폴더를 옮기거나 복구하면 그 호스트의 `SECRETS_GID` 로 `gen-secrets.sh` 를 다시 돌려 그룹을 맞춘다(복구 스크립트는 `secret_fix` 로 맞춘다). 같은 사용자·docker 그룹은 여전히 읽을 수 있다.
- 확인하지 못한 것: 전체 서비스가 실제로 healthy 가 되는지는 E2E 에서만 안다(이번에 돌리지 않았다). 읽기 시험은 uid 10001 컨테이너 하나로 했고 postgres(uid 999)는 같은 방식이지만 따로 읽어 보지 않았다.

## 되돌리는 조건

Compose 가 파일 secrets 의 uid/gid/mode 를 적용하면 600 + 지정 소유자로 바꾸고 이 ADR 을 대체한다.
