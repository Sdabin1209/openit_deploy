# CR-D28: 이미지 라벨 두 영역의 수정 (question-authoring, release-gate)

- 상태: 제안
- 보내는 곳: deploy -> head (영향: question-authoring, release-gate 영역)
- 근거: 계약 ImageLabels(docs/change-requests/contract-ready/schemas/ImageLabels.schema.json), ADR 0035. deploy는 `build-images.sh`와 `publish-image(s).sh`에서 게시 전에 이 스키마로 검사한다.

deploy가 Dockerfile ARG로 넘기는 값은 deploy에서 고쳤다(ops-feedback, dataset-store, model-serving, question-authoring의 survey-schema). 아래 둘은 영역 파일이 값을 정하므로 영역이 고친다.

| 영역 | 지금 | 기대(ImageLabels) | 어디 |
|---|---|---|---|
| question-authoring | `io.openit.turn-engine=none`, `io.openit.model-runtime=none` | 라벨을 달지 않거나 `n/a` | Dockerfile LABEL 상수 |
| release-gate | `contracts.boundary=2.1.1`, `turn-engine=0.4.2`, `model-runtime=0.7.x` (v 접두사 없음) | `v2.1.1`, `v0.4.2`, `v0.7.x` | `scripts/build_image.sh`의 `ver()`가 wheel 파일 이름에서 뽑은 값을 그대로 넘긴다 |

이 둘이 고쳐지기 전에는 deploy의 `build-images.sh`가 두 영역에서 멈춘다. 병합 순서는 헤드가 정한다.
