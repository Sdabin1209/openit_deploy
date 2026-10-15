# CR-D06: 이미지 라벨 키와 경계 계약 태그가 영역마다 다르다

- 상태: 제안
- 보내는 곳: deploy -> head (영향: 네 서비스 영역)

## 확인한 것

공통 규칙(D22)은 "이미지 라벨에 커밋, 소비하는 계약 버전, turn-engine·model-runtime 버전을 기록"한다. 키 이름이 정해져 있지 않아 영역마다 다르다.

| 영역 | 커밋 | 계약 | 라이브러리 |
| --- | --- | --- | --- |
| survey-service | `org.opencontainers.image.revision` | `io.openit.contracts.boundary`, `io.openit.contracts.survey-schema` | `io.openit.turn-engine`, `io.openit.model-runtime` |
| question-authoring | 같음 | `openit.contract.survey-schema`, `openit.contract.boundary-contracts`(커밋 해시) | `openit.lib.turn-engine=none`, `openit.lib.model-runtime=none` |
| ops-feedback | 같음 | `io.openit.contracts.boundary` | `io.openit.turn-engine`, `io.openit.model-runtime` |
| release-gate | 같음 | `org.openit.survey-contract-version`, `org.openit.boundary-contract-version`(파이프라인 스키마 버전) | `org.openit.turn-engine-version`, `org.openit.model-runtime-version` |

또 경계 계약 태그가 갈린다: survey-service와 ops-feedback은 v1.1.0, question-authoring과 release-gate는 v1.0.0(E2E에서 확인한 대로 v1.1.0 검증기는 1.0 레코드를 받고 게이트는 `pipeline_schema_version` 1.1 요청을 받았다. MINOR 호환 규칙대로 동작하는 것으로 보이나 한 서버에 두 버전이 섞여 있다).

## 요청

헤드가 라벨 키 이름 한 벌과 값 형식(`v1.1.0` 같은 태그 문자열)을 정해 공통 규칙에 쓴다(제안: `io.openit.contracts.boundary`, `io.openit.contracts.survey-schema`, `io.openit.turn-engine`, `io.openit.model-runtime`, 해당 없음은 `none`). 또 서버에 올릴 경계 계약 태그를 하나로 맞출 시점을 정한다. 맞추기 전에는 deploy가 라벨을 읽어 `locks/images.lock` 옆에 표로 남길 수 있다(그 표는 아직 만들지 않았다).
