# 0034. deploy 영역 안 컴포넌트 사이 파일 형식을 JSON Schema로 둔다 (images.env, images.lock, jobs.yaml, verify-areas.yaml)

- 상태: 채택(2026-10-28, 작업 지시서 2). 확인한 것: 이 PC에서 네 파일의 현재 내용이 스키마를 통과하고 일부러 틀린 입력은 거부된다(`scripts/test_check_schemas.py`). 아직 하지 않은 것: 생산자·소비자 스크립트가 쓰기·읽기 시점에 이 검증을 부르게 하는 일(아래 결과).
- 근거: 워크스페이스 규칙 R5(영역은 자기 컴포넌트 사이의 스키마를 알고 책임진다), 점검 보고서 DP-15(`docs/audit/structure-rules-2026-10-28.md`).

## 맥락

빌드 -> 게시 -> 잠금 -> 기동 -> 롤백 -> E2E 컴포넌트는 파일로 만난다. `build/images.env`(공백 4열), `locks/images.lock`(KEY=value), `config/jobs.yaml`, `config/verify-areas.yaml`. 형식을 정의한 곳이 없어 소비자마다 `sed`·`awk`·정규식으로 따로 읽고, `publish-images.sh`가 4열 변화를 `read -r area img commit _`로 우연히 견딘다. 변수 이름 목록이 `lib.sh`의 `env -u ...`, `compose.yaml`, `publish-image.sh`의 `tr`에 흩어져 있다.

## 결정

`schemas/`에 JSON Schema(2020-12)를 둔다: `images-env`(한 줄을 객체로 푼 것), `images-lock`(키 정규식 `^[A-Z][A-Z0-9_]*_(DIGEST|REVISION|IMAGE)$`), `jobs`, `verify-areas`. 저장 형식은 바꾸지 않는다. `scripts/check_schemas.py`가 텍스트를 객체로 풀어(파서는 한 곳) 검증하고, `scripts/test_check_schemas.py`가 `e2e.sh` 자기 점검에서 돈다. 모르는 키는 거부한다.

## 왜

- 표준: 영역 사이 계약(`boundary-contracts`)이 JSON Schema 2020-12와 `jsonschema` 검증기를 쓴다. 같은 도구를 쓰면 deploy 안과 밖의 스키마가 한 방식이다.
- 모르는 키를 거부하는 이유: 잠금 키 오타(`SURVEY_SERVICE_DIGST`)는 compose 가 `${..:?}`로만 잡아 기동 시점에야 드러난다. 파일 단계에서 잡는 것이 빠르다. 시험 `test_lock_rejects_typos_and_bad_values`가 이를 본다.
- 값을 출력하지 않는다: 검증 메시지에 digest가 섞이지 않게 위치와 위반 종류만 낸다.

## 검토한 대안과 버리는 이유

- 저장 형식을 JSON/YAML로 바꾸기(점검 보고서의 "가장 작은 수정"): 소비자가 셸 `sed`·compose `--env-file`(KEY=value 필수)이라 `images.lock`은 바꿀 수 없다. 형식을 유지하고 정의만 더하는 쪽이 회귀 위험이 작다.
- 데이터클래스(Python)로 정의: 셸 소비자가 읽을 수 없다. 스키마 파일은 언어와 무관하다.
- 정의 없이 유지: R5 위반이 계속되고 오타가 늦게 드러난다.

## 결과

- 얻는 것: 형식의 정본이 한 곳, 오타와 모양 변화를 자기 점검이 잡는다.
- 감수하는 것: 파서(`parse_images_env`, `parse_lock`)가 스키마 밖에 있어 셸 소비자와 어긋날 수 있다. 생산자·소비자 스크립트가 검증을 직접 부르지는 않는다(후속). `locks/images.lock`은 `DATASET_STORE_DIGEST`가 아직 없어(compose가 요구) 필수 키 목록에 서비스 쌍을 넣지 않았다: 이 파일 상태는 이 ADR의 범위 밖이다.
- 측정하지 않은 것: 검증 소요 시간(작은 파일이라 0.1초대로 관찰했을 뿐 한도를 두지 않았다).

## 되돌리는 조건

저장 형식이 JSON/YAML로 바뀌면 파서를 지우고 스키마를 파일에 직접 적용한다(새 ADR이 이 ADR을 대체). 스키마가 소비자 변화를 막는 부담이 되면 `additionalProperties` 정책만 완화한다.
