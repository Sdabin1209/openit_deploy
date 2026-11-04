# 변경 요청: 추론 서버가 release-gate 를 부르는 길(영역 게이트웨이 나가는 쪽)

작성: deploy, 2026-11-04. 받는 곳: 헤드(영역 사이 계약).

## 발견 (정적 시험 `scripts/test_inference_egress.py`)
model-runtime 이미지의 Exposure(`io.openit.exposure`)의 egress 는 `["release-gate"]` 다. 영역 게이트웨이의 나가는 쪽은 선언된 `release-gate:443` 으로만 CONNECT 터널을 연다(그 밖은 403 EGRESS_DENIED, RUNTIME R1.8·R6.2).
그런데 다른 호스트의 추론 서버(`compose.inference.yaml`)는 `MODEL_RUNTIME_RELEASE_URL=${RELEASE_URL}` 로 **공개 입구의 주소**(예 `https://kiosk.hospital.local:8443`)를 부른다. 이 호스트·포트는 egress 에 없으므로 영역 게이트웨이가 막는다. 시험이 이 어긋남을 잡아 실패한다.

## 선택지 (결정은 헤드)
1. 추론 서버가 `https://release-gate`(포트 443)를 부른다. deploy 가 추론 서버 호스트의 `extra_hosts` 로 `release-gate:<공개 입구 주소>` 를 주고, 공개 입구는 그 주소의 **443** 에서 기계 토큰 경로를 받으며 인증서 SAN 에 `release-gate` 를 넣는다. 공개 입구의 포트가 8443 이면 안 된다.
2. 모델 서버 Exposure.egress 에 공개 입구 호스트(`<게이트웨이 이름>:443`)를 선언한다(model-runtime 변경, 설치처마다 이름이 달라 선언 값이 아니라 배포 값이어야 한다는 문제가 남는다).
3. R1.5 의 OUT-FILE hosts 표(`<주소> <서비스 이름>`)로 compose 밖 호출자에게 `release-gate` 이름을 알려 준다(선택지 1 의 일반화).

## 지금 상태
`compose.inference.yaml` 은 platform 이미지(area-gateway, step-ca cert)로 바꿨지만 `RELEASE_URL` 이 공개 입구 주소라서 위 불일치가 남아 있다. E2E 의 추론 서버 단계(`INFERENCE_*` 호출)도 같은 값을 쓴다. 결정 전에는 E2E 를 돌리지 않는다.
