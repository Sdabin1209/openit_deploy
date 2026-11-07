# 0070. compose 밖 추론 서버는 OUT-FILE 과 서비스 토큰으로 release-gate 영역 게이트웨이에 바로 간다 (R1.5)

- 상태: 채택 (2026-11-08, wo-450). **Supersedes [0049](0049-remote-inference-reads-release-gate-via-gateway.md)**(공개 입구의 추론 기계 토큰 경로).
- 표준: boundary-contracts v4.0.4 `RUNTIME.md` R1.5(compose 밖 호출자: OUT-FILE 루트 인증서·hosts 표·SHA-256, 자기 영역 게이트웨이 출구 R1.8 로 R1.1~R1.3), R3.23(4.0.0: `Exposure.auth.kind` 의 `machine-token` 없음, 기계 호출자를 위한 공개 입구 경로 없음), `HTTP.md` I4(release-gate 읽기: `GET /v1/active-pointer`, `GET /v1/releases/{id}/bundle`), `ModelServingEnv`(`MODEL_RUNTIME_RELEASE_URL`, `MODEL_RUNTIME_RELEASE_TOKEN_FILE`).

## 맥락

ADR 0049 는 다른 호스트의 추론 서버가 **공개 입구(gateway)의 기계 토큰 경로**(`gateway-inference-token`, 공개 입구가 상류에 `gate-read-model-serving` 을 바꿔 붙임)로 release-gate 를 읽게 했다. 학습 서버의 패키지 게시도 같은 방식(`gateway-registry-publish-token`, `model-registry-write-model-lab`)이었다.
계약 4.0.0 이 이 길을 없앴다(R3.23): 공개 입구는 서비스 토큰을 대조하지 않고, 기계 호출자용 경로가 없으며, compose 밖 기계 호출자는 R1.5 hosts 표로 **받는 영역의 게이트웨이**에 바로 간다. platform 은 공개 입구 입력에서 그 넷(`gateway-inference-token`, `gateway-registry-publish-token`, `model-registry-write-model-lab`, `gate-read-model-serving`)을 뺐고(platform 488678d), deploy 도 gateway 서비스의 비밀 마운트에서 뺐다.
그런데 E2E 의 추론 서버 샌드박스(e2e.sh)는 아직 `gateway-inference-token` 이 없으면 멈추고, 단계 5L 은 "기계 토큰으로 공개 입구 active-pointer 200·bundle 200" 을 단언했다. 계약대로면 둘 다 실패한다.

## 결정

1. **길.** compose 밖 추론 서버(`compose.inference.yaml`)는 `MODEL_RUNTIME_RELEASE_URL=https://release-gate` 를 자기 영역 게이트웨이(model-serving-gw)의 loopback CONNECT 출구(`OPENIT_EGRESS_PROXY`, R1.8)로 부른다. 받는 쪽은 release-gate 영역 게이트웨이(`release-gate-gw`, 443)이고, 토큰은 release-gate 의 읽기 토큰 `gate-read-model-serving`(release-gate 의 `gate-read-tokens` 목록에 model-serving 으로 있다)을 **받는 서비스가 직접 대조한다**(R3.23). 신뢰 루트는 OUT-FILE 의 `root_ca.crt`(step-ca 루트) 하나다(`SSL_CERT_FILE`).
2. **OUT-FILE.** deploy 는 compose 밖 호출자에게 `scripts/export-out-files.sh` 로 루트·hosts 표(`<주소> release-gate`)·`SHA256SUMS` 를 준다(기존 도구 재사용, 새 도구 없음). 받는 쪽은 `sha256sum -c` 로 대조한 뒤 쓴다.
3. **이름 풀이.** 다른 서버: `compose.inference.remote.yaml`(`INFERENCE_RELEASE_ADDR` = hosts 표의 주소, 주 서버는 `placement_ports: {release-gate: 443}` 로 release-gate pod 의 443 을 게시). 같은 호스트: `compose.inference.samehost.yaml`(주 서버 프로젝트의 internal 망 `inference-in` 에 external 로 붙고, 그 망에는 release-gate pod 만 별칭 `release-gate` 로 있다; Docker DNS).
4. **E2E 샌드박스(같은 PC의 "다른 호스트 역할").** 같은 호스트 배치(3의 samehost)로 띄운다. e2e.sh 는 제품을 띄운 뒤 OUT-FILE 을 내보내고(hosts 표 주소 = release-gate-net 의 inference-in 주소) 대조한 뒤 그 루트로 추론 서버를 띄운다. `gateway-inference-token` 검사·복사를 없앤다.
5. **단계 5L 단언.** (0) OUT-FILE SHA-256 대조·hosts 표 `release-gate` 줄. (1) 추론 서버 `/readyz` 200·`status=ready`(release 도달). (2) 추론 서버 pod 의 네트워크 공간에서 같은 출구(R1.8)로 `https://release-gate` 를 OUT-FILE 루트만 믿고 부른다: 서비스 토큰 active-pointer 200·bundle 200(본문 있음), 무토큰 401·틀린 토큰 401(받는 서비스의 R3.23). (3) 같은 서비스 토큰을 공개 입구에 내면 200 이 아니다(401 또는 404: 기계 경로 없음). (4) release-gate(pod·앱·영역 게이트웨이)는 호스트 포트가 없다.
6. **토큰 정리.** `gen-secrets.sh` 는 `gateway-inference-token`, `gateway-registry-publish-token` 을 더 만들지 않는다. compose.yaml 최상위 비밀 `gateway-inference-token`, `gateway-registry-publish-token`, `model-registry-write-model-lab`(어느 서비스도 마운트하지 않음)을 지운다. `model-registry-write-model-lab` 파일은 계속 만든다(`model-registry-write-tokens` 목록 값의 재료).

