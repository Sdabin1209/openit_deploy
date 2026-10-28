# deploy 영역 구조 규칙 6개 전수 점검 (2026-10-28, D104)

기준서: `head/docs/audit/structure-rules-audit-spec.md`(R1~R7, 항목 A~G). 대상: 이 리포(`deploy`) 전부를 읽기 전용으로 점검했다. 코드·설정·시험은 고치지 않았다. 비밀 값(`secrets/`, `.env`, 토큰)은 읽지 않았고 `env`/`printenv`도 쓰지 않았다. 실행 중인 `deploy-demo`, docker 이미지·볼륨은 건드리지 않았다(docker 명령을 한 번도 실행하지 않았다).

표기: 심각도 P1 = 독립성을 깨고 실제 결합을 만든다 / P2 = 숨은 결합·암묵 스키마 / P3 = 정리 수준. 인용은 2줄 이내로 줄였다. "확인" = 파일을 읽어서 안 것, "추정" = 읽지 못한 이웃 쪽 사실에 기대는 판단.

## 0. 요약

| 심각도 | 개수 |
| --- | --- |
| P1 | 15 |
| P2 | 17 |
| P3 | 4 |
| 합계 | 36 |

한 줄 진단: deploy는 "이미지 digest만 입력으로 받는다"(brief.md 서두, 3-1절)고 선언하지만, 실제로는 모든 이웃의 소스 트리·Dockerfile 인자·설정 키·환경 변수 이름·모듈 경로·내부 파일을 읽고 만들어 넘긴다. 이웃이 자기 인터페이스로 내놓는 것이 없어서 deploy가 대신 안다. 반대로 deploy 안쪽(영역 안 컴포넌트 사이)에는 기계가 읽는 스키마가 하나도 없다(`e2e_plan.py`의 `Decl` 데이터클래스가 유일).

## 1. 항목 A: 컴포넌트 목록

deploy에는 컴포넌트 경계가 문서나 코드로 선언돼 있지 않다. `docs/design.md`는 "구성 한눈에"(Compose 서비스 중심)이고 컴포넌트(작업 단위)·입력/출력 스키마 표가 없다(`grep` 확인: design.md 절 제목 1~11절에 컴포넌트 표 없음). 아래는 코드에서 역으로 정리한 것이며, "입력/출력 스키마" 열의 "없음"은 기계가 읽는 정의가 없다는 뜻이다. 형식은 있으나 암묵적인 경우는 형식을 적었다.

| # | 컴포넌트 | 파일 | 입력 | 출력 | 업무 | 스키마 정의 |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | 버전 표 | `scripts/lib.sh:19-25` | 환경 변수 `BOUNDARY_TAG_ALL` 등 | 셸 변수 `DEPLOY_BC_TAG` 등 | 계약·turn-engine·model-runtime 태그 한 곳 | 없음(셸 변수) |
| C2 | 이미지 빌드 | `scripts/build-images.sh` | 이웃 소스(`git archive`), 버전 표 | `build/images.env`(4열 텍스트), `build/ctx/*`, `build/hostwheels/` | 로컬 이미지 빌드 | 없음(공백 구분 텍스트, `build-images.sh:67`의 `record`) |
| C3 | 이미지 게시(전체) | `scripts/publish-images.sh` | `build/images.env`, `state/registry.env` | `locks/images.lock`, `locks/history/*` | 레지스트리 push + digest 잠금 | 없음(KEY=value, `publish-images.sh:37`) |
| C4 | 이미지 게시(CI 하나) | `scripts/publish-image.sh`, `docs/ci.md` | 서비스 이름, 이미지, 라벨 | 같은 잠금 + 마지막 줄 `PUBLISHED ...` | 영역 CI용 게시 | 문서(`ci.md`)만, 기계 정의 없음 |
| C5 | 레지스트리 | `compose.registry.yaml`, `scripts/registry.sh` | 포트 | `state/registry.env`(`DEPLOY_REGISTRY=`) | 로컬 레지스트리 기동 | 없음 |
| C6 | 비밀 생성 | `scripts/gen-secrets.sh`, `gateway-lib.sh`, `kiosk-add-device.sh`, `rotate-account.sh`, `config/gateway-accounts.conf` | 계정 설정(`<id> <역할,..>`) | `secrets/tokens/*`, `gateway-accounts.caddy`, `gateway-devices.caddy` | 토큰·해시·목록 파일 | 이름 규칙은 `RUN.md 4-1`; 계정 파일은 `gateway-lib.sh:18-32`가 손으로 검증 |
| C7 | 구성(Compose) | `compose.yaml`, `compose.*.yaml`, `config/*.env`, `config/postgres/` | 잠금, `.env`, 비밀 파일 | 실행 중 서비스 9개 + 잡 6개(`compose.yaml`) | 서비스 묶음 | Compose 스키마(외부 표준) |
| C8 | gateway | `config/Caddyfile`, `gateway-accounts.caddy` | HTTP 요청 | 프록시 요청(헤더 부착) | 인증·경로 분리·시간 상한 | Caddyfile(외부 표준), 경로·역할 표는 암묵 |
| C9 | 기동·종료·상태 | `up.sh`, `down.sh`, `status.sh`, `check-compose.sh` | 잠금, 프로젝트 이름 | 컨테이너 | 적용 | 없음 |
| C10 | 롤백 | `rollback.sh` | `locks/history/*.lock` | 되돌린 `images.lock` | 코드 축 롤백 | 없음 |
| C11 | 스케줄러 | `scripts/scheduler.py`, `config/jobs.yaml` | `jobs.yaml` | `state/scheduler.json`, 종료 코드 | 주기 잡 실행 | 없음. `scheduler.py:24-33`이 손으로 검증 |
| C12 | 잡 실행기 | `run-job.sh` | 서비스 이름 | 컨테이너 1회 실행 | compose 잡 실행 | 없음 |
| C13 | 백업·복구 | `backup-all.sh`, `backup.sh`, `pg-backup.sh`, `backup_tool.py`, `restore.sh`, `pg-restore.sh`, `backup-secrets.sh`, `restore-secrets.sh`, `backup-check.sh`, `backup-restore-test.sh`, `config/backup.env` | `backup.env`, 볼륨, DB | 암호화 백업 파일 | 백업·복구 | 없음(`backup.env` 키 목록은 `backup-lib.sh`가 손으로 읽음) |
| C14 | 건강 감시 | `check-health.sh`, `check_health.py`, `config/external-monitor.example.yaml` | 대상 yaml | 종료 코드 | 외부 감시 자리 | 없음 |
| C15 | 사전 점검 | `doctor.sh` | 호스트 상태 | OK/WARN/FAIL | 환경 진단 | 없음 |
| C16 | 영역 환경 준비 | `prepare-areas.sh`, `prepare-host.sh` | `head/shared/areas.json` | 영역 `.venv`, `node_modules` | 새 머신 준비 | `areas.json`(헤드 소유, `areas.py:12`가 kind만 검증) |
| C17 | 정적 점검 | `check-all.sh`/`check_all.py`, `check-versions.sh`/`check_versions.py`, `check_secret_names.py`, `check-relocatable.sh`, `check-secrets-hidden.sh`, `check-secret-perms.sh`, `check-containers.sh`, `check-standalone.sh` | 이웃 소스 트리 | PASS/FAIL | 영역 가로지르는 일관성 | 없음 |
| C18 | 영역 변경 검증 | `verify-area.sh`, `verify_area.py`, `config/verify-areas.yaml` | 변경된 영역 | 시험 계획 | 변경 영향 시험 | `verify-areas.yaml`, `verify_area.py`가 손으로 검증 |
| C19 | E2E | `e2e.sh`, `e2e_steps.py`(1925줄), `e2e_plan.py`, `e2e_asserts.py`, `e2e_verify_restore.py`, `record-e2e.sh`, `docs/E2E.md` | 실행 중 스택 | 단계 결과, `docs/E2E_RESULTS.md` 한 줄 | 합격 시나리오 | `e2e_plan.Decl` 데이터클래스(단계 선언)만. 단계 사이 `STATE` 딕셔너리는 암묵 |
| C20 | 데모 | `demo.sh` | e2e 단계 일부 | 데모 스택 | 사람이 누르는 환경 | 없음 |
| C21 | 실제 LLM 데모 | `make-llm-package.sh`, `llm_attach_package.py`, `compose.llm*.yaml`, `probe-serving.py`, `e2e_gpu.sh`, `compose.inference.yaml`, `compose.external-inference.yaml` | 어댑터, 프로파일 | 모델 패키지 디렉터리 | GPU 데모 | 없음 |
| C22 | PostgreSQL 보조 | `pg-roles.sh`, `pg-config-check.sh`, `pg-fingerprint.sh`, `fingerprint.sh`, `dev-postgres.sh`, `config/postgres/*` | DB | 계정·지문 | DB 운영 | 없음 |

접착 코드(어느 컴포넌트에도 속하지 않음): `scripts/lib.sh`(133줄, 버전 표 + 영역 목록 + `dc()` + 외부 추론 + HF 캐시 + 포트 + PG + 비밀 모드를 한 파일에서 `source`로 공유), `scripts/testlib.sh`, `scripts/areas.py`, `scripts/*.txt` 허용 목록, `test-*.sh`/`test_*.py` 시험 18개. 컴포넌트 경계가 없는 덩어리: `lib.sh`와 `e2e_steps.py` (DP-24).

## 2. 발견

### P1

