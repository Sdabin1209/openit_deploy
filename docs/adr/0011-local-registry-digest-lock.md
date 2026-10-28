# 0011. 서버 안의 로컬 레지스트리와 이미지 digest 잠금

- 상태: 채택 (D24)
- 날짜: 2026-10-28

## 맥락

배포 단위는 영역별 이미지이고, 코드 축 롤백이 되어야 하며(이전 이미지로 복귀), 운영 서버는 외부 서비스 의존을 줄여야 한다(사용자 제약). 영역 CI는 아직 없고 제출 방법(PR인지 API인지)은 미정이다.

## 결정

`registry:2`를 별도 Compose 프로젝트(`compose.registry.yaml`, 운영은 `127.0.0.1:5000`)로 상시 띄운다. `build-images.sh`가 영역 리포지토리를 `git archive HEAD`로 꺼내 빌드하고, `publish-images.sh`가 push한 뒤 레지스트리 digest와 push 출력의 digest가 같은지 확인하고 `locks/images.lock`을 갱신한다. `compose.yaml`은 `<레지스트리>/openit/<영역>@<digest>`로만 이미지를 참조하고 태그를 쓰지 않는다(`check-compose.sh`가 검사). 이전 잠금은 `locks/history/`에 남긴다. 외부 이미지(gateway, registry, 유틸, postgres)도 `@sha256:`로 고정한다.

## 왜 (따른 표준과 근거)

- 이미지 digest 고정은 재현 가능한 배포의 표준 관행이다: 태그는 바뀔 수 있고 digest는 내용 주소다. 롤백은 잠금을 이전 것으로 되돌리고 `up.sh`를 다시 돌리면 끝나며 E2E가 실제로 돈다(docs/design.md 2절).
- 서버 안 레지스트리는 외부 레지스트리 장애·인터넷·인증에 영향받지 않는다(D24 근거).
- `registry:2`는 인증·TLS가 없어 127.0.0.1에만 바인드한다. 운영 도메인·push 인증은 미정이다(compose.registry.yaml 머리말, docs/ci.md).

## 검토한 대안과 버리는 이유

- 외부 레지스트리(GHCR 등): 인터넷·인증 의존이 생긴다(D24).
- Kubernetes: 이 결정의 범위 밖이며 ADR 0001이 다룬다. digest 고정 방식은 그대로 이식된다(D24).
- 태그로 참조: 같은 태그가 다른 내용을 가리킬 수 있어 롤백과 감사가 흐려진다. 버린다.

## 결과

- 이 서버의 레지스트리 볼륨(`registry-data`)이 사라지면 잠금의 digest 이미지를 다시 내려받을 곳이 없다: 이미지는 같은 커밋·태그에서 다시 빌드해야 하며 digest는 달라질 수 있다(빌드 재현성은 확인한 적 없음).
- Docker Desktop(WSL)은 임의 호스트 포트에 데몬이 닿지 못해 시험은 레지스트리만 `0.0.0.0`의 빈 포트에 잠시 띄운다(docs/design.md 3절, 확인한 환경 제약).

## 되돌리는 조건

영역 CI가 외부에서 빌드하게 되거나 서버가 둘 이상이 되면 외부 레지스트리를 쓴다. 잠금 파일 방식은 그대로 쓴다.

## 후속: 레지스트리 호출 timeout (2026-10-28, FAULT_POLICY 4)

`publish-images.sh`와 `publish-image.sh`는 레지스트리 호출에 상한을 둔다: push 전 `/v2/` 확인(연결 3초, 전체 5초), digest 확인 HEAD(전체 15초), `docker push` 전체 900초. 이유: 레지스트리를 pause하면 연결은 되고 응답이 없어(E2E 5g) 상한이 없던 게시가 바깥 timeout까지 매달렸다. push 전 확인이 5초에 스스로 실패하게 한다(pause 중 curl이 5초에 종료 코드 28로 끊기는 것은 이 PC에서 확인). 값은 모두 측정하지 않은 판단이며 환경 변수 `PUBLISH_CONNECT_TIMEOUT`, `PUBLISH_PROBE_TIMEOUT`, `PUBLISH_HEAD_TIMEOUT`, `PUBLISH_PUSH_TIMEOUT`으로 바꾼다. `docker push`는 연결 timeout 옵션이 없어 전체 상한만 둔다(이미지 크기별 소요는 측정 안 함).
