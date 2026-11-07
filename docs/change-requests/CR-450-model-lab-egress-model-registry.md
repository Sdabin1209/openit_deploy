# 변경 요청: 학습 서버의 패키지 게시 길이 model-lab 출구 선언에서 막힌다 (deploy -> 헤드, model-lab)

- 요청자: deploy (wo-450), 대상: model-lab 의 Exposure 선언(model-registry 이미지 라벨 `io.openit.exposure`)과, 필요하면 boundary-contracts `CONVENTIONS.md` 13절·`Exposure.egress` 설명
- 상태: 제안(결정 아님)
- 관련: deploy ADR 0071, `scripts/test-registry-publish-reach.sh`

## 무엇이 부족한가

계약 4.0.0 R3.23 이 공개 입구의 기계 경로를 없앴으므로, 학습 서버의 model-lab 파이프라인이 주 서버의 model-registry 에 게시(HTTP.md I3 `POST /v1/packages`, 쓰기 역할 model-lab)하는 길은 R1.5 하나다: OUT-FILE(루트·hosts 표 `<주소> model-registry`·SHA-256) + 서비스 토큰 + **같은 서버에 둔 자기 영역 게이트웨이의 출구(R1.8)**. CONVENTIONS 13절도 "compose 밖(R1.5)에서 도는 영역 컴포넌트도 같은 서버에 둔 자기 영역 게이트웨이를 거친다"고 한다.

그런데 model-lab 영역이 낸 Exposure 선언(model-registry 이미지 라벨, 영역 게이트웨이 하나의 선언)의 `egress` 는 `["dataset-store", "question-authoring", "ops-feedback", "release-gate", "external:backup"]` 이고 `model-registry` 가 없다. 그래서 학습 서버에 이 선언으로 model-lab 영역 게이트웨이를 두면 출구가 `CONNECT model-registry:443` 을 403(`EGRESS_DENIED`)으로 거절한다.

확인한 것(이 PC, 2026-11-08, platform area-gateway 95ea138 이미지, model-registry 67b34de 이미지): `scripts/test-registry-publish-reach.sh` 에서
- 받는 쪽은 된다: OUT-FILE hosts 표와 루트로 model-registry 영역 게이트웨이에 닿고, model-registry 가 직접 토큰을 대조한다(무토큰·틀린 토큰 401, 읽기 토큰 게시 403, 쓰기 토큰 게시는 역할 통과 후 본문 판정 400).
- 출구 판정은 선언대로다: 선언 밖 `survey-service` 403, 선언 밖 `model-registry` 403.

## 왜 deploy 가 고칠 수 없나

Exposure 는 영역(model-lab)이 이미지 라벨로 내는 선언이고 deploy 는 그것을 꺼내 게이트웨이에 줄 뿐이다(ADR 0043·0065). deploy 가 다른 선언을 만들어 주면 영역의 선언을 사본으로 바꾸는 것이다. 또 학습 서버에서 도는 model-lab 컴포넌트(파이프라인)의 이미지·선언을 deploy 는 갖고 있지 않다.

## 제안 (헤드가 고른다)

1. **model-lab 이 `egress` 에 `model-registry` 를 더한다.** INTERFACES "한눈에" 표에서 model-lab 은 I3 의 "쓰는 쪽"이므로 Exposure.egress 의 허용 범위(표의 호출 관계) 안이다. 계약 변경 없이 model-lab 이미지 라벨만 바뀐다. 같은 서버(compose 안)에서는 이 출구 항목이 쓰이지 않는다(영역 안 호출).
2. 또는 계약이 "compose 밖에서 도는 영역 컴포넌트가 **같은 영역의** 서버를 부를 때"를 따로 정한다(출구를 거치지 않고 R1.5 hosts 표로 받는 영역 게이트웨이에 바로 등). 이 경우 CONVENTIONS 13절의 위 문장을 고친다.
3. 어느 쪽이든 학습 서버에 둘 model-lab 영역 게이트웨이의 Exposure 를 **어느 이미지의 라벨**에서 읽는지(지금은 model-registry 이미지 라벨이 model-lab 영역의 유일한 선언이다)를 model-lab 이 정해 준다.

## 그때까지

- deploy 는 받는 쪽과 OUT-FILE 을 갖춰 두고(`export-out-files.sh --host "<주소> model-registry"`), `test-registry-publish-reach.sh` 는 출구 단계에서 종료 77(검증 안 함, 통과 아님)로 끝난다. 선언에 `model-registry` 가 생기면 같은 시험이 출구를 거친 게시까지 단언하고 0 으로 끝난다(시험 수정 불필요).
- E2E 의 `E2E_GPU=1` 단계 3 은 계속 이 사유로 멈춘다. 기본 경로(시험 대역 게시)는 영향이 없다.
- 다른 서버 배치에서 model-registry 영역 게이트웨이의 443 을 게시하려면 배치 정의(`schemas/Placement.schema.json`)가 compose 밖 호출자를 표현해야 한다(지금 `placement_ports` 는 다른 서버의 **compose 서비스**가 부르는 서비스만 받는다). 위 결정 뒤 deploy 가 ADR 로 정한다.