**DP-01 | R1 | P1 | build-images.sh가 이웃 Dockerfile의 빌드 인자·빌드 도우미 인자를 전부 안다**
- 위치: `scripts/build-images.sh:71-111, 125-126, 148-149, 157, 164, 177-178`
- 인용: `--build-arg BC_SPEC=/wheels/$whl --build-arg "BC_VERSION=$DEPLOY_BC_TAG" --build-arg "REVISION=$c"` / `BOUNDARY_TAG="$BC" MODEL_RUNTIME_TAG="$MR" TURN_ENGINE_TAG="$TE" ... bash scripts/build_wheels.sh`
- 왜 위반: 영역마다 인자 이름이 다르다(`COMMIT` / `REVISION`, `BOUNDARY_TAG` / `CONTRACTS_VERSION` / `BOUNDARY_VERSION` / `BOUNDARY_CONTRACT` / `BOUNDARY_CONTRACTS`, 도우미 환경 변수 `CONTRACTS_TAG` / `BOUNDARY_CONTRACTS_TAG` / `BOUNDARY_TAG`). 이웃이 인자를 추가·개명하면 deploy 빌드가 깨진다(오늘 결함: `BC_VERSION`, `MODEL_RUNTIME_VERSION`). `--build-context` 이름(`wheels`, `survey_schema`, `boundary`, `schema`)도 이웃 Dockerfile 내부다.
- 최소 수정: 각 영역이 `scripts/build-image.sh <이미지태그> --out build.json` 하나(입력: 계약·turn-engine·model-runtime 태그, 커밋 / 출력: 이미지 ID)만 내놓고 deploy는 그것만 부른다. 인터페이스는 헤드가 `boundary-contracts`에 `IMAGE_BUILD.md`(+ 입력 JSON Schema)로 정한다. 이것이 없으면 영역이 자기 CI에서 빌드해 digest만 제출한다(brief 3-1의 원래 설계, D24).

**DP-02 | R1 | P1 | build-images.sh가 이웃의 빌드 산출물·내부 파일 경로를 읽는다**
- 위치: `scripts/build-images.sh:55, 72, 74, 84-85, 92, 155`
- 인용: `source "$CTX/survey-service/build/wheels/VERSIONS.env"` / `$(cat "$CTX/ops-feedback/src/ops_feedback/_schemas/survey/v1/CONTRACT_VERSION")`
- 읽는 것: survey-service `VERSIONS.env`(변수 `BOUNDARY_TAG`, `SCHEMA_CONTRACT_VERSION`, `TURN_ENGINE_TAG`, `MODEL_RUNTIME_TAG`), `requirements.lock`의 `langgraph==`, question-authoring `build/contracts.tag`·`build/survey-schema.tag`, ops-feedback `src/ops_feedback/_schemas/...CONTRACT_VERSION`, kiosk-frontend `package.json`의 `"version"`, model-runtime `pyproject.toml`의 `project.version`.
- 왜 위반: 폴더 구조·파일 이름·변수 이름을 deploy가 안다. 이웃이 내부 폴더를 옮기면 라벨 값이 조용히 비거나 빌드가 깨진다.
- 최소 수정: DP-01의 `build.json`이 `{image, revision, labels}`를 돌려준다. 라벨 값은 이미지 라벨이 정본이므로 deploy는 `docker image inspect` 라벨(D50)만 읽는다.

**DP-03 | R1 | P1 | deploy가 이웃 소스 트리로 이미지를 직접 빌드한다(브리프·작업 규칙과 어긋남)**
- 위치: `scripts/build-images.sh:52, 56, 58, 63, 119, 141`, `scripts/prepare-host.sh:18`, `scripts/e2e_gpu.sh:14`
- 인용: `git clone -q --bare "$WORKSPACE/$lib" "$CTX/$lib"` / `declare -A SRC=( ... [model-registry]=model-lab [dataset-store]=synthetic-data [model-serving]=model-runtime ...)`
- 왜 위반: `docs/brief.md` 3-1절은 "이 리포지토리는 이미지를 빌드하지 않고 digest를 모아 합친다"이고 워크스페이스 규칙은 읽기를 `../survey-service/schema`, `../boundary-contracts`, `../head/shared/areas.json`만 허용한다. 실제로는 이웃 11~13개 리포의 `HEAD` 소스를 `git archive`/`git clone`으로 꺼낸다. 이미지 이름 ↔ 소스 영역 매핑(`model-registry` ← `model-lab` 등)도 deploy가 안다(DP-22).
- 최소 수정: CI 경로(`publish-image.sh`)를 정본으로 하고 로컬 빌드는 영역이 제공하는 빌드 진입점(DP-01)만 호출. 허용 범위 밖의 읽기가 필요하면 헤드가 예외를 CLAUDE.md에 명시.

**DP-04 | R1 | P1 | E2E가 synthetic-data의 잡 설정(run 모드) 전체를 직접 구성한다**
- 위치: `scripts/e2e_steps.py:234-248`
- 인용: `"adapters": {"question_reader": {"factory": "synthetic_data.adapters:http_question_reader", "kwargs": {"base_url": URL("qa"), "token_env": "SD_QA_TOKEN"}}}` / `"turn_engine_version": "0.2.0", "survey_schema_dir": ...`
- 왜 위반: 키 집합(`dataset_id`, `seed`, `adapters.*.factory`, `kwargs`, `question_sets[].usage`, `seeds`, `split.ratios`, `review.per_kind`, `regeneration.mode`, `output.store`)과 이웃의 파이썬 팩토리 경로를 deploy가 쓴다. 사용자가 보고한 대로 이 키 일부가 synthetic-data에서 제거된 v1 키라면 deploy 쪽만 낡은 채 남는다. 이번 점검에서는 synthetic-data의 현재 스키마를 읽지 못해(허용 범위 밖) 제거 여부를 대조하지 못했다.
- 부수 결함(확인): `turn_engine_version`이 여기서는 `"0.2.0"`으로 박혔는데 같은 파일 265·352행은 `a.turn_engine_version`(`lib.sh:23`의 `DEPLOY_TE_TAG`=v0.4.2)을 쓴다. 한 E2E 안에서 같은 사실이 두 값이다.
- 최소 수정: synthetic-data가 잡 설정의 JSON Schema와 "시험용 최소 설정 생성" 진입점(`python -m synthetic_data example-config --http qa=URL,...`)을 내놓고, deploy는 URL·토큰 파일 경로만 넘긴다. 설정 스키마는 헤드가 `boundary-contracts`에 둔다(DP-31 E 목록).

**DP-05 | R1 | P1 | E2E가 synthetic-data import 모드의 설정·종료 코드·환경 변수·보고서·의존 목록을 안다**
- 위치: `scripts/e2e_steps.py:262-275, 283-296`, `scripts/prepare-host.sh:15`, `scripts/e2e_steps.py:1418`
- 인용: `env={... "DATASET_STORE_WRITE_TOKEN_FILE": str(... "dataset-store-write-synthetic-data")}` / `assert rc == 4 and o.get("status") == "REJECTED"` / `pip install ... attrs==26.1.0 jsonschema==4.10.3 packaging==26.3 pyrsistent==0.20.0 PyYAML==6.0.3`
- 왜 위반: `import` 모드 설정 키(`input_dir`, `tolerance.max_invalid_rows`, `source_label`, `output.store.kind=http|file`), 종료 코드 4=REJECTED, 출력 JSON의 `counts.rows_total/rows_valid/rows_invalid`, `import_report.json`의 `invalid_reasons_by_file`·`inputs[].sha256`, 단수/복수 환경 변수 이름(`DATASET_STORE_WRITE_TOKEN_FILE`/`..._TOKENS_FILE`, 주석에 "ADR 0013"), 호스트 가상환경에 설치할 서드파티 버전(synthetic-data `requirements.lock`의 복사본)을 deploy가 코드로 안다. `jobs.yaml:36`의 주석에도 같은 지식이 산문으로 복사돼 있다.
- 최소 수정: synthetic-data가 잡 인터페이스(진입점, 설정 스키마, 종료 코드 표, 결과 JSON 스키마, 환경 변수 이름)를 `boundary-contracts`의 "JOBS.md + JobResult 스키마"로 낸다. 가상환경은 영역의 `scripts/setup-env.sh`로 만든다(DP-12).

**DP-06 | R1 | P1 | deploy가 ops-feedback 잡의 내부 설정 파일 전체를 저작·소유한다**
- 위치: `config/ops-feedback-job.yaml:4-44`, `test/ops-job/test-ops-job.yaml`, `scripts/run-job.sh:96-100`, `compose.yaml:419-428`
- 인용: `deid: {policy_id: conservative-v0, salt_env: OPS_DEID_SALT, ...}` / `release_reader: {factory: "boundary_contracts.clients:HttpReleaseReader", args: {base_url: "http://release-gate:8080", token: {env: OPS_GATE_READ_TOKEN}}}`
- 왜 위반: 비식별 정책·탐지 규칙 ID(`TURN_FAILURE_SIGNAL` 등)·분류·보존 일수·팩토리 경로는 ops-feedback의 내부 모양이다. 파일 첫 줄이 "형식은 ops-feedback 가 정한다"고 인정한다. 비식별 기준값은 deploy가 정할 수 있는 값이 아니다("사용자 결정 아님"이라 쓰면서 deploy 리포에 둔다). 이웃이 설정 키를 바꾸면 deploy의 파일이 깨진다. `compose.yaml:419`의 `python -m ops_feedback.job --config /config/job.yaml`도 모듈 경로·플래그를 안다.
- 최소 수정: ops-feedback이 `JobConfig` JSON Schema와 운영 기본 설정 파일을 자기 리포에 두고, deploy는 "설정 파일 경로 하나 + 환경 변수 `*_FILE`"만 마운트한다. 실행 명령은 영역이 이미지 `ENTRYPOINT`/라벨(`io.openit.job.<이름>`)로 선언.

