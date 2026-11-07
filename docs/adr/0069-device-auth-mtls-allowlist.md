# 0069. 기기 인증은 mTLS 하나, 기기 허용 목록(DeviceAllowlist)을 deploy 가 만든다

- 상태: 채택 (계약 boundary-contracts v4.0.2: PUBLIC_API F절, DeviceAllowlist, PublicIngressEnv, 헤드 D136). **0040 을 대체한다**(Supersedes 0040).
- 날짜: 2026-11-08

## 맥락

0040 은 게이트웨이(Caddy) 클라이언트 인증서 검증을 2.x 기기 토큰 경로와 함께 두었다(인증서가 없으면 토큰 경로). 계약 4.0.0(D136)은 기기 토큰을 없앴다: 기기 인증은 mTLS 하나이고, 공개 입구(platform public-ingress)가 신뢰 CA(`INGRESS_DEVICE_CA_FILE`)로 TLS 에서 인증서를 검증한 뒤 요청마다 인증서의 CN(기기 ID)과 일련번호를 허용 목록(`DeviceAllowlist`, `INGRESS_DEVICE_ALLOWLIST_FILE`)과 대조한다. 인증서 없음·목록 밖은 403 PERMISSION_DENIED, 신뢰 CA 밖의 인증서는 TLS 핸드셰이크에서 거절된다. 이 허용 목록은 deploy 가 만드는 계약 산출물(x-producers: deploy)이다. 세션 ID 는 서버가 발급한다(SessionStartBody 에 session_id 가 없다). 합성 데이터 잡 설정은 구현 모듈 경로 factory 대신 `HttpClientSettings`(D135)를 쓴다.

## 결정

- 기기 토큰 장치를 모두 없앤다: `INGRESS_DEVICE_TOKENS_DIR` 마운트, `SURVEY_KIOSK_DEVICE_TOKENS(_FILE)`, `gen-secrets.sh` 의 기기 토큰 생성, 토큰 기반 `kiosk-add-device.sh`, survey 기기 토큰 표.
- 허용 목록은 전용 공개 폴더 `DEVICE_ALLOWLIST_DIR`(기본 `state/device-allowlist`)에 `allowlist.json` 하나만 둔다. compose 는 이 **폴더**를 `/etc/openit/devices` 에 읽기 전용으로 마운트하고 `INGRESS_DEVICE_ALLOWLIST_FILE=/etc/openit/devices/allowlist.json` 을 준다. 비밀 폴더, 기기 CA 개인 키, 기기 키는 입구에 마운트하지 않는다. 입구에는 CA 의 공개 인증서(`device-ca.pem`)만 `INGRESS_DEVICE_CA_FILE` 로 간다.
- 등록·회전·폐기는 허용 목록을 바꾸는 것이다(`scripts/kiosk-add-device.sh`): `add`(개발용 CA 로 발급 + 일련번호 추가), `register <기기> <일련번호>`(조직 PKI 가 발급한 인증서의 일련번호), `rotate`(새 일련번호를 더함), `revoke-serial`(일련번호를 뺌, 마지막이면 기기가 빠진다), `remove`(기기 항목 삭제). 입구가 요청마다 목록을 읽으므로 재시작이 필요 없다(`--apply` 는 없어졌다).
- 목록 갱신은 `scripts/device_allowlist.py`(얇은 진입점) 한 곳이 한다. 판정(정규화·합치기·계약 검증)은 컴포넌트 `openit_deploy/components/device_allowlist.py`(DeviceAllowlistEditRequest → DeviceAllowlistEditResult, D117), 잠금·파일 교체는 `openit_deploy/wiring/cli_device_allowlist.py`: 읽기-수정-쓰기 전체에 배타 잠금(fcntl.flock)을 쥐고, 계약 패키지의 검증기로 검증한 뒤(어기면 파일을 바꾸지 않는다), 같은 폴더의 임시 파일에 쓰고 `fsync` 후 `os.replace`(POSIX rename 원자 교체)한다. 일련번호는 RFC 5280 4.1.2.2 대로 양의 정수를 앞자리 0 없는 소문자 16진수로 정규화한다.
- 권한: 폴더 0755, 파일 0644. 입구 컨테이너는 uid 10001, gid 0 으로 돈다(platform 이미지 라벨 `io.openit.inputs` 의 `roles.default.process`, 읽은 이미지: 로컬의 `platform-ingress:codex-debug-1331647`, 계약 v4.0.0 라벨). 호스트 파일의 소유자도 그룹도 아니므로 '기타' 읽기가 필요하다. 목록은 비밀이 아니다(계약 DeviceAllowlist).
- 개발·시험용 기기 CA 와 기기 인증서는 `openssl` 표준 명령으로 만든다(`gen-secrets.sh --test-fixtures`, `kiosk-add-device.sh add`): EC P-256, CA 30일, 기기 인증서 30일, 일련번호는 127비트 난수(맨 위 비트 고정, 양수), clientAuth. 운영의 인증서 발급은 조직 PKI/MDM 몫이다(D113).
- E2E 는 공개 입구로만 부르고 기기 인증서를 표준 `ssl.SSLContext`(`load_verify_locations`로 서버 CA, 호스트 이름 검증 켬, `load_cert_chain` 으로 기기 인증서)로 낸다. 계약 클라이언트(`boundary_contracts.clients`)는 SSL 문맥·클라이언트 인증서를 받는 공개 인자가 없다(비공개 `_context` 뿐)어서 키오스크 호출은 urllib 에 SSLContext 를 직접 준다. 단계 5d 가 확인한다: 인증서 없음·목록 밖은 403 PERMISSION_DENIED, 다른 CA 의 인증서는 연결 오류(HTTP 응답 없음), 일련번호를 목록에서 빼면 다음 요청이 403 이고 되돌리면 회복한다. 세션 시작 본문에는 session_id 가 없고 응답의 값을 쓴다. 합성 잡 설정은 `HttpClientSettings`.

