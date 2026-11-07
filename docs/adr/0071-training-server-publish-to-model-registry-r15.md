# 0071. 학습 서버의 패키지 게시는 R1.5 로 model-registry 영역 게이트웨이에 간다 (받는 쪽만 갖추고 출구는 model-lab 선언을 기다린다)

- 상태: 채택(부분). 받는 쪽·OUT-FILE·시험은 채택, 학습 서버 쪽 출구와 배치 게시 포트는 보류(`docs/change-requests/CR-450-model-lab-egress-model-registry.md`). 2026-11-08, wo-450.
- 표준: boundary-contracts v4.0.4 `RUNTIME.md` R1.5(compose 밖 호출자: OUT-FILE, 자기 영역 게이트웨이 출구 R1.8), R3.23(공개 입구에 기계 경로 없음, 받는 서비스가 서비스 토큰 대조), R3.24(권한 밖 403), `HTTP.md` I3(`POST /v1/packages`, 쓰기 역할 model-lab), `CONVENTIONS.md` 13절(compose 밖 영역 컴포넌트도 자기 영역 게이트웨이를 거친다, `Exposure.egress` 가 출구 허용 목록의 정본).
- 관련: ADR 0070(추론 서버의 같은 설계).

## 맥락

학습 서버의 model-lab 파이프라인은 학습·평가한 패키지를 주 서버의 model-registry 에 게시한다. 예전에는 공개 입구의 기계 토큰 경로(`gateway-registry-publish-token`, 공개 입구가 `model-registry-write-model-lab` 을 붙임)였고, 계약 4.0.0 이 이 경로를 없앴다(R3.23, ADR 0070 에서 토큰 정리). 남는 길은 R1.5 다.

## 결정

1. 길은 ADR 0070 과 같다: 학습 서버 쪽 호출자 -> 같은 서버의 model-lab 영역 게이트웨이 출구(R1.8) -> OUT-FILE hosts 표의 `<주소> model-registry` -> model-registry 영역 게이트웨이(443, 서비스 이름 인증서, OUT-FILE 루트로 검증) -> model-registry. 쓰기 토큰은 `secrets/tokens/model-registry-write-model-lab`(gen-secrets 의 `model-registry-write-tokens` 목록 `model-lab=` 항목과 같은 값)이고 **model-registry 가 직접 대조한다**(게이트웨이는 대조하지 않는다, 3.4.4).
2. OUT-FILE 은 기존 `scripts/export-out-files.sh --host "<주소> model-registry"` 로 낸다(도구 변경 없음).
3. 시험 `scripts/test-registry-publish-reach.sh`(Docker, 고정 포트 없음, 호스트 게시 없음): 같은 호스트의 별도 망을 "다른 서버" 로 두고 호출자 pod 가 hosts 표를 `--add-host` 로 받는다. 실제 model-registry 이미지와 platform area-gateway 이미지로 (1) OUT-FILE 대조 (2) 받는 서비스의 토큰 대조(무토큰·틀린 토큰 401, 읽기 토큰 게시 403, 쓰기 토큰 게시는 역할 통과) (3) 호출자 출구의 판정이 model-lab 의 `Exposure.egress` 선언과 같음을 단언한다. 선언에 `model-registry` 가 있으면 출구를 거친 게시까지 단언하고 0, 없으면 종료 77(검증 안 함).
4. 공개 입구에 게시 경로가 없음(쓰기 토큰의 `POST /v1/packages` 가 401/404)은 실제 공개 입구를 띄우는 `scripts/test-inference-location.sh` 에 단언을 더한다.
5. **보류:** (a) 학습 서버 쪽 model-lab 영역 게이트웨이의 compose 파일, (b) 주 서버에서 model-registry 영역 게이트웨이 443 게시(배치 정의가 compose 밖 호출자를 표현해야 한다), (c) 같은 호스트 배치용 external 망(ADR 0070 의 `inference-in` 에 해당). 셋 다 CR-450 의 결정(출구 선언과 학습 서버 게이트웨이의 Exposure 출처) 뒤에 정한다.

## 왜

