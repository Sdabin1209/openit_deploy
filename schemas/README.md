# schemas/ — deploy 내부 타입 (D117)

영역 내부 타입마다 JSON Schema(draft 2020-12) 하나, 파일 이름 = 타입 이름(`<타입>.schema.json`), 예시는 `examples/<타입>.valid*.json`(통과)·`<타입>.invalid*.json`(거부). 받아들이는 조건(필수·형식·열거·범위·조건부 필수)은 여기에 다 적는다. 계약 타입(영역 사이)은 복사하지 않는다: 계약 클라이언트·validator 가 쓴다(`tests/test_contract_schema_copy`가 계약 이름과 겹치는 파일이 없음을 본다).
코드 타입은 `openit_deploy/types/deploy_types.py` 로 생성한다(`scripts/gen-types.sh`, README 4절). 구조 시험 `tests/test_structure.py` 가 예시 결과와 생성 결과 일치를 본다.

## 타입 목록

컴포넌트의 입력·출력 타입은 `docs/components.md` 표. 그 밖의 타입:

| 타입 | 무엇 |
| --- | --- |
| AreasDoc | head/shared/areas.json 에서 deploy 가 읽는 부분 |
| ImagesEnvRow, ImagesLock, VerifyAreas | build/images.env 한 줄, locks/images.lock, config/verify-areas.yaml (ADR 0034) |
| StepDecls | e2e_steps.py 의 @step 선언(repos, deps, why, also) |
| ProbeRecord | 추론 서버 호출 한 건의 집계용 기록 |

## 스키마 밖 조건

스키마로 쓰지 못해 코드에 둔 조건이다. 이유가 JSON Schema 의 표현력(두 값의 비교, 정본 목록과의 대조)이거나 스키마 대상이 아닌 곳이다. **Python 쪽 6건**, 셸·시험 쪽은 목록이 아니라 범주 2건이다.

| # | 조건 | 어디 | 스키마 밖인 이유 |
| --- | --- | --- | --- |
| 1 | verify-areas.yaml 의 영역 이름 집합 == areas.json 의 python·node·compose 영역 | `wiring/verify_area.py load_config` | 다른 파일(헤드 소유 정본)의 내용과의 대조. 스키마에 영역 이름을 박으면 영역을 더할 때 두 곳을 고친다(정본은 areas.json 하나) |
| 2 | verify-areas.yaml 의 image 이름 ∈ lib.sh 의 SERVICES | 같은 곳 | 정본이 셸(lib.sh) 한 곳. 같은 이유 |
| 3 | @step 선언 also 의 영역 ∈ areas.json 영역 | 같은 곳 | 1과 같다 |
| 4 | 어댑터 config 의 base_model_name_or_path == 프로파일의 base_model | `components/adapter_check.py` | 두 값의 같음 비교(JSON Schema 에 `$data` 가 없다). 거부 결과(ok false + rejection)로 표현한다 |
| 5 | 어댑터 순위 r ≤ 프로파일 max_lora_rank | `components/adapter_check.py` | 두 값의 크기 비교. 4와 같다 |
| 6 | setup-env 보고의 area == 영역 이름 | `components/setup_env_record.py` | 두 값의 같음 비교. 결과 status CONTRACT_VIOLATION |

범주(훑지 못했거나 대상이 아님):
- **셸 스크립트의 인자·환경 검사**(gen-secrets, publish, backup 등): 셸이라 JSON Schema 를 쓰지 않는다. 항목별로 훑지 않았다(미확인). 컴포넌트가 아니라 운영 절차이므로 ADR 0045 가 범위 밖으로 둔다.
- **수용 시험 쪽 규칙**(`e2e_plan.validate`: 단계 선언 누락·deps 와 STATE 접근의 일치 등): 시험의 일부이고 시험이 강제한다(`scripts/test_e2e_plan.py`).

판정 결과를 "거부"로 내는 컴포넌트(job_select 의 NO_SUCH_JOB, exposure_check 의 DIFF 등)는 입력 거부가 아니라 업무 결과라서 이 표에 넣지 않았다.