## 왜

- 표준: X.509 클라이언트 인증(RFC 8446 4.3.2·4.4.2, RFC 5280), 일련번호 규칙(RFC 5280 4.1.2.2), 파일의 원자 교체(POSIX `rename(2)` 는 같은 파일시스템에서 원자적), 배타 잠금(POSIX `flock(2)`). 계약이 정한 입력이다(구조 규칙 6: 영역 간 스키마는 헤드가 책임).
- 부모 폴더 마운트: 목록은 임시 파일을 rename 해 교체하므로 파일만 바인드 마운트하면 컨테이너는 옛 inode 를 본다. 계약도 폴더 마운트를 요구한다.
- 잠금을 읽기부터 쥐는 이유: 잠금 없이 읽고-쓰면 동시에 등록한 두 호출 중 하나의 일련번호가 사라진다(마지막 쓴 쪽이 이김). 시험(`test-kiosk-devices.sh`)이 동시 12건 등록으로 확인한다.
- 목록을 비밀 폴더 밖에 두는 이유: 입구에 마운트되는 폴더에 비밀(CA 개인 키, 기기 키)이 섞이지 않게 한다. 잠금 파일도 폴더 밖(`<폴더>.lock`)이다.

## 검토한 대안과 버리는 이유

- 기기 토큰 병행 유지: 계약이 없앴다(D136).
- 허용 목록을 비밀 폴더 안에 두고 그 폴더를 마운트: CA 개인 키가 입구에 노출된다.
- 파일 하나만 바인드 마운트하고 제자리 덮어쓰기: 쓰는 도중의 부분 파일을 입구가 읽을 수 있고(원자적이지 않다), 계약이 부모 폴더 마운트를 요구한다.
- 입구 uid 로 chown: 호스트에서 그 uid 로 바꾸려면 root 가 필요하다. 목록이 비밀이 아니므로 '기타' 읽기 권한으로 충분하다.
- 인증서를 `kiosk-add-device.sh` 가 항상 발급: 운영 인증서는 조직 PKI 가 발급한다(D113). 그래서 일련번호만 받는 `register` 를 둔다.
- E2E 에서 TLS 검증을 끄거나 SDK 의 비공개 필드를 바꿈: 검증을 약하게 하고 SDK 내부에 기댄다.

## 값의 출처

CA·기기 인증서 유효 30일, EC P-256: 개발·시험용 시작값이고 표준·측정 근거는 없다(운영 값은 조직 PKI 정책). 일련번호 127비트: RFC 5280 의 20옥텟 이하·양수 조건 안에서 충돌이 사실상 없는 값으로 고른 것이다(측정 안 함). 폴더 0755/파일 0644: 위 uid/gid 에서 읽기 위한 최소 권한이다(측정이 아니라 라벨의 uid/gid 에서 따짐).

## 결과와 한계

- 얻는 것: deploy 에서 기기 비밀(토큰) 발급·복제가 사라지고 폐기·회전이 목록 한 파일의 갱신이다.
- 감수: 허용 목록은 `state/` 에 있고 `secrets/` 백업에 들지 않는다. 목록이 사라지면 `register`(조직 PKI 의 발급 기록의 일련번호) 또는 개발용은 `device-certs/*.crt` 에서 다시 등록해야 한다. 이 복구 절차는 자동화하지 않았다. 입구는 목록을 읽지 못하면 기기 경로를 닫는다(fail-closed, 계약).
- 확인하지 못한 것: 위 uid/gid 는 계약 v4.0.0 라벨을 가진 로컬 디버그 이미지에서 읽었고, 허용 목록 입력(`/etc/openit/devices`)을 선언한 게시본 digest 는 이 작업에서 확인하지 못했다. 이미 열린 TLS 연결에서 목록 변경이 다음 요청부터 반영되는지는 입구(platform)의 동작이고 E2E 는 새 연결로만 본다.

## 되돌리는 조건

계약이 기기 토큰 경로를 되살리거나 허용 목록의 형식을 바꾸면 새 ADR 로 대체한다. 입구 이미지의 실행 사용자(uid/gid)가 바뀌면 권한 값을 다시 정한다.