- 계약이 정한 유일한 길이다(R1.5·R3.23). 공개 입구에 경로를 다시 열거나 시험용 게시로 대신하는 것은 우회다.
- 출구 허용 목록은 영역의 선언(`Exposure.egress`)이 정본이다. 측정으로 확인했다: 지금 선언으로는 출구가 `model-registry` 를 403 으로 거절한다(CR-450 의 확인 기록). deploy 가 다른 선언을 만들어 주면 영역 선언의 사본이 된다(구조 규칙 1·6). 그래서 deploy 쪽에서 할 수 있는 것(받는 쪽·OUT-FILE·시험)만 하고 나머지는 변경 요청으로 넘긴다.
- (b)·(c) 를 지금 만들지 않는 이유: 출구가 막힌 동안 이것들은 쓰는 쪽이 없는 문(게시 포트·외부 망)이 된다. 계약·선언이 정해지기 전에 제품에 문을 더하지 않는다.
- 시험이 선언을 읽어 판정을 고르는 이유: 기대값을 손으로 적으면 model-lab 이 선언을 고친 뒤 시험이 틀린 쪽을 단언한다. 선언이 바뀌면 시험 수정 없이 출구를 거친 게시를 단언하게 된다.
- 쓰기 토큰 게시를 빈 묶음으로 보는 이유: 여기서 보려는 것은 길과 역할 판정이다. 실제 패키지의 게시 성공·멱등·해시 검증은 E2E 단계 3(`publish_packages`)이 본다.

## 검토한 대안과 버리는 이유

- **시험에서 model-registry 를 포함한 출구 선언을 deploy 가 만들어 쓰기**: 영역 선언을 꾸며 낸 시험용 문이다. 버린다.
- **출구 없이 hosts 표로 바로 부르기(영역 안 호출로 보기)**: 계약 문장(CONVENTIONS 13절)과 다르다. 계약이 그렇게 정하면(CR-450 제안 2) 이 ADR 을 대체한다.

## 결과

- 얻는 것: 받는 쪽(OUT-FILE -> model-registry 영역 게이트웨이 -> 서버의 토큰 대조)이 실제 이미지로 확인된다. 막힌 지점이 측정과 함께 기록됐고, 풀리면 같은 시험이 그대로 검증한다.
- 감수하는 것: 학습 서버의 게시는 아직 운영 길이 없다. `test-registry-publish-reach.sh` 는 종료 77 이라 자체 점검 묶음(`self-checks.list`)에 넣지 않았다(넣으면 묶음 전체가 77 이 되어 E2E 준비가 멈춘다). CR-450 이 풀리면 목록에 넣는다. `E2E_GPU=1` 단계 3 은 이 사유로 멈춘다.

## 이후 (2026-11-08)

- CR-450 은 제안 1 로 반영됐다(model-lab 6648a4d: Exposure.egress 에 model-registry). `test-registry-publish-reach.sh` 가 출구를 거친 게시 길까지 단언해 rc=0 이 됐고 `self-checks.list` 에 넣었다.
- 새 자기 연결(model-registry -> model-registry)에서 `test-egress-edges.sh` 가 503 으로 실패했다. 원인은 시험 배선이다: 부르는 쪽 pod 에도 받는 쪽과 같은 별칭(model-registry)을 줘서 Docker DNS 가 이름을 두 pod 에 나눠 풀었고(확인: 같은 별칭 두 pod 에서 getaddrinfo 가 두 주소), 출구가 상류 없는 자기 pod 의 게이트웨이로 갔다. 이 자기 연결이 쓰이는 곳은 R1.5(학습 서버의 같은 영역 게이트웨이 -> 주 서버의 받는 영역 게이트웨이)이고 그 길에서 이름은 받는 쪽 한 곳으로만 풀린다(RUNTIME IN-NAME, R1.5 hosts 표). 그래서 부르는 쪽 pod 에는 별칭을 주지 않게 고쳤다(단언은 그대로 `GET 200 ok`). 주 compose 는 바뀌지 않는다: compose 안의 model-registry 는 자기 영역 서버를 출구로 부르지 않는다(영역 안 호출, CONVENTIONS 13절).
- 보류였던 (a) 학습 서버 쪽 게이트웨이 compose, (b) model-registry 443 배치 게시(Placement 가 compose 밖 호출자를 표현), (c) 같은 호스트 external 망은 아직 만들지 않았다. 새 ADR 로 정한다.

## 되돌리는 조건

- CR-450 이 결정되면 새 ADR 이 이것을 대체해 (a)~(c) 를 정한다.