**DP-07 | R1 | P1 | 이웃의 파이썬 모듈 경로·서브커맨드를 compose와 env 파일이 박아 둔다**
- 위치: `config/release-gate.env:4-7`, `compose.yaml:419, 442, 461, 480, 500`
- 인용: `GATE_I1_FACTORY=release_gate.factories:http_question_reader` / `command: ["python", "-m", "release_gate", "collect"]`
- 왜 위반: `release_gate.factories:http_model_registry`는 release-gate 패키지의 내부 함수 이름이다. `-m survey_service purge`, `-m question_authoring purge`, `-m release_gate prune|collect`, `-m ops_feedback.job`도 같다. D39는 "각 영역은 자기 잡을 한 번 실행하는 명령(`run-once` 같은 것)과 설정 파일을 갖는다"인데, 명령 이름이 계약에 없다.
- 최소 수정: 각 영역이 이미지 라벨 `io.openit.jobs`(JSON: `{이름: [argv...]}`)나 `docs/boundary.md`의 기계 가능한 표로 잡 목록을 내고, deploy `jobs.yaml`은 `영역/잡이름`만 참조. 팩토리 경로는 영역 기본값으로 숨기고 URL만 환경 변수로 받는다.

**DP-08 | R1·R4 | P1 | llm_attach_package.py가 model-runtime 패키지를 import하고 model-lab/model-runtime의 산출물(ModelPackageManifest)을 손으로 조립한다**
- 위치: `scripts/llm_attach_package.py:1-5, 80-107`, `scripts/make-llm-package.sh:33, 37-43, 62`
- 인용: `import model_runtime as mr` / `cfg = mr.fake_serving_config(backend)` / `"출력 구조는 model-runtime make_neutral_package.py 와 같다"`
- 왜 위반: 이웃 코드 의존(`mr.load_profile`, `mr.fake_serving_config`, `mr.DEFAULT_SUPPORTED_FEATURES`, `mr.SUPPORTED_RUNTIME_CONTRACT_VERSION`, `mr.RUNTIME_VERSION`), 프로파일 JSON 키(`base_model`, `engine.max_lora_rank`), 어댑터 파일 이름(`adapter_model.safetensors`, `adapter_config.json`)과 safetensors 머리말 파싱, `SUMMARY.json` 모양, 매니페스트 필드 전체를 deploy가 알고 같은 일을 재구현한다. `make-llm-package.sh`는 model-runtime 태그에서 `scripts src profiles` 폴더를 꺼내 내부 스크립트 `make_neutral_package.py`를 호출한다.
- 최소 수정: model-runtime(또는 model-lab)이 "외부 어댑터 → ModelPackageManifest" 진입점(`python -m model_runtime attach-package`)을 제공. deploy는 어댑터·프롬프트 경로만 넘기고 출력 디렉터리를 `validator("ModelPackageManifest")`로만 확인.

**DP-09 | R1 | P1 | E2E가 model-lab의 출력(ModelPackageManifest·EvaluationReport)과 model-runtime 서빙 설정을 직접 만든다. 근거 필드는 I9 계약에 없다**
- 위치: `scripts/e2e_steps.py:305-385, 327-336`
- 인용: `ex = info["serving_config_expectation"]` / `mkcfg = lambda mode: {"prompt_template_version": ex["prompt_template_version_default"], ... "protection_policy_version": ex["protection_policy_versions"][-1]}`
- 왜 위반: `/v1/info`에서 `serving_config_expectation`, `prompt_template_version_default`, `constraint`, `output_contract`, `protection_policy_versions`를 읽어 `serving_config`를 조립한다. 계약 `HTTP.md:116`의 `/v1/info` 응답은 `{service, runtime_version, supported_contract_versions, backend, loaded, serving_config_hash}`뿐이라 이 필드들은 계약 밖이다(F 참조). `docker_py(IMAGES["survey-service"], "import model_runtime as m; m.fake_serving_configs()")`(336행)는 survey-service 이미지 안의 model-runtime 내부 함수까지 부른다.
- 최소 수정: ① model-lab이 "시험용 중립 패키지 생성" 진입점을 내놓거나, model-runtime의 `make_neutral_package`를 영역 진입점으로 승격한다(DP-08과 같은 것). ② `serving_config_expectation`을 I9 `/v1/info` 계약에 추가(변경 요청) 하거나 E2E가 쓰지 않게 한다.

**DP-10 | R1 | P1 | E2E가 survey-service 소스 파일의 내부 상수를 AST로 읽는다**
- 위치: `scripts/e2e_steps.py:1215-1222`
- 인용: `src = (ROOT / "build/ctx/survey-service/survey_service/risk_rules.py").read_text(...)` / `... getattr(t, "id", "") == "_PROVISIONAL"`
- 왜 위반: 이웃 소스 파일 경로, 비공개 이름(`_PROVISIONAL`), 값의 모양(`{규칙키: [문구,...]}`), 규칙 키 `"chest-pain"`을 안다.
- 최소 수정: survey-service가 위험 문구 목록을 읽기 면(`GET /v1/risk-rules` 등 계약 API)이나 이미지 속 공개 파일로 제공하거나, E2E용 문구를 설정으로 주입(`SURVEY_RISK_RULES_FILE`)해 deploy가 소유한 값을 쓴다.

**DP-11 | R1 | P1 | 정적 점검기(check-all·check-versions·check-secret-names)가 이웃 소스 전체를 파싱하고, 이웃 가상환경의 내부 함수까지 부른다**
- 위치: `scripts/check_all.py:28, 377-384, 488, 559`, `scripts/check_versions.py:10-61`, `scripts/check_secret_names.py:31-93`
- 인용: `py = ... str(WS / "model-runtime" / ".venv" / "bin" / "python")` / `from model_runtime.schema_guard import relax` / `base = WS / "turn-engine" / "turn_engine" / sub.split(".")[0]`
- 왜 위반: 워크스페이스 규칙 상 읽기 허용은 세 경로뿐이다. 이 점검기들은 모든 영역의 `*.py`·Dockerfile·requirements·compose·package.json을 읽고(`git ls-files`), model-runtime의 `schema_guard.relax`·`DEFAULT_SUPPORTED_FEATURES`, turn-engine 내부 모듈 목록을 쓴다. 이웃의 환경 변수 `*_FILE` 이름을 `read_secret("NAME")` 호출에서 AST로 뽑는다(`check_secret_names.py:56-62`). 이웃의 폴더 구조·모듈 이름·패턴이 deploy 코드에 박혀 있다. ADR 0033이 파싱 방식을 개선했지만 R1 문제는 그대로다.
- 최소 수정: 점검은 각 영역이 자기 리포에서 한다(`scripts/verify-contract.sh`). deploy는 영역이 내놓은 JSON(`boundary.json`: 소비하는 계약 버전, 읽는 `*_FILE` 이름, 포트)만 수집·대조. 정적 점검 중 계약 패키지로 가능한 것(스키마 완화 정책, 삭제된 이름)은 `boundary-contracts`의 conformance로 이동.

**DP-12 | R1 | P1 | 이미지 라벨 규칙(D50)과 게시 인터페이스가 영역 경계를 넘는데 boundary-contracts에 없다**
- 위치: `scripts/publish-image.sh:51-55`, `scripts/e2e.sh:229-241`, `scripts/demo.sh:184-188`, `docs/ci.md:1-12`
- 인용: `for k in io.openit.service io.openit.revision io.openit.contracts.boundary io.openit.contracts.survey-schema; do` / `case "$l" in ""|"<no value>"|none) return 0;;`
- 왜 위반: 라벨 6개 + 선택 확장(`io.openit.langgraph` 등, D63), 값 규칙(`unknown` 금지, `v` 접두 유무: `demo.sh:187`이 "v 접두사는 무시"), 영역 CI가 따라야 할 `scripts/smoke.sh`·`publish-image.sh` 호출 규약·종료 코드 0~5·마지막 줄 `PUBLISHED ...`는 모든 영역이 지켜야 하는 인터페이스다. `grep -rl io.openit boundary-contracts`(md/json/py) 결과 0건이라 계약에 없다. 정본이 `head/docs/DECISIONS.md` D50·D63과 deploy의 `docs/ci.md` 두 곳으로 나뉜다. 라벨 표기가 영역마다 달라 비교가 불가능하다고 `build-images.sh:66`이 스스로 적었다.
- 최소 수정: 헤드가 `boundary-contracts`에 `IMAGE_LABELS.md` + `ImageLabels.schema.json`(키, 정규 표기 `vMAJOR.MINOR.PATCH`, 해당 없음 값 `n/a` 하나)과 `PUBLISH.md`(CI→deploy 인터페이스)를 둔다. `ci.md`는 deploy 쪽 구현 설명만 남긴다.

