# 계약 승격 준비물 (deploy, 2026-10-29, wo6)

헤드의 `head/docs/audit/boundary-schema-promotion-2026-10-29.md` 표 deploy 행에 따라 CR-D27 초안 8개를 계약 이름으로 정리했다. 코드는 바꾸지 않았다.
`schemas/`(8개, `$id` = `<이름>.schema.json`, 2020-12), `examples/valid`, `examples/invalid`, `examples/observed`, `MANIFEST.json`, 검증 스크립트 `validate.py`.
검증: `python3 -W ignore docs/change-requests/contract-ready/validate.py`(jsonschema 4.x와 referencing 필요. `_common.schema.json`은 형제 `boundary-contracts`에서 읽는다, 읽기 전용).

## 한 일과 바꾼 것

- 파일 이름·`$id`·`title`을 계약 이름으로 바꿨다. 초안의 한국어 title은 description 앞머리로 옮겼다. 스키마 규칙(필드, 패턴, 모르는 키 거부)은 바꾸지 않았다.
- `_common.schema.json#/$defs/Hash`(`^sha256:[0-9a-f]{64}$`)가 이미 있어 `BuildImageResult.image_id`, `PublishResult.digest`가 그것을 참조한다(패턴은 같다). 다른 `$defs`(Id, Timestamp 등)는 맞는 필드가 없어 쓰지 않았다. revision(`^[0-9a-f]{7,40}$`)은 `_common`에 같은 정의가 없어 그대로 뒀다.
- 이웃 영역 코드는 읽지 않았다("이웃 쪽 미확인"은 MANIFEST note).

## ImageLabels와 survey-service 초안의 차이 (survey-service/docs/change-requests/schemas/image-labels.schema.json, 읽기 전용)

| 항목 | deploy ImageLabels | survey-service 초안 |
|---|---|---|
| io.openit.service | 이름 패턴 `^[a-z][a-z0-9-]*$` | `const: survey-service` |
| revision | 7~40자 hex, `unknown` 불가 | hex 또는 `unknown` 허용 |
| survey-schema | 숫자 또는 `n/a` | 숫자만 |
| turn-engine, model-runtime | `vX.Y.Z` 또는 `n/a` | `vX.Y.Z`만(필수, n/a 없음) |
| langgraph | 선택, minLength 1 | 필수, `X.Y.Z`(v 없음) |
| 허용하는 io.openit.* 키 | 11개(variant, app-version, jobs, exposure 포함) | 7개 |
| 다른 접두사 | 무시 | 무시(값은 문자열) |

두 스키마를 같은 예시에 실제로 돌려 본 결과(`jsonschema`): survey 초안의 valid 예시는 ImageLabels도 통과, invalid 예시는 둘 다 거부. 그러나 deploy의 `real-admin-console`(n/a 값)과 `with-declarations`(jobs/exposure 라벨)는 survey 초안이 거부한다.

**통합 판단(제안)**: 하나로 통합할 수 있다. survey-service 초안은 ImageLabels의 부분집합이 아니라 **서비스별 추가 제약**(service const, langgraph 필수·`X.Y.Z`, turn-engine·model-runtime 필수 실버전, survey-schema 숫자)이므로, 계약은 `ImageLabels` 하나를 두고 survey-service는 자기 CI에서 `allOf: [ImageLabels, {그 제약}]` 같은 프로필을 영역 몫으로 둔다(규칙 6: 읽는 쪽 부분집합을 계약으로 두지 않는다). 확인할 두 가지: (1) survey 초안이 `revision: unknown`을 허용하는 것은 deploy `publish-image.sh`가 거부하는 값이라(`io.openit.revision 이 unknown 이다`) 통합 때 허용하지 않는 쪽으로 맞춰야 한다. (2) langgraph의 `v` 접두사 없음(`1.2.15`)이 다른 버전 라벨(`v0.7.6`)과 표기가 다르다. 어느 쪽으로 통일할지는 헤드 판단이다.

## 실제 이미지 라벨이 초안 스키마를 어기는 곳 (examples/observed, 기대 없음)

이 PC의 로컬 `deploy-build/*` 이미지 8개에서 `docker image inspect`로 뽑은 라벨이다(이미지가 최신 빌드인지는 확인하지 않았다). survey-service, admin-console만 통과한다(`valid/real-*`). 나머지는 `validate.py`가 INFO로 보인다.

- `n/a`가 아닌 `none`을 쓴다: ops-feedback, question-authoring(turn-engine, model-runtime). 스키마는 `n/a`.
- 버전 `v` 접두사 없음: release-gate(`2.1.1`, `0.7.6`, `0.4.2`), model-serving model-runtime(`0.7.6`).
- survey-schema: question-authoring은 `survey-schema-v1.0.0`, dataset-store는 `unknown`. 스키마는 숫자 또는 `n/a`.
- turn-engine·model-runtime 라벨이 없다: kiosk-frontend. `publish-image.sh`는 이 둘을 선택으로 두는데(해당 없으면 없어도 된다) 초안 스키마는 필수 `n/a`다. 둘 중 하나를 헤드가 정해야 한다(스키마를 완화하거나 영역이 `n/a`를 단다).
- model-serving 이미지의 `io.openit.service`는 `model-runtime`이다(서비스 이름은 `model-serving`). 패턴은 통과하지만 `PublishRequest.service`/이미지 이름과 다르다.
- `publish-image.sh`는 필수 4개(service, revision, contracts.boundary, contracts.survey-schema)만 비어 있지 않은지 본다. 그래서 위 값들이 게시를 통과한다. 스키마 검증으로 바꾸면 이 영역들이 실패한다.

## 예시의 출처

- `valid/ImageLabels.real-*`는 실제 이미지에서 뽑았다. 나머지(BuildImage*, Exposure, JobsDeclaration, Publish*, SetupEnvReport, ImageLabels의 초안 예시)는 CR-D27 초안 예시를 옮긴 것이고 실제 코드가 낸 값이라고 확인하지 않았다. 현재 어느 이미지도 `io.openit.jobs`/`exposure` 라벨을 달지 않는다.
- `publish-image.sh`의 실제 출력을 PublishResult로 대조하는 시험은 만들지 않았다(코드 변경 없음, 스크립트 실행 안 함).
