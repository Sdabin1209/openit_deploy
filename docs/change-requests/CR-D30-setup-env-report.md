# CR-D30. 이웃 영역의 시험 환경·진입점을 추측하지 않는다: SetupEnvReport와 영역 진입점으로 (U43 deploy 몫 설계안)

- 보내는 곳: deploy -> 헤드 (영역 쪽 SetupEnvReport 출력이 생긴 뒤에 deploy 코드를 바꾼다. 지금은 코드 변경 없음)
- 근거: 구조 규칙 1·6(영역은 서로의 구조를 모른다, 영역 간 스키마는 헤드). `head/docs/audit/u23-boundary-consumers-2026-10-30.md`, OPEN_GAPS U43.

## 1. 지금 deploy가 이웃의 구조를 추측하는 곳 (코드에서 확인한 목록)

| # | 위치 | 추측하는 것 |
| --- | --- | --- |
| 1 | `scripts/doctor.sh:108-112` | 파이썬 영역(`areas_list --kind python,library`)마다 `<영역>/.venv/bin/python`이 있고 그 안에 `pytest`가 import되는지 |
| 2 | `scripts/doctor.sh:122-123` | 노드 영역마다 `<영역>/node_modules` 폴더가 있는지 |
| 3 | `scripts/check_all.py:391,869-874` (규칙 3·8) | `model-runtime/.venv/bin/python`(완화 정책), 영역마다 `.venv/bin/python`과 pytest 존재 |
| 4 | `scripts/check_all.py:852-853` (규칙 8) | 노드 영역의 `node_modules` 존재 |
| 5 | `scripts/prepare-host.sh:16-18` + `scripts/e2e_steps.py:203,259-263,283-284,1484` | synthetic-data를 `build/venv-sd/bin/python -m synthetic_data run|import --config …`로 **영역 소스의 사본(`build/ctx/synthetic-data`)을 cwd로** 실행: 영역의 파이썬 패키지 이름(`synthetic_data`), 모듈 하위 명령(`run`, `import`), 설정 파일 모양(`adapters.question_reader.factory = synthetic_data.adapters:http_question_reader`, `kwargs.token_env` …), 환경 변수 이름(`SD_QA_TOKEN`, `SD_OPS_TOKEN`, `DATASET_STORE_WRITE_TOKEN_FILE`)을 E2E가 안다 |

(1~4는 "환경이 어디에 어떻게 준비됐는지"를 추측하고, 5는 "영역의 잡을 어떻게 실행하는지"를 추측한다. 둘은 해결 수단이 다르다.)

## 2. 설계안

### 2-1. 환경 위치(1~4): 영역이 `scripts/setup-env.sh`로 환경을 준비하고 SetupEnvReport 한 줄을 낸다

- 계약 `SetupEnvReport`(boundary-contracts v2.4.1)에는 이미 `environment: {kind: python-venv|node-modules, path}`가 **[제안]** 필드로 있다. 영역이 이를 선언하면 deploy는 경로를 추측하지 않는다.
- deploy 쪽 변경(영역이 `environment`를 낸 뒤): `prepare-areas.sh`가 영역마다 `bash scripts/setup-env.sh`의 마지막 표준 출력 한 줄(JSON)을 받아 `SetupEnvReport`로 검증하고 `state/areas-env.json`(영역 -> report)에 모은다. `doctor.sh`와 `check_all.py`는 이 파일의 `environment.kind/path`로 `python`·`node_modules`를 찾고, pytest 확인은 영역의 시험 진입점(아래 2-3)에 맡긴다. 영역이 `environment`를 안 내면 그 영역은 "검증 안 함(SKIP, 이유: setup-env 가 환경 위치를 선언하지 않았다)"으로 낸다.
- 계약이 부족한 점(헤드에게): (a) `environment`가 "제안"이라 필수가 아니다 -> 3.0.0 전에 필수 승격 여부 결정 필요. (b) "시험을 어떻게 돌리는가"(pytest/npm test 진입점)에 대한 선언이 없다: `environment`에 `test_command`(argv 배열)를 더하거나 영역이 `scripts/run-tests.sh`를 내는 규약이 필요하다. 지금 deploy는 `pytest`/`npm test`라는 도구 이름도 추측한다(check_all 규칙 8).

### 2-2. synthetic-data 잡 실행(5): 영역이 이미지(또는 `run-once` 진입점)로 잡을 내고 deploy는 선언을 읽는다

- 기존 규약(워크스페이스 CLAUDE.md 자동화 절): 각 영역은 자기 잡을 한 번 실행하는 명령(`run-once`)과 설정 파일을 가진다. 이미 계약에 `JobsDeclaration`(이미지 라벨 `io.openit.jobs`)이 있어 영역이 이미지 라벨로 잡 목록을 낸다.
- 제안: synthetic-data가 (a) 라벨 `io.openit.jobs`로 `run`·`import` 잡의 argv와 설정 파일 경로·환경 변수(비밀은 `*_FILE`)를 선언하고, (b) 이미지에서 실행 가능하게 한다(현재 호스트 venv + 소스 사본 + cwd 가정이 사라진다). E2E는 `docker run --rm <이미지> <선언된 argv>`(compose `jobs` 프로파일과 같은 방식)로 잡을 돌린다.
- 설정 파일(`adapters` 팩토리 경로, 토큰 환경 변수 이름)은 영역의 JobConfig 스키마다. 계약이 이를 노출하지 않으면 deploy는 "영역이 내는 예시 설정 + 바꿀 값(URL, 토큰 파일 경로)의 이름"만 받아야 한다. 이를 위해 `JobsDeclaration`에 `config_example`(영역 이미지 안 경로)와 `inputs`(deploy가 채울 값의 이름과 의미: `QUESTION_READER_URL`, `FAILURE_STORE_URL`, `QUESTION_READ_TOKEN_FILE` …)를 더하는 계약 변경이 필요하다. **지금 계약은 이 부분이 부족하다**(`JobsDeclaration`은 argv만 선언한다고 읽었다, 확인 못 한 부분이 있으면 헤드가 정정).

### 2-3. 단계

1. 영역 8곳이 `setup-env.sh`에서 SetupEnvReport(+`environment`)를 낸다(영역 몫, U43).
2. 헤드가 `environment` 필수 여부와 시험 진입점 선언(2-1의 b), `JobsDeclaration` 확장(2-2)을 결정한다.
3. 그 뒤 deploy가 `prepare-areas.sh`, `doctor.sh`, `check_all.py`, `e2e_steps.py`(synthetic-data), `prepare-host.sh`(venv-sd)를 위 선언으로 바꾸고 이 목록의 추측을 지운다. 시험: 추측 경로 문자열(`.venv/bin/python`, `node_modules`, `synthetic_data`, `venv-sd`)이 deploy 코드에 없음을 확인하는 정적 시험(수정 전 실패).

## 3. 영향

- 지금 deploy 변경 없음. 영역이 SetupEnvReport를 내기 전에 deploy를 바꾸면 doctor와 check-all이 환경을 못 찾는다.
- 이 변경이 끝나면 deploy는 이웃의 `.venv`·`node_modules`·패키지 이름·설정 파일 모양을 모른다.