## 왜

- 계약이 정한 유일한 길이다(R1.5·R3.23). 우회(공개 입구에 기계 경로를 다시 열기, 시험용 게시)는 계약 위반이다.
- 토큰 대조를 받는 서비스가 하므로(3.4.4 이후) 공개 입구가 토큰을 바꿔 붙이는 중간 단계가 없다. 원격 호스트에 가는 토큰은 읽기 권한(I4 읽기)뿐인 release-gate 서비스 토큰이다.
- E2E 를 같은 호스트 배치로 하는 이유: 다른 서버 배치는 release-gate pod 의 **443** 을 호스트에 게시해야 한다(계약 URL `https://release-gate` 는 443, 출구 허용 목록 `Exposure.egress` 도 `release-gate:443`). 시험 PC 에서 443 을 고정 게시하면 고정 포트 금지·동시 실행 규칙(CLAUDE.md)에 어긋나고, Docker 가 배정한 포트는 URL·허용 목록과 맞지 않는다. 같은 호스트 배치는 제품 compose 에 게시 포트를 하나도 더하지 않는다(시험용 문 없음). 다른 서버 경로(hosts 표 + 443 게시)의 실제 기동은 `scripts/test-split-pki-playbook.sh` 가 본다.
- 5L 의 탐침을 추론 서버 pod 의 공간 + 그 출구로 부르는 이유: 서버가 실제로 쓰는 길(자기 출구 -> 받는 영역 게이트웨이)과 같아, 출구 허용 목록·이름 풀이·TLS 루트·토큰을 한 번에 본다. deploy 는 영역 컨테이너 안에 들어가지 않는다(별도 클라이언트 컨테이너, `e2e_sandbox.exec_py`).

## 검토한 대안과 버리는 이유

- **release-gate 영역 게이트웨이를 Docker 배정 호스트 포트로 게시하고 hosts 표에 적기**: 계약 URL·출구 허용 목록이 443 이라 배정 포트로는 부를 수 없다. URL 에 포트를 넣으면 `ModelServingEnv`·Exposure 와 어긋난다. 443 고정 게시는 시험 PC 의 고정 포트다. 버린다.
- **공개 입구의 기계 토큰 경로 유지(0049)**: 계약 4.0.0 R3.23 위반, platform 이 입력에서 뺐다. 버린다.
- **E2E 에서 OUT-FILE 없이 step-ca 루트를 바로 넘기기(이전 e2e.sh)**: 동작은 같지만 R1.5 의 대조 단계(SHA-256)를 시험이 거치지 않는다. 운영과 같은 도구로 내보내고 대조하는 쪽을 고른다.

## 결과

- 얻는 것: 원격 추론 서버의 운영 경로와 E2E 의 경로가 계약 R1.5 하나로 같다. 공개 입구에 기계 경로가 없다는 것을 E2E 가 단언한다. 쓰이지 않는 기계 토큰 두 개와 마운트되지 않는 비밀 정의 셋이 없어졌다.
- 감수하는 것: (1) E2E 는 같은 호스트 배치만 실행한다(다른 서버 경로는 분리 배치 시험 몫). (2) 기존 설치의 `secrets/tokens/gateway-inference-token`·`gateway-registry-publish-token` 파일은 지우지 않는다(gen-secrets 는 남은 파일을 건드리지 않는다). 운영자가 지운다(runbook 9-1b). (3) **학습 서버의 패키지 게시(model-lab -> model-registry, I3)** 는 같은 R1.5 길(OUT-FILE `<주소> model-registry` + `placement_ports: {model-registry: 443}` + 쓰기 토큰 `model-registry-write-model-lab` 을 model-registry 가 직접 대조)이 필요하다. 이 결정에서는 E2E_GPU 경로를 고치지 않았다. 이어진 결정은 [ADR 0071](0071-training-server-publish-to-model-registry-r15.md)(받는 쪽은 확인, 출구는 model-lab 선언에 model-registry 가 없어 막힘, CR-450). (4) 번들 크기·전송 시간은 측정하지 않았다. 서버 쪽 읽기 상한은 model-runtime 의 `MODEL_RUNTIME_RELEASE_READ_TIMEOUT_S` 다.

## 되돌리는 조건

- 계약이 공개 입구에 기계 호출자 경로를 다시 정하면 새 ADR 이 이것을 대체한다.
- 시험 PC 에서도 443 을 안전하게 게시할 수 있는 격리(별도 네트워크 이름공간의 호스트 역할 등)가 생기면 E2E 를 다른 서버 배치(remote overlay)로 바꾼다.