**DP-13 | R1·R6 | P1 | gateway(Caddy)가 이웃 API 경로·메서드·역할·토큰·헤더를 알고, 그 정본(계약)이 부분적이다**
- 위치: `config/Caddyfile:109-300`, `scripts/gateway-lib.sh:12`, `config/gateway-accounts.conf`
- 인용: `@staffapi path /v1/staff/* /v1/sessions/*/intervention` / `header_up Authorization "Bearer {file./run/secrets/gate-write-release-approver}"`
- 확인한 매핑(경로 → 서비스 → 역할 → 토큰 파일): 직원 API(survey, `staff`, `survey-api-staff`), 승인 읽기·쓰기 4경로(release-gate, `release-approver`, `gate-read/write-release-approver`), 운영자 4경로(`operator`), 검토 경로(ops-feedback, `reviewer`), 저자 경로(question-authoring `/v1/materials /v1/drafts* /v1/reviews`, `author`/`clinical-reviewer`), 키오스크 `/v1/sessions*`(기기 토큰), 내부 전용 `/v1/sessions/*/risk-signals /v1/results*`는 404. 역할 이름 6개(`GW_ROLES`)와 `X-Openit-User` 헤더.
- 계약 대조(확인): 경로는 `HTTP.md`(`/v1/cases`, `/v1/deidentified-traces`, `/v1/materials`, `/v1/drafts`, `/v1/reviews`, `/v1/active-pointer`, `/v1/releases`, `/v1/decisions`)·`PUBLIC_API.md`(`/v1/staff/alerts`)에 산재해 있고, "게이트웨이가 열어야 하는 경로와 역할의 표"는 어느 문서에도 없다(`grep` 확인). 역할 이름 `author`·`clinical-reviewer`·`reviewer`·`operator`·`release-approver`의 게이트웨이 정의도 없다.
- 왜 위반: gateway가 이웃 API를 아는 것 자체는 gateway의 업무다. 문제는 알아야 할 내용이 이웃이 스키마로 제공하지 않아 deploy가 각 영역 코드·문서를 읽고 추측해 쓴다는 점이다(오늘의 결함 패턴과 같다). `/v1/signals`는 E2E(`e2e_steps.py:1336`)가 호출하는 question-authoring 경로인데 어느 계약 문서에도 없다.
- 최소 수정: 각 서비스가 "외부 노출 면"을 `exposure.json`(`[{path, methods, role, audience: kiosk|staff|human-ui|internal, timeout_class}]`)으로 낸다. 헤드가 스키마를 `boundary-contracts`에 둔다. Caddyfile은 이 JSON에서 생성(또는 일치 검사). 역할 이름 집합은 계약에 둔다.

**DP-14 | R1 | P1 | compose.yaml이 이웃 서비스의 환경 변수 이름, 비밀 매핑, 이미지 안 사실(실행 도구·경로·UID)을 안다**
- 위치: `compose.yaml:65-158, 267-276, 296-302, 319-325, 342-348, 366-369, 384-386, 400-402, 282, 241`
- 인용: `SURVEY_KIOSK_DEVICE_TOKENS_FILE: /run/secrets/survey-kiosk-device-tokens` / `test: ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2)"]`
- 왜 위반: 서비스별 `*_FILE` 이름 약 35개(`QA_GATEWAY_TOKENS_FILE`, `OPS_FAILURE_DATABASE_URL_FILE`, `MODEL_RUNTIME_RELEASE_TOKEN_FILE` ...), `tmpfs: ["/tmp", "/data"]`("영역의 SQLite 기본 경로가 /data", `compose.yaml:304`), 컨테이너 안에 `python`·`wget`이 있다는 가정(healthcheck를 compose가 재정의), 포트 8080, `/healthz`, `uid 10001`(`lib.sh`·`SETUP`)을 deploy가 안다. 이웃이 이름을 바꾸면 `check_secret_names.py`가 소스를 읽어 잡아내야 하는 구조(DP-11)다. 이웃 이미지는 자기 `HEALTHCHECK`를 이미 가졌다(`docs/boundary.md` 표 "이미지 HEALTHCHECK 있음").
- 최소 수정: 각 영역이 이미지 라벨 `io.openit.deploy-manifest`(또는 리포의 `deploy.manifest.json`, 스키마는 계약)로 `{port, health, secrets:[{env:"X_FILE", name:"..", mode}], volumes:[{path,write}], tmpfs, jobs:[...], exposure}`를 선언. compose는 그 선언 위에서만 조립. healthcheck는 이미지 `HEALTHCHECK`를 따른다.

**DP-15 | R3·R5 | P1 | deploy 안의 컴포넌트 사이 스키마가 기계가 읽는 형태로 한 곳에 없다**
- 위치: 1절 표 C2~C20 전반. 구체: `build/images.env`(`build-images.sh:67`), `locks/images.lock`(`publish-image.sh:85`, `publish-images.sh:37-42`, `rollback.sh`, `lib.sh:56`의 `env -u ...` 목록), `config/jobs.yaml`(`scheduler.py:24-33`), `config/verify-areas.yaml`(`verify_area.py`), `state/scheduler.json`, e2e `STATE` 딕셔너리(`e2e_steps.py:93-94`), `config/backup.env`, `config/gateway-accounts.conf`.
- 인용: `echo "$1 $2 $3 bc=$BC,te=$TE,mr=$MR" >> "$DEPLOY_ROOT/build/images.env"` (4열 공백 텍스트) / `lib.sh:56: env -u SURVEY_SERVICE_DIGEST -u QUESTION_AUTHORING_DIGEST ...`
- 왜 위반(R5): 영역 안 컴포넌트들(빌드→게시→잠금→기동→롤백→E2E)이 교류하는 파일 형식을 정의한 곳이 없고, 각 소비자가 정규식·`sed`·`awk`로 따로 읽는다. 변수 이름 목록이 `lib.sh:56`, `compose.yaml`, `publish-image.sh:78`(`tr 'a-z-' 'A-Z_'`)에 흩어져 있다. 이 때문에 `publish-images.sh`가 `build/images.env`의 4번째 열 변화에 맞춰 `read -r area img commit _`로 우연히 견딘다.
- 최소 수정: `deploy/schemas/`에 `images-env.schema.json`, `images-lock.schema.json`(키 정규식 `^[A-Z_]+_(DIGEST|REVISION|IMAGE)$`), `jobs.schema.json`, `backup-config.schema.json`, `e2e-state.schema.json` 등 JSON Schema를 두고, 읽고 쓰는 스크립트가 한 검증 함수를 부른다. 저장 형식을 JSON/YAML로 바꾸는 것이 가장 작은 수정이다.

(P1 합계: DP-01 ~ DP-15 = 15건)

### P2

**DP-16 | R1 | P2 | status.sh와 건강 점검이 이웃 /readyz 본문 필드를 읽는다**
- 위치: `scripts/status.sh:39-40`
- 인용: `extra = f": ready={d.get('ready')} active_release={d.get('active_release')} problems={d.get('problems')}"` / `judging=... awaiting_approval=...`
- 왜: `HTTP.md:117`·`CONVENTIONS.md:110-111`은 readyz를 "200/503 + 사유"로만 정한다. 본문 키는 계약 밖이다(`E2E` 단언들 `e2e_asserts.py`도 같은 필드를 쓴다, 추정: 이 파일은 상세히 읽지 않았다). 최소 수정: 계약에 `ReadyzBody` 스키마(공통 `ready`, `problems[]` + 영역 `ext`)를 둔다.

**DP-17 | R1 | P2 | gen-secrets.sh가 이웃이 받는 토큰 목록의 형식과 역할 이름 집합을 안다**
- 위치: `scripts/gen-secrets.sh:38-41, 46-47, 68`, `scripts/gateway-lib.sh:64-68`
- 인용: `putlist qa-author-tokens "$QA_AUTHOR:author-e2e:question-author,$QA_REVIEWER:clinical-e2e:clinical-reviewer"` / `printf '%s=%s\n' "$id" ... >> survey-kiosk-device-tokens`
- 왜: `역할=토큰,...`은 계약(`HTTP.md:11`)이지만 `토큰:사용자:역할`(question-authoring)과 `device_id=토큰` 줄(survey-service)은 영역 고유 형식이다. 서비스별 허용 역할 이름(`gate`: read/write 각 역할, `ops-review-reviewer` 등)이 코드에 박혀 있다. 최소 수정: 각 서비스가 `TokenTable` 형식과 역할 목록을 `deploy-manifest`(DP-14)에 선언하고, deploy는 토큰 발급 + 파일 배치만.

**DP-18 | R1 | P2 | 백업이 이웃 저장소의 안쪽 구조를 안다**
- 위치: `scripts/backup_tool.py:13-15`, `scripts/backup.sh:17, 38`, `scripts/backup-all.sh:2`
- 인용: `STORE_EXCLUDES = {"survey-data": ("releases",), "datasets-data": (".tmp",)}`
- 왜: survey-service 볼륨 `releases/`는 "게이트 묶음에서 다시 적재되는 사본", dataset-store `.tmp`는 "요청 임시 폴더(synthetic-data ADR 0012)"라는 이웃 내부 사실이다. 최소 수정: 영역이 `deploy-manifest.volumes[].backup: {include|exclude: [...]}`로 선언.

**DP-19 | R1 | P2 | 서비스 목록·이미지 이름 ↔ 영역 매핑이 여러 곳에 복사돼 있다**
- 위치: `scripts/lib.sh:30`(`SERVICES`), `lib.sh:56`(digest 변수 목록), `build-images.sh:56`(`SRC`), `scripts/status.sh:19, 33`, `e2e.sh:234, 243`, `config/verify-areas.yaml:22-59`(`image:`), `docs/ci.md`, `demo.sh:89`
- 인용: `SERVICES="survey-service question-authoring ops-feedback release-gate model-registry dataset-store model-serving kiosk-frontend admin-console"` / `[model-registry]=model-lab [dataset-store]=synthetic-data [model-serving]=model-runtime`
- 왜: R5(영역 안 일관성)와 R1(영역 ↔ 이미지 매핑은 이웃이 선언할 사실). `areas.json`(헤드 정본)에는 영역이 어떤 이미지·서비스를 만드는지 필드가 없다. 최소 수정: `areas.json`에 `images: ["model-registry"]` 같은 필드(헤드 소유)를 추가하고 deploy 모든 곳이 `areas.py`로 읽는다.

