# 변경 요청: PublishRequest.service 에 platform 이미지 이름을 넣는다

작성: deploy, 2026-11-04. 받는 곳: 헤드(영역 사이 계약).

## 문제
배치(deploy)가 platform 영역의 이미지(영역 게이트웨이 `area-gateway`, 공개 입구 `public-ingress`, 감시 `monitoring`, 백업 저장소 `backup-store`, 인증기관 `step-ca`)를 레지스트리에 올려 digest 잠금(`locks/images.lock`)에 적어야 한다(D24).
`scripts/publish-image.sh` 는 계약 `PublishRequest` 로 요청을 검증하는데, 계약 v3.4.7 의 `PublishRequest.service` enum 은 `survey-service … model-serving-gpu` 뿐이라 platform 이미지 이름을 거부한다.
enum 을 우회(검증 끄기, 이름 바꾸기)하지 않는다.

## 요청
`PublishRequest.service` enum 에 platform 이 낸 이미지 이름을 더한다: `area-gateway`, `public-ingress`, `monitoring`, `backup-store`, `step-ca`(platform 리포의 `scripts/build-image.sh` variant 와 같은 이름). 필요하면 `BuildImageRequest` 도 platform 의 variant 를 같은 규칙으로 읽는다(지금 `variant` 는 `^[a-z0-9-]+$` 라 이미 받는다).

## 그 전까지
영역 게이트웨이 컨테이너 정의와 설정 입력(`scripts/gen-gateways.py`, 시험 `scripts/test_gen_gateways.py`)은 만들어 두고, 이미지 게시만 이 변경을 기다린다.
