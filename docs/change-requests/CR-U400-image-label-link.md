# 변경 요청 (deploy -> 헤드): ImageLabels 에 `io.openit.link` 추가

- 대상: boundary-contracts `ImageLabels` (v3.1.1 기준)
- 무엇이 부족한가: link(통신 기반 라이브러리, D118)를 쓰는 영역 이미지에 어느 link 버전이 들어갔는지 적을 라벨 키가 없다. v3.1.1 `ImageLabels` 는 알 수 없는 `io.openit.*` 키를 거부하므로(`propertyNames`) 영역이 임의로 달 수 없다.
- 제안: 선택 라벨 `io.openit.link`, 값 패턴은 `io.openit.model-runtime` 과 같은 태그 형식(`^v[0-9]+\.[0-9]+\.[0-9]+$`) 또는 `n/a`. 근거와 대안: deploy ADR 0046.
- 받은 뒤 deploy 가 할 일: `check-versions.sh` 에 `DEPLOY_LINK_TAG` 대조 추가. 그 전까지 이 점검은 하지 않는다.
- 2026-10-30 헤드 결정: CR-U400-image-label-link 는 대장에 올렸다. 계약 고정 중이라 지금은 link 버전 라벨 점검을 하지 않는다. 링크 기준은 v0.2.0(추가만).