**DP-20 | R3·R4 | P2 | run-job.sh가 일반 실행기인데 `job-ops-feedback` 분기를 갖는다**
- 위치: `scripts/run-job.sh:96-100`
- 인용: `if [ "$svc" = job-ops-feedback ] && [ $# -eq 0 ]; then ... cfg=${OPS_JOB_CONFIG:-.../config/ops-feedback-job.yaml}`
- 왜: 한 함수가 "잡 실행"과 "ops-feedback 전용 설정 검사"를 서비스 이름 분기로 같이 한다(R3·R4). 스케줄러는 compose 서비스 이름(`job-*`)을 안다(`jobs.yaml:7-31`). 최소 수정: 설정 필요 여부를 `jobs.yaml`의 `requires_file:`로 선언.

**DP-21 | R3 | P2 | lock 파일 쓰기가 publish-image.sh와 publish-images.sh에 이중 구현돼 서로 다르게 검사한다**
- 위치: `scripts/publish-image.sh:78-90`, `scripts/publish-images.sh:23-43`
- 인용: `publish-image.sh:52: for k in io.openit.service ... ; do ... exit 3` / `publish-images.sh:17: while read -r area img commit _; do`
- 왜: 같은 잠금 형식을 두 컴포넌트가 따로 쓴다. 단수는 라벨 4개·digest 대조·flock·history를 하고, 복수는 flock이 없고 라벨 검사가 없다(확인: `publish-images.sh` 전체에 `flock`·`label` 없음). 한 형식을 한 곳에서 쓰지 않아 어긋날 수 있다(G 참조). 최소 수정: 복수 스크립트가 영역별로 단수 스크립트를 호출.

**DP-22 | R3 | P2 | lib.sh가 공용 모듈로 모든 컴포넌트에 전역 상태를 공유한다**
- 위치: `scripts/lib.sh` 전체(133줄)
- 인용: `[ "${DEPLOY_NO_DOCKER:-0}" = 1 ] || detect_docker`(source하는 순간 부작용) / `export HF_CACHE_VOLUME=...`
- 왜: 버전 표, 영역 목록 읽기, `dc()`, 외부 추론 설정, HF 캐시, 포트, PG, 비밀 모드가 한 파일이다. 스크립트가 `source`로 전역 변수(`DOCKER`, `WORKSPACE`, `COMPOSE_EXTRA`, `_MOUNTED_SECRETS`)를 공유하고 `DEPLOY_NO_DOCKER=1` 같은 플래그를 `source` 전에 약속으로 넘긴다. 최소 수정: `lib-versions.sh`, `lib-docker.sh`, `lib-compose.sh`로 쪼개고 각 컴포넌트는 필요한 것만 source.

**DP-23 | R3 | P2 | e2e_steps.py가 1925줄 한 파일이고 단계 사이를 전역 STATE 딕셔너리로 잇는다**
- 위치: `scripts/e2e_steps.py:93-94`(STATE), 69곳의 `STATE[...]`, `@step` 선언 `:36-41`
- 인용: `STATE = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}` / `_P4 = "step4 가 STATE['pointers']/['releases'] 를 쓰고 이 단계가 '\"pointers\" not in STATE' 로 BLOCKED 처리한다 ..."`
- 왜: 단계(5, 5c, 5m ...)가 서로의 STATE 키(`qs`, `dataset`, `pointers`, `releases`)에 기댄다. `deps`는 AST로 사후 검증되는 선언일 뿐 키 스키마가 아니다. 단계 하나가 이웃 단계의 내부 상태 모양을 안다(R3·R4). 최소 수정: `STATE` 키를 `TypedDict`/JSON Schema로 정의하고 단계별 읽기·쓰기 키를 선언(이미 `deps`에 있는 정보를 타입으로).

**DP-24 | R1 | P2 | E2E가 서비스 기본값·상수를 복사한다(시간 사슬, 턴 마감)**
- 위치: `scripts/e2e_steps.py:753, 756-765`, `config/Caddyfile:20-27, 288-296`
- 인용: `SURVEY_TURN_DEADLINE_S = 6.0 # survey-service 서버 턴 총 마감(SURVEY_TURN_DEADLINE_SECONDS 기본)` / `GW_HDR_GATE_S, GW_HDR_OPS_S = 15.0, 10.0`
- 왜: 6초는 `CONVENTIONS.md`의 시간 사슬(계약, 표로만 있음)이지만 `SURVEY_TURN_DEADLINE_SECONDS`라는 survey-service 환경 변수 이름과 그 기본값을 E2E가 안다. Caddy 상한(15/10초)은 deploy 자신의 값이다(`test_e2e_constants.py`가 대조). 최소 수정: 시간 사슬을 계약에 JSON(`time_chain.json`)으로 두고 E2E·Caddy가 읽는다.

**DP-25 | R1 | P2 | metrics 레지스트리 접근이 계약 패키지 모양을 추정하고, 없을 때 계약 파일을 직접 읽는 대체 경로가 있다**
- 위치: `scripts/e2e_steps.py:21-33`
- 인용: `if hasattr(bc, "metrics"): ms = list(bc.metrics().values())` / `f = pathlib.Path(__file__).resolve().parents[2] / "boundary-contracts" / "boundary_contracts" / "metrics.json"`
- 확인: 현재 `boundary_contracts/metrics_registry.py:19-27`의 `metrics()`는 `{이름: 읽기 전용 항목}`을 돌려주고 docstring과 `METRICS.md:7`이 이를 문서화한다. 즉 오늘 시점에는 맞다. 문제는 ① `.values()` 모양 가정과 필수 키 집합(`need`, 28행)을 deploy가 재선언하는 것, ② 패키지에 `metrics()`가 없는 구버전이면 `../boundary-contracts/.../metrics.json`을 직접 열어 `metrics()`를 재구현하는 것(경로는 워크스페이스 규칙이 읽기 허용하지만 패키지 내부 파일 위치다). 버전 표가 `v2.1.1`로 고정이라 대체 경로는 사실상 죽은 코드다. 최소 수정: 대체 경로 삭제, 필수 키 검사는 계약의 `metrics.schema.json`로.

**DP-26 | R1 | P2 | prepare-areas·doctor·verify-area가 이웃의 개발 도구 이름과 폴더 규칙을 안다**
- 위치: `scripts/prepare-areas.sh:52-55`, `scripts/doctor.sh:102-125`, `scripts/verify_area.py:141-144`, `config/verify-areas.yaml:23-54`, `scripts/lib.sh:15-16`
- 인용: `s="$WORKSPACE/$a/scripts/setup-env.sh"` / `("npm", "test", "--silent")] + [tuple(c) for c in t.get("also", [])]` / `tests: {kind: npm, also: [["node", "scripts/gen-schemas.mjs", "--check"]]}`
- 왜: `scripts/setup-env.sh` 규약은 `boundary-contracts/README.md:61, 74`에는 있으나 헤드 문서(작업 규칙)·`areas.json`에는 없다(확인). `.venv/bin/python`, `node_modules`, pytest 존재, admin-console의 `gen-schemas.mjs --check`, node 하한 `24`(두 영역 `package.json engines` 복사본, `lib.sh:15`)를 deploy가 안다. "영역 파일이 바뀌면 거기를 따라 고친다"(lib.sh 주석)는 수동 동기화다. 최소 수정: 영역 규약을 `head/shared`에 문서화하고 `areas.json`에 `test_cmd`, `setup_cmd`, `node_min` 필드를 추가(헤드).

**DP-27 | R1 | P2 | E2E 시험 자료가 이웃 내부 모양을 복사한다(가짜 모델 흐름, 문항 양식)**
- 위치: `test/fake-model/question_flow.json`, `test/compose.fake-model.yaml:3-5`, `test/fixtures/question-form-v2.txt`, `scripts/e2e_steps.py:566, 1119, 1053`
- 인용: `MODEL_RUNTIME_FAKE_FLOW_FILE: /test-fake-model/question_flow.json`(환경 변수 이름은 model-runtime ADR 0009) / `"order": ["Q1.D01", "Q1.D02", ... "Q10"]`, `"slots": {"Q1.D01": [{"key": "Q1.D01.diagnosed", "type": "boolean"}]}`
- 왜: model-runtime 가짜 백엔드의 입력 파일 형식(키 `order`, `slots`, `corrections`, `reasks`)과 문진 문항 ID 31개·슬롯 키·타입을 deploy 리포가 갖는다. 문항 ID 목록은 문진 스키마(허용 읽기)와 survey-service 흐름(`question-form-v2.txt`는 "survey-service 의 QuestionFlow 와 같은 순서"라고 주석)의 복사본이다. 최소 수정: model-runtime이 `FakeFlow` JSON Schema와 "문진 스키마에서 흐름 파일 생성" 도구를 제공.

**DP-28 | R1 | P2 | 외부 GPU 경로가 model-lab의 원격 폴더·실행 명령·환경 변수를 안다. 토큰이 ssh 명령줄에 실린다**
- 위치: `scripts/e2e_gpu.sh:14-19`
- 인용: `rsync ... "$SRC"/ "$HOST":openit-gpu/model-lab/` / `MODEL_REGISTRY_URL=http://127.0.0.1:18080 MODEL_REGISTRY_WRITE_TOKEN=$TOKEN ... python -m model_lab run --config configs/gpu-dev-http-publish.yaml`
- 왜: model-lab의 설정 파일 경로(`configs/gpu-dev-http-publish.yaml`), 진입점, 환경 변수 이름(`MODEL_REGISTRY_WRITE_TOKEN`: D84는 `_FILE`)을 안다. 토큰을 `TOKEN=$(cat ...)`로 읽어 원격 명령줄에 넣는다(비밀 취급은 이 점검 규칙 밖이므로 사실만 적는다). 주석이 "실행해 보지 않았다(미검증)"고 인정한다. 최소 수정: model-lab이 `run-once --registry-url --token-file` 진입점을 계약으로 제공(D39).

