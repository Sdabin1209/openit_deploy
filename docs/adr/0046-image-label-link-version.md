# 0046. 영역 이미지에 들어간 link 버전을 라벨 `io.openit.link` 로 기록한다 (제안)

- 상태: 제안 (계약 변경이 필요해 헤드의 결정을 기다린다)
- 날짜: 2026-10-30

## 맥락

통신 기반 라이브러리 link(D118) v0.1.0 이 나왔고 영역 이미지의 받는 쪽은 그 위에서 돈다. 어느 이미지에 어느 link 버전이 들어갔는지 알아야 버전표 점검(`check-versions.sh`)이 어긋난 이미지를 잡을 수 있다. 기존 라벨 키는 계약 `ImageLabels` 가 정한다(`io.openit.service`, `revision`, `contracts.boundary`, `contracts.survey-schema`, `model-runtime`, `variant`, `app-version`, `langgraph`, `jobs`, `exposure`). 확인한 것: v3.1.1 의 `ImageLabels` 는 알 수 없는 `io.openit.*` 키를 거부한다(`propertyNames`), `io.openit.link` 는 목록에 없다.

## 결정 (제안)

라벨 키 `io.openit.link`(값: 태그 형식 `vMAJOR.MINOR.PATCH`, link 를 쓰지 않는 이미지는 `n/a`)를 영역 이미지에 기록한다. 기준 버전은 `scripts/lib.sh` 의 `DEPLOY_LINK_TAG`(v0.1.0) 한 곳이다. 각 영역의 build-image 가 이 값을 `--build-arg`가 아니라 영역의 의존 잠금에서 읽어 라벨로 단다(영역 내부 일이다: deploy 는 영역의 빌드 구조를 모른다, 구조 규칙 1). 점검은 `check-versions.sh` 가 라벨 `io.openit.link` 를 `DEPLOY_LINK_TAG` 와 대조하는 것으로 한다(구현은 계약이 키를 허용한 뒤).

## 왜

- 표준: 이미지 라벨 키는 계약 `ImageLabels` 와 같은 `io.openit.*` 이름공간(D50)에 두어 기존 관문(`publish-image.sh` 의 ImageLabels 검사)이 한 번에 본다.
- `io.openit.contracts.boundary` 와 `io.openit.model-runtime` 이 이미 같은 목적(이미지에 들어간 의존 버전의 기록)으로 있다. 같은 모양을 쓴다.

## 검토한 대안

- 계약 밖 이름공간(예: `openit.link`)의 라벨: 계약이 무시하므로 지금 당장 쓸 수 있으나 관문이 보지 못해 한 영역이 빠뜨려도 모른다. 버린다.
- `io.openit.contracts.boundary` 값에 합치기: 값 형식(`vX.Y.Z`)을 깨 계약 필드의 뜻이 섞인다. 버린다.
- 라벨 없이 `images.env` 의 도장(`bc=,mr=`)에 `lk=` 를 더한다: 도장은 deploy 가 쓴 기록이고 이미지가 실제로 가진 것을 말하지 않는다(ADR 0042 가 라벨을 정본으로 삼은 이유). 버린다.

## 결과

얻는 것: link 버전이 어긋난 이미지를 라벨로 잡는다. 감수하는 것: 계약 변경이 먼저다. 변경 요청: `docs/change-requests/CR-U400-image-label-link.md`. 그 전까지 deploy 는 `DEPLOY_LINK_TAG` 만 두고(호스트 `.venv` 설치용, `prepare-host.sh venv`) 이미지 점검은 하지 않는다(**검증하지 않았다**).

## 되돌리는 조건

헤드가 라벨 대신 다른 기록 위치를 정하면 이 ADR 을 새 ADR 이 대체한다.
