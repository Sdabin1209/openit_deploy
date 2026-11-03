# 변경 요청: 영역 게이트웨이 설정 생성기를 이미지 쪽에서 받는다

작성: deploy, 2026-11-04. 받는 곳: 헤드(영역 사이 계약), platform 영역.

## 문제
배치(deploy)는 영역마다 영역 게이트웨이(platform 이미지)를 띄우고 설정(`/etc/envoy/envoy.yaml`, `sds.yaml`)을 그 영역의 Exposure 선언(이미지 라벨 `io.openit.exposure`)에서 만들어 줘야 한다.
지금 설정 생성기 `platform/scripts/gen-area-gateway-config.py` 는 platform 리포의 스크립트다. deploy 가 그 파일을 직접 부르면 이웃 영역의 코드·파일 구조에 기대는 것이다(워크스페이스 규칙: 영역끼리 코드를 가져오지 않는다, 구조 규칙 1). 이미지는 순수 Envoy 라 그 안에는 생성기가 없다.

## 요청 (제안, 결정은 헤드·platform)
platform 이 생성기를 **이미지로 배포**한다. 예: `area-gateway` 이미지에 설정 생성 명령을 넣거나 같은 리포가 `area-gateway-config` 이미지를 따로 낸다.
- 입력: 파일 마운트로 Exposure JSON(`/in/exposure.json`)과 인자(`--upstream 127.0.0.1:<앱 포트>`, 필요하면 `--route-upstream`), 인증서·키 위치.
- 출력: `/out/envoy.yaml`, `/out/sds.yaml`. 종료 코드 0 이면 완성본, 아니면 이유를 표준 오류에 낸다. 입력은 Exposure 계약 스키마로 검증한다(CONVENTIONS 3절).
- 라벨은 기존 규칙(`io.openit.service`, `io.openit.revision` 등)을 따른다.

deploy 는 그 이미지를 `docker run --rm` 으로 한 번 돌려 영역마다 설정을 만들고(`scripts/gen-gateways.sh`), 만든 파일을 영역 게이트웨이 컨테이너에 읽기 전용으로 마운트한다. 같은 입력에는 같은 출력이다(멱등).

## 그 전까지 deploy 가 하는 것
생성기 호출만 비워 두고 나머지(영역 게이트웨이 컨테이너 정의, 같은 네트워크 공간 배치, `OPENIT_EGRESS_PROXY=http://127.0.0.1:3128`, 인증서 마운트)를 만든다. 생성기 이미지가 나오면 호출을 채운다.