**DP-29 | R1·R6 | P2 | 개별 헤더·본문 규약 일부가 계약에 흩어져 deploy 시험이 계약보다 더 안다**
- 위치: `scripts/e2e_steps.py:129-130, 427-452`
- 인용: `data=json.dumps({"requested_by_role": "operator", **body})` / `"(옛 게이트 호환을 위해 operator 로 넣는다)"`
- 왜: `HTTP.md:75`는 I5 `activate` 본문에 `requested_by_role`을 정의하지만 `X-Openit-User`와 역할 토큰이 실제 권한을 정한다고 `PUBLIC_API`/`HTTP.md:86`이 말한다. E2E가 "무시되는 필드를 옛 호환으로 보낸다"는 이웃의 이력을 안다. 최소 수정: 계약에서 `requested_by_role` 폐기 여부를 확정하고 E2E에서 제거.

**DP-30 | R1·R7 | P2 | 버전 표(lib.sh)와 정확 일치 규칙(D80)이 만드는 결합**
- 위치: `scripts/lib.sh:19-25`, `scripts/check_versions.py`, `scripts/build-images.sh:50-67`, `scripts/doctor.sh:124-125`, `docs/adr/0003`·SETUP E절
- 인용: `DEPLOY_MR_TAG="${MODEL_RUNTIME_TAG_ALL:-v0.7.6}"` / `DEPLOY_SS_TAG="survey-schema-v1.0.0"`
- 결합 목록(확인): ① 세 태그(계약 v2.1.1, turn-engine v0.4.2, model-runtime v0.7.6)와 survey 스키마 태그 `survey-schema-v1.0.0`(survey-service 리포의 태그 이름 규칙)이 deploy 코드에 있다. ② 버전을 올리려면 영역 N개를 모두 맞춘 뒤 deploy 표를 같이 올려야 한다(정확 일치): `check_versions.py`가 모든 영역의 Dockerfile ARG·requirements·package.json 문자열을 정규식으로 검사하므로 한 영역이 뒤처지면 전체가 FAIL. ③ model-serving 이미지 태그(`$MR`)와 model-runtime `HEAD`가 다를 수 있어 `build-images.sh:141`은 태그 시점 소스, 나머지 영역은 `HEAD`다(혼용). ④ 이미지 라벨의 model-runtime 표기가 `v` 유무가 영역마다 달라 `demo.sh:187`이 정규화한다. ⑤ 게이트도 `CONTRACT_COMPAT`로 같은 일치를 검사(G 참조).
- 왜: 정확 일치는 "영역이 서로의 구조(어느 파일에 버전을 적는가)를 안다"를 낳는다. 최소 수정: 영역이 `io.openit.contracts.*`(DP-12) 라벨 값만 내고 deploy는 라벨을 표와 비교(파일 파싱 불필요). 호환 규칙(정확/MINOR)은 계약 문서에 한 곳.

**DP-31 | R6 | P2 | 계약에 없는데 영역 경계를 넘는 형식 목록(E)**
아래는 이 영역이 쓰거나 이 영역을 통과하는데 `boundary-contracts`에 스키마가 없는 것이다.
1. 이미지 라벨 규칙(D50/D63) — DP-12.
2. 이미지 게시 인터페이스(`publish-image.sh` 인자·종료 코드·`PUBLISHED` 줄) 및 영역 `scripts/smoke.sh`·`scripts/setup-env.sh` 규약 — DP-12, DP-26.
3. 이미지 빌드 인터페이스(영역별 Dockerfile 인자, 빌드 도우미) — DP-01.
4. 잡 엔트리포인트·설정 스키마(synthetic-data `run`/`import`, ops-feedback `job`, release-gate `collect`/`prune`, survey/question-authoring `purge`, model-lab `run`) — DP-04~07, DP-28.
5. 서비스의 deploy 요구(`*_FILE` 이름, 포트, 볼륨, healthcheck, 노출 경로·역할) — DP-13, DP-14, DP-17.
6. `/readyz` 본문 필드 — DP-16. `/v1/info`의 `serving_config_expectation` — DP-09.
7. 모델 패키지 디렉터리 구조(`LORA_A/{adapter,manifest.json}`, `SUMMARY.json`)와 프로파일 JSON — DP-08.
8. question-authoring `/v1/signals`(`e2e_steps.py:1336`) — 계약 문서에 없음.
9. `docs/boundary.md:3-4`의 "계약을 소비하거나 생산하지 않는다"는 사실과 다르다: deploy는 `boundary_contracts.clients`·validator를 쓰고 PUBLIC_API의 `X-Openit-User` 규약과 CONVENTIONS 시간 사슬을 구현한다(확인: `e2e_steps.py:9-12`, `Caddyfile:36-38, 291-296`). 문서 오류(P2).
영역 안에서 정의됐지만 영역 경계를 넘는 deploy의 스키마: `locks/images.lock`(CI가 PR로 제출, D24), `docs/E2E_RESULTS.md` 표(다른 영역이 링크로 인용, 워크스페이스 규칙), `scripts/lib.sh` 버전 표(헤드 규칙이 정본으로 지명).

**DP-32 | R1 | P2 | gateway-lib·kiosk 장치 파일이 survey-service 내부 파일 형식(device 표)을 만든다**
- 위치: `scripts/gateway-lib.sh:64-68`
- 인용: `printf '%s=%s\n' "$id" "$(tr -d '\r\n' < "$D/tokens/kiosk-device-$id")" >> survey-kiosk-device-tokens`
- 왜: DP-17의 구체 예. "기기를 바꾸면 survey-service도 다시 시작해야 표가 바뀐다"는 이웃의 재적재 동작을 deploy가 안다(주석). 최소 수정: 계약에 `DeviceTokenTable` 형식과 재적재 방식(SIGHUP/주기 읽기)을 정의.

(P2는 DP-16 ~ DP-32, 17건)

### P3

**DP-33 | R3 | P3 | design.md에 컴포넌트·입출력 스키마 표가 없다**
- 위치: `docs/design.md`(절 제목 1~11, "구성 한눈에"는 Compose 서비스 중심). 왜: R2(영역은 컴포넌트를 가진다) 문서화 누락. 수정: 1절 표를 design.md로 옮기고 스키마 파일(DP-15) 링크.

**DP-34 | R7 | P3 | 같은 규칙의 반복 점검: 정적 점검 6개가 겹친다**
- 위치: `check_all.py:196-215`(규칙 1이 `check-versions.sh`를 호출), `check_versions.py`, `doctor.sh:124-125`(태그 존재), `e2e.sh:229-241`(라벨 6개), `publish-image.sh:51-55`(라벨 4개), `verify_area.py stale_images`(`images.env` 4열)
- 왜: 각각 부분적으로 "버전·라벨이 맞다"를 재확인한다. 라벨 규칙의 구현이 `publish-image.sh`(4개 필수)와 `e2e.sh`(6개)에서 다르다(확인). 영역이 게시한 값을 deploy가 한 번만 검증하면 충분하다(D104). 수정: 라벨 검사를 `publish-image.sh` 한 곳으로.

**DP-35 | R3 | P3 | 생성 파일 위치·이름 규약이 문자열로 흩어져 있다**
- 위치: `lib.sh:75`(`secret_mode`가 compose.yaml을 `sed`로 읽어 마운트되는 파일 이름을 뽑음), `check_secret_names.py`, `gen-secrets.sh`
- 인용: `sed -n 's|^[[:space:]]*file:[[:space:]]*${SECRETS_DIR:-./secrets}/\(tokens/\)\{0,1\}\([A-Za-z0-9._-]*\).*|\2|p' "$DEPLOY_ROOT/compose.yaml"`
- 왜: compose.yaml(구성)의 텍스트 모양에 gen-secrets(비밀 생성)가 기댄다. 컴포넌트 C6이 C7의 내부 서식을 안다. 수정: 비밀 목록을 `secrets.manifest.json` 하나로 두고 compose를 그것에서 생성/검증.

**DP-36 | R1 | P3 | docs/README가 이웃 사실을 산문으로 복사한다**
- 위치: `README.md:11-19`(이웃 표), `config/jobs.yaml:36`(synthetic-data 잡 설명), `docs/boundary.md:3절`(영역 표), `SETUP.md` F절(node 24)
- 왜: 워크스페이스 규칙 "이웃 영역의 사실은 복사하지 않고 링크한다"에 걸린다(환경 변수·잡 이름·ADR 번호 복사). 수정: 이웃 문서 링크로 치환.

(P3는 DP-33 ~ DP-36, 4건. 합계 15 + 17 + 4 = 36)

## 3. 이웃 구조를 아는 곳 전수와 "이웃이 자기 인터페이스로 제공해야 하는 것" 최소안 (요청 항목 2)

