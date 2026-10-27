# 0025. 로컬 레지스트리 강화: 비root, 읽기 전용, cap_drop ALL

- 상태: 채택
- 날짜: 2026-10-28
- 관련: D24(로컬 레지스트리), 점검 F1·F6

## 맥락

`registry:2`는 컨테이너 기본이 root 실행·쓰기 가능 루트·기본 capability였다. 인증과 TLS가 없어 127.0.0.1에만 바인드한다(그래서 이 한계는 그대로다). 이미지가 쌓이는 레지스트리가 약하면 공급망 신뢰 경계가 약해진다.

## 결정

`compose.registry.yaml`에서 레지스트리를 `user: 65532:65532`, `read_only: true`, `cap_drop: ALL`, `no-new-privileges`, tmpfs `/tmp`, 로그 회전, 자원 한도(ADR 0023, 측정 안 함)로 띄운다. `registry-data` 볼륨은 이미지가 root 소유로 만들므로 일회성 서비스 `registry-perms`(root, `CHOWN` capability만, 네트워크 없음, 읽기 전용)가 소유자를 65532로 바꾼 뒤 레지스트리가 뜬다(`service_completed_successfully`, 멱등).

## 왜 (따른 표준과 근거)

- 비root·읽기 전용 루트·capability 제거·no-new-privileges는 컨테이너 강화의 일반 지침이다(OWASP Docker Security Cheat Sheet, CIS Docker Benchmark). 이 세션에서 원문을 다시 열지는 않았다. 다른 서비스가 이미 같은 방식(`x-hardening`)이다.
- **동작을 확인했다**: 임시 프로젝트에서 띄워 `id`가 uid 65532, 루트에 쓰기 불가(`touch`가 Read-only file system), 컨테이너 설정이 ReadonlyRootfs/CapDrop ALL/no-new-privileges, healthy, 그리고 HTTP로 블롭 업로드가 201, 다시 조회가 200(볼륨에 비root로 쓰기 성공)임을 확인했다.
- 65532: 서비스 이미지의 10001, postgres의 999와 겹치지 않는 별도 비특권 uid를 골랐다. 65532에는 특별한 근거가 없다(관례적으로 쓰이는 'nonroot' 값). 기능상 다른 비특권 uid여도 된다.

## 검토한 대안과 버리는 이유

- **root 유지 + cap_drop만**: 파일 소유가 root라 동작은 하지만 root 프로세스가 남는다. 일회성 chown 서비스로 비root가 가능함을 확인했으므로 버린다.
- **볼륨을 미리 65532 소유로 만드는 수동 절차**: 사람이 빠뜨린다. 자동 서비스가 낫다.
- **인증·TLS 추가(htpasswd + 인증서)**: 도메인·CI 경로가 미정이다(runbook 1절, ci.md). 이번 범위가 아니다.

## 결과

- 얻는 것: 레지스트리 프로세스가 root가 아니고 루트 파일시스템을 바꾸지 못한다.
- 감수하는 것: 시작 때 일회성 서비스가 한 번 돈다(`registry.sh up`은 `--wait` 없이 `up -d`라 영향 없음). 인증·TLS 없음, 삭제 허용(`REGISTRY_STORAGE_DELETE_ENABLED`)과 가비지 컬렉션 절차 없음은 그대로다(점검 A6). **기존 레지스트리 볼륨 위에서의 첫 전환은 확인하지 못했다**(새 볼륨만 시험; 기존 볼륨은 chown 서비스가 소유자를 바꾸는 설계).

## 되돌리는 조건

- 레지스트리 이미지가 비root·읽기 전용에서 동작하지 않는 버전으로 바뀌면(digest 갱신 시 E2E/레지스트리 시험으로 확인) 원인을 확인하고 이 ADR을 고친다.
