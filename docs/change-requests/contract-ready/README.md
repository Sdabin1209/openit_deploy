# 계약 승격 준비물 (deploy, 2026-10-29, wo6) — **승격 완료, 사본 삭제 (wo-28)**

> 이 폴더의 스키마 사본·예시·검증기·MANIFEST는 지웠다. 정본은 계약 패키지(boundary-contracts)다(공통 규칙: 스키마는 패키지에 있고 복사본을 만들지 않는다). 아래는 승격 때의 기록이다.

헤드의 `head/docs/audit/boundary-schema-promotion-2026-10-29.md` 표 deploy 행에 따라 CR-D27 초안 8개를 계약 이름으로 정리했다. 코드는 바꾸지 않았다.
`schemas/`(8개, `$id` = `<이름>.schema.json`, 2020-12), `examples/valid`, `examples/invalid`, `examples/observed`(새 스키마를 어기는 실제 라벨), `MANIFEST.json`, 검증 스크립트 `validate.py`.
검증: `python3 -W ignore docs/change-requests/contract-ready/validate.py`(jsonschema 4.x와 referencing 필요. `_common.schema.json`은 형제 `boundary-contracts`에서 읽는다, 읽기 전용).

## 한 일과 바꾼 것

- 파일 이름·`$id`·`title`을 계약 이름으로 바꿨다. 초안의 한국어 title은 description 앞머리로 옮겼다. 스키마 규칙(필드, 패턴, 모르는 키 거부)은 바꾸지 않았다.
- `_common.schema.json#/$defs/Hash`(`^sha256:[0-9a-f]{64}$`)가 이미 있어 `BuildImageResult.image_id`, `PublishResult.digest`가 그것을 참조한다(패턴은 같다). 다른 `$defs`(Id, Timestamp 등)는 맞는 필드가 없어 쓰지 않았다. revision(`^[0-9a-f]{7,40}$`)은 `_common`에 같은 정의가 없어 그대로 뒀다.
- 이웃 영역 코드는 읽지 않았다("이웃 쪽 미확인"은 MANIFEST note).

## ImageLabels와 survey-service 초안의 차이 (survey-service/docs/change-requests/schemas/image-labels.schema.json, 읽기 전용)

| 항목 | deploy ImageLabels (wo8 결정 반영) | survey-service 초안 |
|---|---|---|
| io.openit.service | 이름 패턴 `^[a-z][a-z0-9-]*$` | `const: survey-service` |
| revision | 7~40자 hex, `unknown` 거부 | hex 또는 `unknown` 허용 |
| survey-schema | 숫자 또는 `n/a` | 숫자만 |
| turn-engine, model-runtime | 선택. `vX.Y.Z` 또는 `n/a` | 필수 `vX.Y.Z`(n/a 없음) |
| langgraph | 선택, minLength 1 | 필수, `X.Y.Z`(v 없음) |
| 허용하는 io.openit.* 키 | 11개 | 7개 |
| 다른 접두사 | 무시 | 무시(값은 문자열) |

**통합(결정 wo8)**: 계약은 `ImageLabels` 하나다. survey-service의 추가 제약(service 상수, langgraph 필수·형식, turn-engine·model-runtime 필수)은 survey-service가 자기 CI에서 `allOf: [ImageLabels, {그 제약}]` 프로필로 둔다. survey 초안의 `revision: unknown` 허용은 통합 때 버린다(`publish-image.sh`가 거부하던 값). langgraph의 v 접두사 표기 통일은 아직 열려 있다(survey 초안 `1.2.15`, 다른 버전 라벨 `v0.7.6`).

## 실제 이미지 라벨의 이탈 (이 PC의 deploy-build/* 최신 빌드로 확인, 새 스키마 기준)

| 영역 | 이탈 | 라벨을 정하는 곳 | 고치는 쪽 |
|---|---|---|---|
| ops-feedback | turn-engine·model-runtime = `none` | Dockerfile ARG 기본값 `none`을 deploy가 덮지 않았다 | deploy(wo8에서 `n/a`를 넘긴다) |
| dataset-store | survey-schema = `unknown` | Dockerfile ARG 기본값을 deploy가 넘기지 않았다 | deploy(wo8에서 DEPLOY_SS_TAG의 주 버전을 넘긴다) |
| model-serving | model-runtime 에 v 접두사 없음(`0.7.7`) | deploy가 `pyproject` 버전을 그대로 넘겼다 | deploy(wo8에서 v 접두사) |
| question-authoring | survey-schema = `survey-schema-v1.0.0` | deploy가 영역 파일의 태그 문자열을 그대로 넘겼다 | deploy(wo8에서 주 버전 `1`로 변환) |
| question-authoring | turn-engine·model-runtime = `none` | Dockerfile의 LABEL에 `none`이 박혀 있다(ARG 없음) | 영역(변경 요청) |
| release-gate | boundary `2.1.1`, turn-engine `0.4.2`, model-runtime `0.7.x`: v 접두사 없음 | 영역의 `scripts/build_image.sh`가 wheel 파일 이름에서 버전을 뽑아 넘긴다(`ver()`) | 영역(변경 요청) |
| model-serving | `io.openit.service` = `model-runtime`(이미지 이름 `model-serving`) | Dockerfile LABEL 상수 | 영역 판단: 스키마는 통과시키지만 게시 이름과 다르다(검사하지 않음, 헤드가 정한다) |
| kiosk-frontend | turn-engine·model-runtime 없음 | - | 이탈 아님(wo8 결정으로 선택) |

survey-service, admin-console, model-registry는 통과한다. 위 deploy 쪽 수정은 Dockerfile ARG에 값을 넘기는 방식이라 영역 코드를 건드리지 않는다. 영역 쪽 둘이 고쳐질 때까지 `build-images.sh`·`publish-images.sh`는 question-authoring과 release-gate에서 멈춘다(의도).

## 예시의 출처

- `valid/ImageLabels.real-*`는 실제 이미지에서 뽑았다. 나머지(BuildImage*, Exposure, JobsDeclaration, Publish*, SetupEnvReport, ImageLabels의 초안 예시)는 CR-D27 초안 예시를 옮긴 것이고 실제 코드가 낸 값이라고 확인하지 않았다. 현재 어느 이미지도 `io.openit.jobs`/`exposure` 라벨을 달지 않는다.
- `publish-image.sh`의 실제 출력을 PublishResult로 대조하는 시험은 만들지 않았다(코드 변경 없음, 스크립트 실행 안 함).