| # | 아는 곳 | 아는 이웃 구조 | 이웃이 제공할 것(최소) | 발견 |
| --- | --- | --- | --- | --- |
| 1 | `build-images.sh` | Dockerfile 인자 이름, 빌드 도우미 환경 변수, 빌드 컨텍스트 이름 | `scripts/build-image.sh` 하나(입력 JSON: 태그 3개·커밋 / 출력 JSON: 이미지 ID·라벨) | DP-01 |
| 2 | `build-images.sh` | `VERSIONS.env`, `contracts.tag`, `CONTRACT_VERSION`, `requirements.lock`, `package.json`, `pyproject.toml` 경로 | 이미지 라벨(`io.openit.*`)이 정본. 경로는 deploy가 몰라야 함 | DP-02 |
| 3 | `build-images.sh`, `prepare-host.sh` | 이웃 리포 소스 트리와 이미지 ↔ 영역 매핑 | CI 게시(digest 제출)만. 로컬 빌드는 영역 진입점 | DP-03, 19 |
| 4 | `e2e_steps.py` `sd_config`/`imp_config` | synthetic-data 잡 설정 키, 팩토리 경로, 종료 코드, 보고서 JSON, 환경 변수, 의존 버전 | JobConfig/JobResult JSON Schema + 예시 설정 생성기 + `setup-env.sh` | DP-04, 05 |
| 5 | `config/ops-feedback-job.yaml`, `compose.yaml:419` | ops-feedback 잡 설정 전체, 모듈 경로 | 영역 소유 운영 기본 설정 + `JobConfig` 스키마 + 잡 선언 라벨 | DP-06 |
| 6 | `config/release-gate.env`, `compose.yaml` 잡 4개 | 파이썬 팩토리·모듈·서브커맨드 | 잡 선언(`io.openit.jobs`), URL만 환경 변수 | DP-07 |
| 7 | `llm_attach_package.py`, `make-llm-package.sh` | model-runtime 파이썬 API, 프로파일 JSON, `make_neutral_package.py`, 어댑터 파일명 | model-runtime의 `attach-package` 진입점(출력은 `ModelPackageManifest` 디렉터리) | DP-08 |
| 8 | `e2e_steps.py` `make_packages` | `/v1/info.serving_config_expectation`, 서빙 설정 필드, 패키지 매니페스트·평가 보고서 조립 | I9 `/v1/info` 계약 확장 또는 중립 패키지 생성 진입점 | DP-09 |
| 9 | `e2e_steps.py:1215` | survey-service `risk_rules.py`의 `_PROVISIONAL` | 위험 문구를 계약 API/설정으로 노출 | DP-10 |
| 10 | `check_all.py`, `check_versions.py`, `check_secret_names.py` | 모든 영역의 소스·Dockerfile·`read_secret` 호출, model-runtime `schema_guard`, turn-engine 모듈 | 영역이 `boundary.json`(소비 버전, `*_FILE` 이름)을 낸다. 계약 점검은 계약 패키지 conformance로 | DP-11 |
| 11 | `publish-image.sh`, `e2e.sh`, `demo.sh` | 라벨 키·값 표기(`v` 유무), `smoke.sh` | `IMAGE_LABELS.md` + 스키마, `PUBLISH.md` | DP-12 |
| 12 | `Caddyfile` | 경로·메서드·역할·토큰 파일·헤더 | 서비스별 `exposure.json` + 계약의 역할 이름 집합 | DP-13 |
| 13 | `compose.yaml` | `*_FILE` 이름 35개, 포트 8080, `/data`, `python`/`wget`, 읽기 전용 루트 | `deploy-manifest` 스키마(포트, 건강, 비밀, 볼륨, 잡, 노출) | DP-14 |
| 14 | `gen-secrets.sh`, `gateway-lib.sh` | 토큰 목록 형식(`토큰:사용자:역할`, `device_id=토큰`), 서비스별 역할 | `TokenTable` 형식과 역할 목록을 `deploy-manifest`에 | DP-17, 32 |
| 15 | `backup_tool.py`, `backup.sh` | 볼륨 안 폴더(`releases`, `.tmp`) | `deploy-manifest.volumes[].backup` | DP-18 |
| 16 | `status.sh`, `e2e_asserts.py` | `/readyz` 본문 키 | `ReadyzBody` 스키마 | DP-16 |
| 17 | `prepare-areas.sh`, `verify_area.py`, `doctor.sh` | `setup-env.sh`, `.venv`, pytest/npm, `gen-schemas.mjs`, node 하한 | `areas.json`에 명령 필드(헤드) | DP-26 |
| 18 | `test/fake-model/question_flow.json`, `compose.fake-model.yaml` | model-runtime 가짜 흐름 파일 형식과 환경 변수 | `FakeFlow` 스키마와 생성 도구 | DP-27 |
| 19 | `e2e_gpu.sh` | model-lab 설정 경로·진입점·환경 변수 | model-lab `run-once` 인터페이스 | DP-28 |
| 20 | `lib.sh` 버전 표 | 영역이 버전을 적는 파일 | 라벨(1, 11행) | DP-30 |
| 21 | 경로 `../x` | `../survey-service`(clone, `schema/`), 모든 형제(소스) | 허용 3경로 외는 제거 | DP-03, 11 |

## 4. E2E가 이웃 형식을 직접 만들어 넘기는 곳 전수 (요청 항목 3)

| 대상 | 위치 | 만드는 것 | 소유 영역 |
| --- | --- | --- | --- |
| synthetic-data run 잡 설정 | `e2e_steps.py:234-248` | JSON(`adapters`, `question_sets`, `seeds`, `split`, `review`, `regeneration`, `output`) | synthetic-data (DP-04) |
| synthetic-data import 잡 설정·입력 | `e2e_steps.py:262-275`, `test/import-v2/*.jsonl`(`make_rows.py`) | `input_dir`, `tolerance`, v2 jsonl 6개(행 형식은 "추정"이라고 스스로 적음, `e2e_steps.py:280`) | synthetic-data / 데이터 담당 (DP-05) |
| ModelPackageManifest(2건), EvaluationReport(2건), serving_config | `e2e_steps.py:326-385` | 계약 스키마 통과 레코드 | model-lab (DP-09) |
| 어댑터 패키지(중립) | `test/fixtures/e2e-test-adapter/*`, `make-llm-package.sh`, `llm_attach_package.py` | `LORA_A/{adapter,manifest.json}` | model-runtime/model-lab (DP-08) |
| ops-feedback 잡 설정 | `test/ops-job/test-ops-job.yaml`, `config/ops-feedback-job.yaml` | 비식별·탐지·보존 | ops-feedback (DP-06) |
| 가짜 모델 흐름 | `test/fake-model/question_flow.json` | `order`/`slots`/`corrections`/`reasks` | model-runtime (DP-27) |
| 문항 양식 | `test/fixtures/question-form-v2.txt` | question-authoring 업로드 입력(문항 ID 31개) | question-authoring/survey (DP-27) |
| GateSubmission 제출 | `e2e_steps.py:471, 1611`(`submit_candidate`) | `subject`, `requested_by_role` | release-gate (계약 I5, 클라이언트 사용: 정상) |
| TraceEnvelope(단계 6), reviewed_input(7), FailureCase 검토 게시 | `e2e.sh` 배너(110행 부근 "단계 6 TraceEnvelope와 단계 7 ... 시험 자료") | 계약 스키마 레코드 | ops-feedback (계약 I6/I7: 계약 안, 정상) |
| 승인 `POST /v1/approvals` | `e2e_steps.py:427-452` | 계약 `GateApproval` | release-gate (계약 I5: 정상) |

위 중 "계약 안(정상)"으로 표시한 것은 `boundary_contracts.clients`와 계약 스키마로 만들므로 R1 위반이 아니다. 위반은 앞 7행.

## 5. 게이트웨이가 이웃 API를 아는 곳과 정본 (요청 항목 4)

DP-13의 표 참조. 정본 대조 결과(확인):
- 시간 사슬: `Caddyfile:288-296`의 키오스크 경로 연결 1s + 응답 헤더 8.5s = 9.5s는 `CONVENTIONS.md:119`와 일치. 읽기 `/readyz` 2s(`Caddyfile:94`)는 `CONVENTIONS.md:111`(서비스 readyz 2초)과 일치.
- 상류 장애 응답: 503/504 + `{"code":"UPSTREAM_UNAVAILABLE"}`는 `CONVENTIONS.md:89`와 일치(본문이 BoundaryError가 아님을 계약이 명시).
- `X-Openit-User`: 클라이언트 값 제거·덮어쓰기는 `HTTP.md:86`·`PUBLIC_API.md:93`과 일치(`Caddyfile:36-38, 115, 147, 163` 등 `header_up X-Openit-User "{http.auth.user.id}"`, 키오스크·정적 경로는 `-X-Openit-User`).
- 승인 4경로(`GET /v1/submissions`, `/v1/submissions/*`, `POST /v1/approvals`)와 `POST /v1/submissions` 차단은 `HTTP.md:71-86`(D53)과 일치. `X-Openit-Report-Hash` 통과.
- 정본이 없는 것: 노출 경로 ↔ 역할 표, 역할 이름, 서비스별 토큰 파일 이름. `/v1/staff/alerts/stream`(SSE)의 `flush_interval -1`·`read_timeout 1h`는 `PUBLIC_API.md`의 SSE 설명(15초 ping)을 근거로 deploy가 정한 값이다(근거 ADR 없음: 확인 못 함, `adr/0002-caddy-gateway.md`는 Caddy 선택 이유이고 타임아웃은 `ADR 0003`).

## 6. 항목 C (R5): deploy 안 컴포넌트 사이 스키마

정의 위치: `deploy/schemas/` 같은 폴더 없음(`find . -name "*.schema.json"` 결과 0건, build/.venv 제외). 기계가 읽는 정의는 `e2e_plan.py:26`의 `@dataclass(frozen=True) class Decl`(E2E 단계 선언) 하나뿐이다. 암묵인 곳: DP-15에 나열(`images.env`, `images.lock`, `registry.env`, `jobs.yaml`, `verify-areas.yaml`, `backup.env`, `gateway-accounts.conf`, `scheduler.json`, e2e `STATE`, `E2E_RESULTS.md` 표, `check-health` 대상 yaml, 비밀 파일 이름 규칙). 검증은 소비자 쪽 `sed`·정규식·손 검증 코드(`scheduler.py:24-33`, `gateway-lib.sh:18-32`, `verify_area.py`)로 각자 한다.

## 7. 항목 F: 계약 준수 대조

대조한 계약 문서: `HTTP.md`, `PUBLIC_API.md`, `CONVENTIONS.md`(시간 사슬, 401/403, readyz/healthz, 상류 장애 응답), `INTERFACES.md`(I9 일부), `METRICS.md`(첫 줄만).
- deploy가 제공하는 서버형 인터페이스는 gateway뿐이다. 일치한 것은 5절. 불일치·계약 밖은 DP-09(`/v1/info` 필드), DP-16(readyz 본문), DP-13(`/v1/signals` 계약 밖), DP-29(`requested_by_role`).
- 상태 코드: gateway의 키오스크 경로 기기 토큰 없음 401(`Caddyfile:300-303`)은 `CONVENTIONS.md:86`(공개 API는 토큰 없으면 401)과 일치. 직원 경로의 역할 부족 403(`respond "forbidden: staff 역할이 아니다" 403`)도 일치. `/healthz`는 gateway 평문 포트가 정적 200(`Caddyfile:41-43`)이어서 "의존과 무관하게 200"(`CONVENTIONS.md:110`)과 일치. `/readyz`는 survey로 프록시하며 상류 2xx만 통과(`Caddyfile:96-104`): 이 gateway 동작 자체는 계약에 없다(계약은 서비스의 readyz만 정의).
- 멱등·타임아웃: `lb_try_duration 0`(재시도 없음)은 `CONVENTIONS.md` 사슬 취지와 맞지만 "gateway는 재시도하지 않는다"를 명시한 계약 문장은 확인하지 못했다(미확인).
- 적합성 시험: `boundary-contracts/conformance/`(`servers.py`, `examples`)는 서버·클라이언트 참조 구현이다. deploy는 계약 서버를 제공하지 않으므로 해당 없다. `verify.py`는 계약 리포를 건드릴 수 있어 돌리지 않았다(실행하지 않음). `deploy/scripts/check-all.sh`·`test-*.sh`도 이번 점검에서는 실행하지 않았다(점검 규칙이 코드 읽기이고 docker가 필요한 시험은 실행 환경을 바꾼다).

## 8. 항목 G: R7 이중 검증·재구현

R7 대상은 deploy가 이웃 출력을 다시 검증·재구현하는 곳이다. 영역 경계의 환자 입력 검증은 해당하지 않는다.
- DP-34: 버전·라벨 일치를 6곳이 부분적으로 재확인(P3).
- DP-21: 잠금 파일 쓰기와 digest 대조를 두 스크립트가 따로 구현.
- DP-08: `ModelPackageManifest` 조립을 model-runtime의 `make_neutral_package.py`와 다시 구현("출력 구조는 ... 와 같다").
- DP-25: `metrics()` 접근자를 파일 직접 읽기로 재구현(대체 경로).
- `e2e_steps.py`의 `validate("GateSubmission", x)` 등(473행 등) — 서비스가 낸 레코드를 E2E가 계약 검증기로 확인한다. 이것은 합격 시험(적합성 확인)이며 컴포넌트가 이웃의 출력을 믿고 쓰지 않는 구현이 아니므로 R7 위반으로 세지 않았다. 다만 `e2e.sh` 준비 단계의 `check-all` 규칙 5("하드코딩된 계약 문자열", `check_all.py:635-`)와 게이트의 `CONTRACT_COMPAT`·`validator`가 같은 규칙(`pipeline_schema_version` 일치)을 재구현하는 점은 DP-34에 포함.

## 9. 문제없음 항목과 확인 범위

읽은 파일: `CLAUDE.md`, `docs/brief.md`, `README.md`, `docs/SETUP.md`, `docs/boundary.md`(앞 60줄), `docs/ci.md`(앞 20줄), `docs/design.md`(제목 목록), `docs/adr/0033-check-all-structured-only.md`, `scripts/lib.sh`, `areas.py`, `build-images.sh`, `publish-image.sh`, `publish-images.sh`, `scheduler.py`, `run-job.sh`, `prepare-areas.sh`, `prepare-host.sh`, `make-llm-package.sh`, `llm_attach_package.py`, `gen-secrets.sh`, `gateway-lib.sh`(앞 70줄), `check_versions.py`, `check_secret_names.py`, `check_all.py`(주요 규칙 발췌), `status.sh`(앞 40줄), `e2e_steps.py`(1~330, 330~385, 1212~1235, 설정 구성 부분과 grep으로 전수 색인), `e2e_gpu.sh`, `e2e.sh`(100~140, grep 색인), `demo.sh`(175~190), `config/Caddyfile`(전체를 grep 색인하고 20~64, 107~128, 281~353 정독), `config/jobs.yaml`, `config/verify-areas.yaml`, `config/ops-feedback-job.yaml`, `config/*.env`, `compose.yaml`(구조 전체를 `grep -n`으로 색인, 1~34 정독), `compose.test.yaml`, `test/compose.fake-model.yaml`, `test/fake-model/question_flow.json`(앞 600바이트). 계약: `HTTP.md`, `PUBLIC_API.md`, `CONVENTIONS.md`는 관련 절을 읽었다. `head/shared/areas.json`.

문제없음으로 판단한 것(방법):
- 비밀 취급: `grep -n "env_file\|_FILE"`로 compose의 토큰이 환경 변수 평문이 아니라 `NAME_FILE` 경로임을 확인(D84 준수). 이는 이번 구조 규칙 범위 밖이므로 결함으로 세지 않았다.
- `boundary_contracts` 사용: `e2e_steps.py:9-12`, `e2e_verify_restore.py:4-6`, `llm_attach_package.py:80-81`의 import는 계약 패키지의 `clients`·`validator`·`canonical`·`PIPELINE_SCHEMA_VERSION`으로 허용 범위다. 단 `llm_attach_package.py`의 `model_runtime` import는 DP-08.
- `prepare-areas.sh`는 영역 목록을 `areas.json`(허용 경로)에서 읽고 `setup-env.sh`를 부를 뿐 설치 명령을 복사하지 않는다(주석 10행). 그 규약이 계약에 없는 점만 DP-26.
- 시간 사슬 값(gateway 1s + 8.5s 등)은 계약과 일치(5절).
- 이웃 DB를 읽지 않는다: deploy 코드는 PostgreSQL 컨테이너를 직접 다루는 `pg-*.sh`, `e2e_steps.py:1863-1869`의 `psql` 호출이 있다. 이는 deploy가 소유하는 인프라(PG 서버)에 대한 조작이고 이웃 테이블 스키마를 읽는 것이 아니다. 단 `select tablename from pg_tables ... limit 1`(5b 단계)은 QA 테이블 이름을 임의 하나로 잡을 뿐 이웃 테이블 구조에 기대지 않는다(확인).

## 10. 점검하지 못한 것

- 이웃 영역의 현재 스키마·소스(synthetic-data 잡 설정, ops-feedback `JobConfig`, release-gate 팩토리, model-runtime API)는 읽기 허용 밖이라 읽지 않았다. 그래서 DP-04의 "제거된 v1 키"가 정확히 무엇인지, DP-06·07의 이름이 현재 맞는지는 대조하지 못했다. "이웃이 이름을 안다"는 구조 사실만 증거로 썼다.
- `e2e_steps.py`(1925줄)는 설정 구성·모델 패키지·정적 점검 호출·게이트웨이 단계의 핵심만 정독했고 나머지는 `grep` 색인으로 이웃 형식 사용처를 찾았다. 5계열(5c, 5m, 5n, 5s ...)과 6, 7 단계 본문, `e2e_asserts.py`, `e2e_verify_restore.py`, `probe-serving.py`는 정독하지 않았다.
- `check_all.py`는 규칙 0~11 중 규칙 1, 3, 4, 5의 일부만 읽었다. 규칙 2, 6, 7, 8, 11의 상세는 읽지 않았다.
- `compose.yaml`의 리소스·네트워크 절, `compose.llm*.yaml`, `compose.inference.yaml`, `compose.external-inference.yaml`, `compose.registry.yaml`, `config/postgres/`, `config/systemd/`, `backup*.sh`·`restore*.sh`·`pg-*.sh`·`rotate-account.sh`·`kiosk-add-device.sh`·`check-*.sh`의 본문, `down.sh`·`up.sh`·`rollback.sh`·`registry.sh`는 이름·`grep`으로만 확인했다.
- `docs/RUN.md`(365줄), `runbook.md`, `E2E.md`, `STATUS.md`, `change-requests/*`(CR-D01~D26), 다른 ADR(0001~0032)은 읽지 않았다(이미 알려진 결정이 R1 판단을 바꿀 수 있다: 예 `adr/0032-dataset-store-boundary.md`).
- `boundary-contracts`의 `INTERFACES.md`, `METRICS.md` 본문, `schemas/`, `conformance/`는 필요한 부분만 `grep`했다. 계약 conformance 시험과 deploy의 `test-*.sh`, `check-all.sh`는 실행하지 않았다.
- 실제 실행 상태(컨테이너, 이미지 라벨 실값, 레지스트리)는 보지 않았다(docker 명령을 쓰지 않았다). 따라서 "이웃 이미지에 `python`/`wget`이 있다"(DP-14)는 compose 정의에서 읽은 가정이지 이미지를 열어 본 것이 아니다.
- 읽은 `docs/boundary.md`는 앞 60줄뿐이라 "장애 영향" 절 이후는 보지 못했다.
