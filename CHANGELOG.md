# 변경 이력

## wo-300: 계약 3.0.0 전환 (deploy 몫)
- 기준표: `DEPLOY_BC_TAG` v3.0.0. `DEPLOY_TE_TAG`·`DEPLOY_TE_VERSION`을 지웠다(D109). 문진 스키마는 survey-service가 2.0.0을 낼 때까지 survey-schema-v1.3.0 그대로. compose의 `SURVEY_TURN_ENGINE_VERSION`·`GATE_TURN_ENGINE_VERSION` 환경 변수 4곳을 지웠다: 규칙 세대 표지는 서비스가 설치된 계약의 `ActionExtractionRules.rules_version`에서 읽는 것으로 가정한다(해당 영역의 wo-300; 영역이 여전히 이 환경 변수를 요구하면 헤드가 알려야 한다).
- `build-images.sh`의 BuildImageRequest에는 `versions.turn_engine`이 없었다(U42에서 이미 뺐다). `images.env` 도장 스키마에서 `te=`를 뺐다. 이미지 라벨 `io.openit.turn-engine` 기대값을 시험 고정값에서 지웠다(3.0 ImageLabels가 거부한다).
- check-all 규칙 4: turn-engine 공개 API 대조를 지우고, 어느 영역이든 `turn_engine`을 import하면(정적·`__import__`·`importlib`) FAIL로 바꿨다(퇴역 확인). turn-engine 리포 자신은 제외한다. 프롬프트 템플릿 검사는 그대로.
- E2E: 매니페스트·잡 설정의 `turn_engine_version`을 `action_rules_version`으로, 값은 `boundary_contracts.action_rules.load_rules()["rules_version"]`(리터럴 없음, `test_e2e_action_rules_version.py`가 지킨다). extract 호출 3곳과 `probe-serving.py`는 `ExtractRequest{input, flow, fields}`로 보낸다(fields는 가짜 백엔드 흐름 파일의 slots에서 만든다). 5의 추론 서버 직접 호출 단계는 옛 본문·fields 없는 요청·skips 없는 flow가 400임을 확인한다. `llm_attach_package.py` 매니페스트, ops-feedback 잡 설정(`scrub_string_keys`, `scrub_patterns` 삭제)을 3.0에 맞췄다.
- StaticImageInterface는 deploy 코드에 없었다(포트·사용자는 U47에서 이미지 OCI 설정으로 읽는다). 주석만 갱신했다.
- 발견(고치지 않음): `config/ops-feedback-job.yaml`의 `rollback: null`이 계약 `OpsFeedbackJobConfig`(rollback은 object)를 어긴다. 2.7.0에서도 같았다. 값은 사용자 결정 전이라 deploy가 정하지 않는다(ops-feedback이 null을 받는다면 계약 변경 요청 후보).

## wo-30 후속: U48 안 A (위험 규칙 파일 주입)
- E2E가 survey-service 내부 `risk_rules.py`를 읽던 `risk_phrase_from_defaults()`를 지웠다. deploy가 시험용 규칙 파일 `test/risk-rules.e2e.json`(계약 SurveyRiskRulesFile, 임상 규칙 아님)을 만들고 `test/compose.risk-rules.yaml`(E2E 전용, `e2e.sh`의 `COMPOSE_EXTRA`)로 survey-service의 `SURVEY_RISK_RULES_FILE`에 마운트한다. 운영 compose에는 연결하지 않는다(시험 문구가 운영에서 켜지면 안 된다). 5f·5m·5n은 그 파일의 문구를 쓴다.
- 5f의 옛 검사 "임시 기본 목록(PROVISIONAL_DEFAULT) 켜짐, provisional=true, clinically_reviewed=false"는 규칙 파일을 주입하면 성립하지 않아 뺐고 `active=true`와 `rule_count == 규칙 수`로 바꿨다. 규칙 파일일 때 `/readyz`의 source·provisional 값은 deploy가 알지 못해 단정하지 않는다(첫 E2E에서 실제 값을 보고 정할 일).
- `test-no-guessed-paths.sh`가 이웃 영역 소스 파일 읽기(`ROOT.parent / "<영역>/…"`, `risk_rules.py`)도 잡는다.
- 기준표는 v2.7.0 그대로다(헤드: 곧 3.0.0으로 한 번에 옮긴다). SurveyRiskRulesFile 스키마는 설치된 패키지(2.7.0)에 없어, `E2E`는 검증하지 못했다는 안내를 내고 `test_risk_rules_file.py`의 스키마 검증은 SKIP으로 출력한다(통과로 세지 않음). v2.8.0 패키지로는 통과를 확인했다.

## wo-30: U47 deploy 몫 (노출 선언 대조, PublishResult, SyntheticJobError)
- `scripts/check-exposure.sh`(+`check_exposure.py`, ADR 0043): `config/Caddyfile`을 영역 이미지의 라벨 `io.openit.exposure`(계약 Exposure)와 대조한다. 생성이 아니라 대조인 이유는 ADR(Exposure가 CSRF·mTLS·SSE·상태 변환 같은 게이트웨이 기능을 아직 표현하지 못한다). 포트·사용자는 이미지 OCI 설정(`ExposedPorts`, `User`)에서 읽는다. 알려진 어긋남 2건은 `config/exposure-known-diffs.json`에 이유와 함께 둔다. e2e.sh 자체 점검에 포함.
- `publish-image.sh`: 표준 출력 마지막 줄이 계약 `PublishResult` JSON이다(모든 종료 코드 0~5; `--help` 제외). 옛 `PUBLISHED|UNCHANGED …` 문자열 줄은 없다. `docs/ci.md`, `docs/ci-example/publish-image.yml`을 맞췄고 `test-publish.sh`가 마지막 줄을 계약 validator로 검증하고 `exit_code`가 실제 종료 코드와 같은지 본다.
- `sd_jobs.describe_failure`: 잡 종료 코드 2의 stderr 마지막 줄을 계약 `SyntheticJobError`로, 3·75는 `BoundaryError`로 읽어 보고한다(검증 실패나 JSON이 아니면 그 사실을 적는다). E2E의 `run_job`은 종료 코드 2를 설정 오류로 바로 보고한다.

## wo-29: 기준표 bc v2.7.0·문진 스키마 v1.3.0, U43 소비(CR-D30 3단계), U48 CR
- 기준표: `DEPLOY_BC_TAG` v2.7.0, `DEPLOY_SS_TAG` survey-schema-v1.3.0 (model-runtime v0.10.0 그대로).
- 영역 시험 환경: `prepare-areas.sh`가 영역 `setup-env.sh` 표준 출력 마지막 줄을 계약 `SetupEnvReport`로 검증해 `state/setup-env/`에 모은다(`scripts/setup_env_report.py`). `doctor.sh`, `check_all.py`(규칙 3·8), `verify_area.py`는 그 보고의 `environment.path`·`test_command`만 쓴다. 이웃의 `.venv/bin/python`, `node_modules`, pytest/npm 짐작을 지웠다. 규칙 8은 수집이 아니라 보고된 `test_command` 실행이다(영역이 정한 명령이라 collect-only를 deploy가 만들 수 없다). 그래서 규칙 8이 시험 시간만큼 걸린다(측정: 4개 영역 약 140초, check-all 전체).
- synthetic-data 잡: 호스트 `build/venv-sd`·영역 소스 사본·cwd를 지웠다. `e2e_steps.py`가 dataset-store 이미지의 라벨 `io.openit.jobs`(JobsDeclaration)를 읽어 `docker run <이미지> <argv>`로 돌린다(`scripts/sd_jobs.py`). 설정은 `SyntheticJobConfigRun/Import` 스키마로 먼저 검사해 `config.container_path`에 마운트하고, 비밀은 `secret_files`(NAME_FILE)로 넘긴다. 실제 이미지로 import 잡을 돌리는 시험 `test_sd_jobs.py`. `prepare-host.sh wheels`는 호스트 잡 환경을 더 만들지 않는다.
- 짐작 경로 검사 `scripts/test-no-guessed-paths.sh`(e2e.sh 자체 점검에 포함). 예외와 이유: deploy 자신의 `.venv`, 저장소 스캔에서 건너뛸 폴더 목록, 계약이 설정 값으로 정한 `adapters.factory`(`synthetic_data.adapters:...`, 계약 SyntheticJobConfigRun), `e2e_gpu.sh`의 model-lab GPU 잡(영역이 잡을 아직 선언하지 않음: 영역 쪽 선언이 필요한 남은 구멍).
- `docs/change-requests/CR-U48-risk-rules-read.md`: E2E가 survey-service 내부 `risk_rules.py`를 읽는 곳과 대안(코드 변경 없음).

## build-images: 영역 리포 루트에서 진입점을 부른다 (git archive 사본 아님)
- kiosk-frontend 의 새 진입점(0e94776)이 `Cannot find module 'ajv/dist/runtime/equal'`로 실패했다: 진입점이 영역의 `node_modules`(setup-env 가 준비한 환경)를 쓰는데 git archive 사본에는 환경이 없다. 진입점은 영역이 정하므로(구조 규칙 1) deploy 가 환경을 추측해 사본에 링크하지 않고, 계약 BuildImageRequest 의 `source_dir`(영역 리포 루트) 그대로 영역 리포 루트에서 부른다. 이미지가 HEAD 와 같도록 추적 파일에 커밋 안 된 변경이 있으면 멈춘다(`BUILD_ALLOW_DIRTY=1` 은 개발 중에만). 추론 서버(model-runtime)만 기준표 태그 시점의 소스가 필요해 태그의 git archive 사본을 쓴다.
- e2e_steps 의 `risk_rules.py` 읽기는 사본 대신 survey-service 리포 경로를 읽는다(영역 내부 파일 읽기라 여전히 정리 대상).

## wo-28 후속: 사본 정리와 verify_area 정본 일원화
- `test_verify_area.py::test_image_src_matches_build_images_sh`가 `declare -A SRC`를 찾다가 깨졌다. 서비스->리포 대응의 정본은 `lib.sh`(`SERVICES`, `service_repo`) 한 곳이라 `verify_area.IMAGE_SRC`가 셸에 물어 만든다(두 정본 금지). 시험은 `lib.sh`와 같은 값인지, 알려진 대응(model-registry->model-lab 등)이 맞는지, 코드에 따로 적은 표가 없는지 본다.
- `test_contract_schema_copy.py`가 5c61298부터 실패했다(`contract-ready/schemas` 사본 4개 BuildImageRequest·BuildImageResult·JobsDeclaration·SetupEnvReport가 계약 패키지와 어긋남). 사본은 승격 전 임시 정본이었고 지금 정본은 계약 패키지다. 공통 규칙(스키마는 패키지에 있고 복사본을 만들지 않는다)에 따라 `docs/change-requests/contract-ready/`의 스키마·예시·검증기·MANIFEST와 `docs/change-requests/schemas/`(CR-D27 초안)를 지웠고(README는 승격 기록으로 남김), `check_image_labels.py`의 사본 폴백을 없앴다(패키지가 없으면 종료 2). 시험은 패키지에 deploy 경계 스키마 8개가 있고, 리포에 계약 스키마 사본이 다시 생기지 않았고(deploy 자신의 내부 형식 `schemas/`는 허용), 검사기가 패키지를 쓰는지 본다.
- 문진 스키마 호스트 wheel(E2E 검증기용)을 survey-service 빌드 산출물(`build/ctx/survey-service/build/wheels`)이 아니라 `dependency_sources.survey_schema`(기준표 태그의 schema/)로 `build-images.sh`가 만들어 `build/hostwheels/survey-schema/`에 둔다(`prepare-host.sh`가 거기서 설치).

## build-images: 영역 Dockerfile 인자·빌드 산출 파일을 모른다 — 영역 `scripts/build-image.sh`만 부른다 (U42, 구조 규칙 1)
- 서비스마다 계약 BuildImageRequest JSON(`source_dir`, `revision`, `versions`=lib.sh 기준표, `dependency_sources`=기준표 태그에서 `git archive`로 꺼낸 boundary-contracts·model-runtime·survey-service `schema/`, `variant`, `image_tag`)을 `build/ctx/req-<서비스>.json`에 쓰고 영역 리포 루트(model-runtime만 기준표 태그의 git archive 사본)에서 `bash scripts/build-image.sh <요청>`만 부른다. 결과(표준 출력 마지막 줄)는 BuildImageResult로 검증하고 `image`가 요청과 같은지, `image_id`가 로컬 이미지 ID와 같은지 확인한 뒤 `images.env`에 기록한다.
- 지운 것: 영역별 Dockerfile 인자(COMMIT, REVISION, BOUNDARY_*, CONTRACTS_VERSION, MODEL_RUNTIME_*, SURVEY_SCHEMA_*, LANGGRAPH …), 영역 산출 파일 읽기(VERSIONS.env, contracts.tag …), wheel 만들기, `--build-context`, `verify_mr_label`(영역 내부 모듈 이름을 알았다), survey-service·release-gate clone.
- 서비스 -> 리포·variant 대응은 `lib.sh`의 `service_repo`·`service_variant` 한 곳이다(서비스 목록과 같은 자리).
- 서비스 빌드 전에 deploy venv의 계약을 기준표 태그로 맞춘다(영역 진입점이 요청을 PYTHON의 계약 validator로 검증하므로). **기준표 `DEPLOY_BC_TAG`를 v2.6.0으로 올렸다**: BuildImageRequest가 turn_engine 없이 versions.boundary만 요구하는 판은 2.5.0부터다(v2.4.1의 스키마는 turn_engine을 요구해 진입점 요청이 거부된다). 다른 영역이 아직 2.6.0 아래 핀이면 이미지 라벨이 표와 다르다고 `check-versions`가 알린다.
- 시험: `test-build-images.sh`(가짜 영역 진입점·가짜 docker, 16건: 요청 값, 서비스->리포 대응, GPU variant, 진입점 실패·결과 계약 위반·image 불일치·image_id 불일치·진입점 없음), `test-build-images-static.sh`에 영역 빌드 이름 금지 검사 추가(옛 스크립트로는 22건 실패, 새 스크립트는 통과). 실제 빌드: main에 진입점이 있는 5곳(ops-feedback, model-lab, synthetic-data, kiosk-frontend, admin-console)을 빌드해 `check-versions` 통과. 나머지 4곳(release-gate, model-runtime, question-authoring, survey-service)은 영역 wo-42 합치기를 기다린다.
- e2e_steps: 이웃 소스 사본의 경로가 `build/ctx/src/<서비스>`로 바뀌었다(`risk_rules.py`를 읽는 한 줄은 영역 내부 파일 읽기라 따로 정리가 필요하다).

## 계약 소비 정리 (U44·U46, U43 설계안)
- U44: 이미지 라벨 검사가 두 번이던 것을 계약 ImageLabels 검증 하나로 정리했다. `publish-image.sh`는 필수 키를 손으로 먼저 보고 `:57`에서 계약 검증을 또 했고, `e2e.sh`의 `labels6`/`labels_kiosk`도 키를 따로 봤다. 모두 `validate_image_labels`(`check_image_labels.py`) 하나만 부른다(필수 4개 존재·빈 값·revision 형식·n/a 표기·오타 키는 스키마가 본다).
- U46: `docs/boundary.md`·`docs/brief.md`의 "계약을 소비하거나 생산하지 않는다"를 사실로 고쳤다(소비 중: ImageLabels(+JobsDeclaration·Exposure), E2E의 validator·clients·metrics·canonical / 아직 쓰지 않음: BuildImage*, SetupEnvReport, Publish*). `PublishRequest.service` enum과 `lib.sh` 서비스 목록은 시험 `scripts/test_services_enum.py`로 같음을 보장한다(계약 enum이 정본, 어긋나면 실패; 점검 자체도 단위 시험).
- U43 준비: 이웃의 `.venv`·`node_modules`·synthetic-data 실행을 추측하는 곳의 목록과 SetupEnvReport·영역 진입점으로의 설계안을 `docs/change-requests/CR-D30-setup-env-report.md`에 적었다(코드 변경 없음).

## check-versions: 영역 소스 grep 대신 빌드된 이미지 라벨을 기준표와 비교 (U39, ADR 0042)
- 옛 점검이 model-runtime Dockerfile의 `ARG BOUNDARY_VERSION=...`을 놓쳤다(영역마다 핀 이름이 달라 패턴을 따라가는 방식의 한계, 구조 규칙 1·6 위반). `check-versions.sh`가 `build/images.env`의 이미지 라벨(`contracts.boundary`, `model-runtime`, `contracts.survey-schema`)을 `lib.sh` 표와 비교한다. `check_versions.py`(소스 grep)는 지웠다.
- 이미지가 없으면 종료 3(검증하지 못함): check-all은 SKIP, E2E의 빌드 전 check-all은 `CHECK_ALL_IMAGES=defer`(대상 아님+이유), 빌드 뒤 E2E 점검은 3을 실패로 본다.
- 시험: `test-check-versions.sh`를 가짜 docker 라벨로 다시 썼다(11건: 같으면 0, 계약·model-runtime·문진 스키마·빈 라벨 어긋남 1, 이미지·기록·docker 없음 3). `test-check-all.sh`에 종료 3 -> SKIP, defer -> 대상 아님 사례를 더했다.

## e2e.sh 옵션 처리: 모르는 옵션을 거부하고 --only 와 --sections 조합을 사용 오류로
- `bash scripts/e2e.sh --help`가 전체 E2E를 시작했다(모르는 옵션이 조용히 무시됐다). 이제 맨 앞(정적 점검·doctor·빌드 앞)에서 옵션을 검사한다: `-h/--help`는 사용법만 내고 0, 모르는 옵션·값 없는 `--only/--sections`·알 수 없는 구간은 사용법을 표준 오류로 내고 2. 시험 `scripts/test-e2e-options.sh`(수정 전 8건 실패 -> 통과 8건)를 e2e.sh 앞단 자체 점검에 넣었다.
- `--only 5r --sections jobs,backup,rollback`은 뒷구간이 전제하는 상태(수집기 실행 기록, 문항 버전, 활성 릴리스, 단계 4~8의 산출물)가 없어 FAIL 3건이 났다. **거부(사용 오류)로 정했다.** 이유: (1) 자동으로 선행 단계를 함께 돌리려면 구간별 필요 단계 표를 따로 유지해야 하는데 이미 `e2e_plan.py`/`@step`의 deps가 정본이라 표가 둘이 된다. (2) 뒷구간이 실제로 필요로 하는 것은 단계 1~8 전체(수집기 로그, `e2e_verify_restore.py`가 읽는 문항·모델 패키지·Trace·포인터)라 `--only`로 줄여 얻는 시간이 없다. (3) 조용히 더 많은 단계를 돌리면 사용자가 지정한 범위와 실제 실행이 어긋난다. 뒷구간만 보려면 `--sections`만 준다(단계 1~8을 모두 돌린다).

## E2E 후속(전체 E2E 첫 실행에서 나온 3건)
- 단계 5o: 진행 시뮬레이션이 칸 없는 문항(Q3, Q4_1, Q5_1 …)에서 `KeyError: 'Q3'`로 멈췄다(`types[q]`). 칸이 없으면 값 없이 NEXT 만 나오므로 `types.get(q)`로 처리한다. 그 뒤 마지막 두 턴의 turn_id(`rng-8`, `rng-9`)가 진행 루프의 turn_id와 겹쳐 409 였다 -> 고유 id. `--only 1,2,3,4,5o` 로 5o REAL 통과(6.0s).
- `test-systemd-units.sh`의 "scheduler.py 참조" 점검이 git 이 추적하지 않는 `__pycache__/*.pyc` 를 찾았다 -> `git ls-files` 로 추적 파일만 본다(리포 밖이면 `__pycache__`·`*.pyc` 제외).
- e2e 정리가 감시 compose 프로젝트의 네트워크(`<프로젝트>_monitoring`)를 남겼다: 정리의 `down`이 `compose.monitoring.yaml`을 읽지 않아 그 파일에만 있는 네트워크를 몰랐다 -> 정리에서 그 파일을 포함해 내린다.

## 버전 열차 올림과 D115(LoRA-A 출력 값 규칙) E2E 단계 5o
- `lib.sh` 기준표: boundary-contracts v2.4.1, model-runtime v0.10.0, 문진 스키마 survey-schema-v1.2.0(SlotDef 칸 규격). 시험 값도 맞췄다.
- E2E 문항지(`test/fixtures/question-form-v2.txt`)의 Q8_1 일수 칸에 칸 규격 줄(`자료형: integer`, `값 단위: day/week`, `최소: 0`, `최대: 7`)을 넣었다. question-authoring 2f7d2b7의 작성 양식이 읽는 줄이다.
- 새 단계 `5o`(`--only 1,2,3,4,5o`): 추론 서버에 ExtractRequest{input, flow, fields}로 직접 '8일'을 보내면 REASK/OUT_OF_RANGE(같은 문항, 저장 안 하는 UNCLEAR), 7일·0일은 NEXT(경계 포함). 서비스 경유는 가짜 A가 값을 내는 발화로 Q8_1까지 24턴 진행한 뒤 '8일이요' -> 턴 action REASK, 8 저장 없음 -> '3일이요' -> 3 저장. 모방(mimic) 백엔드가 아니라 E2E의 fake 백엔드(흐름 파일의 integer 칸이 발화의 첫 숫자를 값으로 낸다)로 범위 밖 값을 만든다. 구현만 했고 이 단계는 아직 돌리지 않았다.

## build-images: 영역 내부 버전 파일을 읽지 않는다 (ADR 0041)
- model-runtime 라벨은 `DEPLOY_MR_TAG`에서 만들고 빌드한 이미지의 `model_runtime.RUNTIME_VERSION`과 대조한다(어긋나면 빌드 중단). kiosk-frontend `app-version`은 deploy가 넘기지 않는다(영역 Dockerfile 기본값, CR-D29). `pyproject.toml`·`package.json`·`mr_version` 제거.
- `test-build-images-static.sh`에 영역 내부 버전 파일 사용 금지 검사를 더했다(수정 전 5건 실패, 수정 뒤 통과).

## 복구 뒤 비root 서비스가 unhealthy 이던 것: 볼륨 루트의 소유자·모드 복원
- 원인(재현으로 확정): `restic restore <스냅샷>:/data --target /dst` 는 /data 아래 항목의 소유자·모드는 되살리지만 볼륨 루트(/dst) 자체는 건드리지 않는다. 지웠다 새로 만든 볼륨의 루트는 root:root 755 라 uid 10001 서비스(model-registry, dataset-store)가 쓰지 못한다. 재현: 루트 10001:10001 750 인 볼륨을 백업 -> 볼륨 삭제 -> restore.sh -> 루트 0:0 755 (파일은 10001 그대로).
- 고침: `restore.sh` 가 스냅샷에 기록된 /data 노드(`restic ls --json`)의 uid·gid·mode 를 읽어 볼륨 루트에 적용한다(못 읽으면 실패). `test-backup.sh` 에 루트 속성 단언을 더했다.

## E2E 백업 저장소(compose.backup-target.yaml) 500 수정
- 원인(rest-server 로그로 확인): 새 이름 있는 볼륨은 root 소유인데 rest-server 가 비root(65534)로 돌아 `mkdir /data/openit: permission denied` -> restic init/backup 이 HTTP 500. `test-backup.sh` 의 rest 시험은 컨테이너를 기본 사용자(root)로 띄워 이 차이를 못 잡았다.
- 고침: 일회용 `backup-target-perms`(root, CHOWN·DAC_OVERRIDE 만, 네트워크 없음)가 볼륨 소유자를 65534 로 바꾸고 `backup-target` 이 `service_completed_successfully` 뒤에 뜬다(레지스트리 perms 서비스와 같은 방식). 같은 구성을 compose 로 띄워 `up --wait` -> restic init/backup 성공, 서버 자격 forget 403 을 확인했다.

## 4b 후속: 게이트웨이를 띄우는 자체 시험이 device-tls 조각을 마운트하지 않아 실패하던 것
- 원인: `config/Caddyfile`이 `/etc/caddy/device-tls.caddy`를 import하는데 `test-gateway-auth.sh`(4곳), `test-secret-fixtures.sh`, `test-demo-kiosk.sh`가 Caddy를 직접 띄우거나 검증하면서 그 파일과 `device-ca.pem`을 마운트하지 않았다("File to import not found"). compose(운영·데모 겹침)는 기본 compose의 `gateway-device-tls`·`gateway-device-ca` 설정으로 이미 마운트한다.
- 고침: 세 스크립트의 Caddy 실행에 두 마운트를 더했다. `e2e.sh`가 앞단에서 부르는 자체 점검 전부를 이 PC에서 돌려 통과를 확인했다.

## 4b 게이트웨이: 키오스크 기기 인증서 검증, 계약 v2.3.0 (D113, ADR 0040)
- `config/Caddyfile`: 사이트 `tls { issuer internal; import device_client_auth }`, 주체를 `X-Openit-Dn`으로 받아 `header_regexp`로 CN을 꺼내 키오스크 경로에서 `X-Openit-Device`로 넘긴다. survey로 가는 모든 프록시에서 클라이언트의 `X-Openit-Device`·`X-Openit-Dn`을 지운다. 인증서 없음은 기존대로 401 + Bearer, 2.x 기기 토큰 경로는 호환으로 남는다.
- `config/device-tls.caddy`(기본: 검증 꺼짐), `config/device-tls.mtls.caddy.example`, `config/device-ca.pem`(자리), compose `gateway-device-tls`·`gateway-device-ca`. survey의 기기 토큰 표는 2.x 호환 선택으로 표시했다.
- `scripts/device-pki.sh`(시험·데모용 일회용 CA, 운영 금지), `scripts/test-device-mtls.sh`(18건 통과; 시험은 호스트 이름으로 접속: Caddy는 클라이언트 인증 사이트에서 Host=SNI를 요구해 IP 접속은 421), `lib.sh` DEPLOY_BC_TAG v2.3.0.

## 백업 저장소를 서버 밖 append-only(restic rest-server)로 (D112, ADR 0038 갱신)
- `BACKUP_REPOSITORY=rest:http(s)://…`(운영) + `BACKUP_REST_CREDENTIAL_FILE`(서버 자격, 값은 env 파일로만 전달) 모드 추가. 서버는 쓰기·읽기만 되고 스냅샷·데이터 삭제와 덮어쓰기는 403. 로컬 `BACKUP_DIR`는 개발·시험 전용(경고).
- 보관 정리는 저장소 쪽 `scripts/backup-prune.sh`(저장소 파일 접근 + 암호). 서버의 `backup_forget`은 append-only 모드에서 하지 않는다.
- `pg-backup.sh`: 실패한 덤프는 EOF 전에 restic 컨테이너를 죽여 스냅샷을 만들지 않는다(지울 수 없어서). 일부 성공한 실행은 성공한 것의 스냅샷이 남는다(옛: 모두 버림).
- `compose.backup-target.yaml`(시험·데모용 rest-server, 이미지 digest 고정 `REST_SERVER_IMAGE`). E2E 단계 9 백업과 5b가 이 저장소를 쓴다.

## 기준 표 boundary-contracts v2.2.2, 정적 화면 이미지(Caddy)에 맞춘 compose
- `scripts/lib.sh`: `DEPLOY_BC_TAG` v2.2.2(waitress가 앱 앞에서 내는 413/414/431을 계약 클라이언트가 INVALID_RECORD로 읽는다). 시험 값(v2.2.0 예시, mr=v0.8.1)도 현재 표로 올렸다.
- `compose.yaml`: kiosk-frontend·admin-console에 `cap_add: NET_BIND_SERVICE`(공식 caddy 바이너리의 파일 권한 때문에 `cap_drop ALL` + no-new-privileges에서 exec가 거부됨, 측정함. gateway와 같은 처리)와 `/healthz` healthcheck(kiosk에는 없었다)를 더했다.

## 단위 4a-4: 직원 계정 발급·회전 스크립트 -> 조직이 주는 bcrypt 계정 파일 (D111, ADR 0039)
- 운영 직원 계정의 원본은 조직이 주는 `secrets/staff-accounts.conf`(`<계정> <역할> <bcrypt 해시>`, 형식 `config/staff-accounts.conf.example`). 새 `scripts/apply-accounts.sh [--apply]`가 형식·역할·bcrypt를 검사하고 게이트웨이 계정 조각을 다시 쓴다(검사 실패면 기존 조각 유지, 해시는 출력하지 않음).
- 삭제: `scripts/rotate-account.sh`, `config/gateway-accounts.conf`, 운영 계정의 무작위 암호·해시 생성. 시험 계정(`*-e2e`)은 `--test-fixtures`에서만 기존대로 만든다.
- 시험: `test-staff-accounts.sh` 17건(Docker 불필요), `test-gateway-auth.sh`에 조직이 준 해시로 실제 로그인(통과/틀린 암호 401/역할 밖 403) 추가.

## 단위 4a-3: backup_tool.py + age/gpg -> restic (D111, ADR 0038)
- 백업은 restic 저장소 하나(`$BACKUP_DIR/restic`, 이미지 `RESTIC_IMAGE` digest 고정, 암호는 `BACKUP_PASSWORD_FILE`). `backup.sh`(볼륨), `pg-backup.sh`(`pg_dump -Fc | restic backup --stdin`, 평문 파일 없음, 중도 실패 시 스냅샷 삭제), `backup-secrets.sh`, 복구 `restore.sh`/`pg-restore.sh`/`restore-secrets.sh <latest|ID>`, 정기 복원 시험은 임시 저장소 왕복 + 실제 저장소 `restic check`.
- 삭제: `backup_tool.py`, age/gpg 암호화, MANIFEST 해시, tar 묶기, `BACKUP_ENCRYPT_*`·`BACKUP_ALLOW_PLAINTEXT`·`BACKUP_SECRETS_*` 키(남아 있으면 CRIT). **보증이 약해진 점**: 서버에 저장소 암호가 있어야 한다(옛 공개키 방식은 서버에 복호 키가 없었다). ADR 0038 '감수하는 것'.
- 시험: `test-backup.sh` 38건, `test-backup-secrets.sh` 15건, `test-postgres.sh` 66건이 restic 경로로 통과. E2E 단계 9 백업 구간과 5b를 restic 경로로 바꿨다(이 환경에서는 Docker 네트워크 부족으로 E2E를 돌리지 못했다).

## 단위 4a-2: check_health -> Prometheus + blackbox/json/node exporter + Alertmanager (D111, ADR 0037)
- 추가: `compose.monitoring.yaml`(이미지 5개 digest 고정, `lock-third-party.sh`), `config/prometheus/`(prometheus, 경보 규칙과 `promtool test rules`, blackbox, json_exporter, alertmanager), `scripts/job-metrics.sh`(systemd `ExecStopPost`가 주기 잡 결과를 textfile 지표로), `scripts/test-monitoring.sh`(정적 + 가짜 서비스 실패 주입), `scripts/check-monitoring-live.sh`, 각 `.service`에 `ExecStopPost`.
- 삭제: `check_health.py`, `check-health.sh`, `test-check-health.sh`, `external-monitor.example.yaml`, check-health 유닛.
- E2E: 단계 5m은 model-serving `/readyz`와 판정 루프를 직접 읽는다. 단계 9 구간은 감시 스택을 같은 프로젝트에 올려 탐침·지표를 확인한다(전체 모드에서만).

## 단위 4a-1: scheduler.py -> systemd timer (D111, ADR 0036)
- 잡마다 `config/systemd/openit-<잡>.service|timer` 7쌍을 추가했다. `scripts/scheduler.py`, `config/jobs.yaml`, `schemas/jobs.schema.json`, 스케줄러 유닛, 스케줄러 상태 파일과 그 시험을 지웠다. `check_health.py`는 스케줄러 상태를 읽지 않는다(잡 신선도 점검은 4a-2에서 Prometheus가 이어받는다).
- 새 시험 `scripts/test-systemd-units.sh`(주기 표, oneshot, 스크립트 존재, `systemd-analyze verify`, 망가진 유닛 거부). E2E 단계 9의 스케줄러 구간은 이 시험 + `run-job.sh` 실행으로 바뀌었다.

## 기준 표 갱신과 turn-engine 코드 의존 제거 반영 (wo-u3, D109)
- `scripts/lib.sh`: boundary-contracts v2.2.1, model-runtime v0.9.0, 문진 스키마 survey-schema-v1.1.0. `DEPLOY_TE_TAG`(v0.4.3)는 코드 의존이 아니라 계약 기록의 '규칙 세대 표지'로만 남는다. v 없는 형식 `DEPLOY_TE_VERSION`(0.4.3)을 새로 내보낸다.
- `compose.yaml`: survey-service 에 `SURVEY_TURN_ENGINE_VERSION`을 `DEPLOY_TE_VERSION`으로 넘긴다(survey 쪽 기본값에 기대지 않는다).
- `scripts/build-images.sh`: turn-engine 빌드 컨텍스트 사본과 survey-service 의 `TURN_ENGINE_TAG` 인자를 없앴다. survey-service `build_wheels.sh`가 원격 대신 로컬 태그를 읽도록 `REPO_BASE`(사본 폴더 `build/ctx/repos`)를 준다. model-serving 이미지의 turn-engine 라벨은 영역 기본값 `n/a`를 따른다.

## 데모: 모델 서빙을 모방 백엔드로, 키오스크는 /config.json 으로 기기 설정 (작업 지시서 2, 컨테이너 검증 전)
- `scripts/demo.sh up`: model-serving 을 `MODEL_RUNTIME_BACKEND=mimic`(+`MODEL_RUNTIME_ALLOW_FAKE=1`, `MODEL_RUNTIME_FAKE_FLOW_FILE`)으로 띄운다(`test/compose.demo-mimic.yaml`). 흐름 파일은 `--mimic-flow-file <파일>`로 받고 기본은 `test/fake-model/question_flow.json`이다. 모방기의 동작과 파일 내용은 model-runtime 이 정한다(이 영역은 경로만 넘긴다). E2E 는 계속 fake 다. 모방 이미지는 아직 만들어지지 않았다면 up 은 model-serving 이 시작을 거부해 실패한다(확인 못 함).
- 키오스크 `/config.json`: `test/compose.demo-kiosk.yaml`(데모 전용)이 `scripts/kiosk-add-device.sh add e2e` 가 만든 기기 산출물을 kiosk-frontend 의 `CONFIG_FILE`로 마운트하고, `scripts/demo_caddyfile.py`가 만든 gateway 설정 사본(운영 Caddyfile 의 `/config.json` 404 블록 하나만 kiosk-frontend 로 넘김)을 쓴다. 운영 구성(compose.yaml, config/Caddyfile)은 그대로다. 안내 출력에 토큰 값은 없다.
- `scripts/test-demo-kiosk.sh`: 병합된 compose 설정과 Caddyfile 사본으로 위 배선과 운영 불변을 확인한다(컨테이너를 띄우지 않는다).

## 전체 E2E(00aa6de) 실패 둘 수정: db 네트워크 분리, 개입 단언
- 차단 단언 `survey-service -> question-authoring` 실패 원인: 서비스 넷이 하나의 `db` 네트워크를 같이 써서 postgres 클라이언트끼리 닿았다(구성 결함). `db-survey`, `db-qa`, `db-ops`, `db-gate`로 나눴다(각 internal, postgres만 넷에 모두 가입). 이유: 데이터베이스 길이 서비스 사이의 새 길이 되면 영역 격리가 무너진다. 단언을 넓혔다: `question-authoring -> survey-service`, `model-registry -> model-serving`, `question-authoring -> model-serving` 차단, db 네트워크마다 구성원이 postgres와 자기 서비스뿐임.
- 단계 5 `개입이 409가 아님` 원인: 단언이 `X-Openit-User` 없이 서비스에 직접 호출해 401을 받았다(낡은 단언). 헤더 없음은 401, 헤더 있으면 409로 나눠 응답 코드·본문을 메시지에 찍는다.

## PostgreSQL 구성을 컨테이너에서 처음 확인 (네 영역 최신 main으로 빌드)
- 확인: 스택 10개 컨테이너 healthy. `/readyz`: survey-service `database.kind=postgresql`, release-gate `database=postgresql`, question-authoring `db=postgres`, ops-feedback `log_store`·`failure_store`=postgresql. ops-feedback I7 읽기 면은 `OPS_FAILURE_DB` 없이 DB URL만으로 켜진다(`GET /v1/cases` 200). `/data`(tmpfs)에 쓰기 흔적과 오류 로그 없음(qa, ops 비어 있음). 잡은 `storage` 항목이 필수(없으면 시작 거부)이고 DB URL이 있으면 PostgreSQL을 쓴다 -> 설정 파일에 주석만 보강.
- 5r 수정: 개입 본문에 `staff_id`를 싣지 않는다(InterventionDecision은 additionalProperties false). 위조 `X-Openit-User`가 무시되는지로 확인. 목록 알림의 kind는 `RISK_STOP`, 세션 조회 알림의 kind는 `RISK`, rule_id는 세션 조회에서 본다. 단독 실행 시 활성 릴리스 적재를 기다린다.
- `pg-fingerprint.sh`: 비어 있는 데이터베이스(INSERT 없음)에서 실패하던 것을 고침. `10-roles.sh`: 최초 초기화의 임시 서버에서 불필요한 reload 경고를 없앰.

## 운영·E2E 구성을 PostgreSQL로, 위험 신호·결과 조회 E2E 단계, 백업 잡에 pg_dump (코드·구성만, 컨테이너 검증 전)
- 결정(사용자 지시, 표준): 운영 구성은 PostgreSQL, SQLite는 각 영역의 개발·시험 기본으로만 남긴다. 이유: 권한·백업·보존을 DB 한 곳에서 걸고 서버가 나뉘어도 같은 방식으로 동작한다.
- `compose.yaml`: survey-service(`SURVEY_DATABASE_URL_FILE`), question-authoring(`QA_DATABASE_URL_FILE`), ops-feedback 서버·잡(`OPS_LOG_/OPS_FAILURE_DATABASE_URL_FILE`), release-gate 서버·수집 잡(`GATE_DATABASE_URL_FILE`)을 `db` 네트워크에 붙이고 `db-*-dsn` 비밀을 마운트, 서버 서비스는 postgres healthy에 의존. `qa-data`, `ops-data` 볼륨과 `OPS_FAILURE_DB` 설정을 정리(`gate-data/releases`, `survey-data` 릴리스 작업 폴더는 유지). survey-service에 `SURVEY_RESULT_READER_TOKEN_FILE`, `SURVEY_RISK_SOURCE_TOKEN_FILE`. `gen-secrets.sh`가 `survey-result-reader`, `survey-risk-source`를 만든다. `compose.test.yaml`에도 `db` 네트워크.
- 게이트웨이: `/v1/sessions/*/risk-signals`, `/v1/results*`를 404로 먼저 닫는다(내부 면, 이유는 docs/RUN.md 4-1-1).
- E2E 새 단계 5r(REAL, 가짜 모델): 세션 시작(기기 토큰, subject_ref) -> 발화 -> 위험 신호(risk-source) -> 알림 목록 -> 직원 세션 조회 -> 개입 RESUME(resolved_by=staff-e2e) -> 결과 조회(result-reader, 발화 없음). 네트워크 단언: 서비스 4개는 postgres:5432에 닿고 model-registry는 못 닿으며 호스트에 게시 없음.
- 백업: `backup-all.sh`(파일 저장소 + `pg-backup.sh`)를 backup 잡으로, `pg-fingerprint.sh` 추가. E2E 백업·복구 단계가 gate-data/models-data와 PostgreSQL 5개 데이터베이스(`pg-data` 볼륨 삭제 후 `pg-restore.sh`)의 왕복을 본다. `backup.sh` 기본 저장소는 `gate-data`.
- 실행해 본 것: compose 해석(서비스별 네트워크·환경 변수·의존), Caddyfile `caddy validate`, 스크립트 구문, check-all. 실행하지 않은 것: 새 E2E 단계와 백업 단계 전체, PostgreSQL 지원 이미지.

## E2E·데모의 activate를 헤더 있는 HTTP 호출로 (release-gate D85 행위자 식별 반영)
- release-gate가 activate·rollback에서 본문의 `requested_by_role`을 버리고 역할은 쓰기 토큰, 행위자는 `X-Openit-User`로 정한다(사람 역할 토큰에 헤더가 없으면 401). `GATE_SERVICE_ROLES`에 operator를 넣는 우회는 하지 않았다(더 엄격한 쪽). 이유: 감사 기록의 행위자는 서버가 정하고, 시험도 운영과 같은 경로를 탄다.
- `e2e_steps.py`: `gate_ops`/`gate_activate`(urllib, 이웃 코드 import 없음)로 activate를 부른다. 새 단언: 헤더 없이 operator 토큰으로 activate하면 401이고 포인터가 안 바뀐다, 헤더가 있으면 통과하고 `GET /v1/active-pointer`의 `ext["release-gate"].requested_by`가 그 ID. `demo_up`·`demo_activate`·단계 4b·단계 8도 같은 호출. ops-feedback 자동 롤백은 서비스 역할이라 그대로.
- 새 release-gate 이미지로는 아직 돌려 보지 못했다(이 변경은 그쪽 push 전이고 E2E는 이전 이미지로 한 번만 돌렸다). 이전 이미지에서는 이 단언(401)이 실패한다.

## 게이트웨이 개별 계정·키오스크 기기 인증, 스케줄러 주기, 잡 설정 파일 (D85)
- 결정(사용자 지시 D85, 표준): 직원·운영자는 개별 계정으로 인증하고 `X-Openit-User`로 행위자를 전한다. 이유: 감사 기록에 누가 했는지가 남고, OIDC로 바꿔도 같은 헤더 규칙을 쓴다. 키오스크는 기기 토큰으로 인증한다. 이유: 게이트웨이에 닿는 누구나 키오스크 API를 부르는 상태를 없애고 기기별로 폐기할 수 있다.
- `config/Caddyfile`: 인증 블록 `(authenticate)`와 `(role_matchers)`를 생성 파일로 분리(OIDC 교체 지점). staff/operator/release-approver/reviewer 역할 검사(403), 직원 개입 경로 포함. operator 계정만 여는 경로 넷(admin-console CR-004): `GET /v1/active-pointer`, `GET /v1/releases`(읽기 토큰 `gate-read-operator`)와 `POST /v1/activate`, `/v1/rollback`(쓰기 토큰 `gate-write-operator`), no-store. `gen-secrets.sh`가 release-gate 읽기 목록에 역할 operator를 더함. 키오스크 경로는 `@device_ok` 기기 토큰 대조 후 서비스 토큰으로 바꿔 붙이고 아니면 401, 클라이언트의 `X-Openit-User` 제거.
- `config/gateway-accounts.conf`(계정↔역할), `scripts/gateway-lib.sh`, `gen-secrets.sh`(계정 암호·해시 파일, 시험 기기 `e2e`), `scripts/kiosk-add-device.sh add|remove|list|sync [--apply]`, 자체 시험 `scripts/test-gateway-auth.sh`(e2e.sh가 실행). 예전 `staff-console-password` 등 공용 암호 파일과 `gateway-staff-auth/human-auth.caddy`는 쓰지 않는다(남아 있어도 된다).
- E2E(`e2e_steps.py`, `e2e.sh`)와 `demo.sh`: 키오스크 호출에 기기 토큰, 계정 이름 `staff-e2e`/`operator-e2e`/`trainer-e2e`/`reviewer-e2e`. 새 단언: 기기 토큰 없음·틀림·서비스 토큰은 401, 역할 밖 계정 403, 운영자 경로 인증 없이 401.
- `config/jobs.yaml`: release-gate-collector 600초, ops-feedback-job 3600초, backup 86400초(표준 주기). 이유: 새 조합은 10분 안에 후보가 되고, Trace 비식별은 시간 단위, 백업은 하루 단위가 표준이다.
- `config/ops-feedback-job.yaml`: root 소유 빈 디렉터리(Docker가 파일이 없을 때 만든 것)를 지우고 실제 파일로 둠. `rollback`, `retention.raw_days`는 사용자 결정 전이라 `null`.
- check-all 규칙 11: compose 바인드 마운트 원본(확장자 있는 파일)이 실제 파일이 아니면 FAIL(재발 방지). 자체 시험 포함.


## PostgreSQL 기반: 서버 하나, 서비스마다 데이터베이스·최소 권한 계정 (서비스 설정은 아직 그대로)
- 결정(사용자 지시: 빈 곳은 표준적인 방법): 영역별 SQLite 파일 대신 공식 `postgres:16` 서버 하나. 서비스마다 데이터베이스와 계정을 나눈다. 소유 서비스만 쓰고 이웃은 HTTP로만 읽는 규칙(D49·D50)은 그대로다.
  - 이유 1: 권한·암호화·백업·보존을 DB 계층 한 곳에서 걸 수 있다.
  - 이유 2: 서버가 여러 대로 나뉘어도 같은 방식으로 동작한다(접속 문자열만 바뀐다).
- `compose.yaml` `postgres`: 볼륨 `pg-data`, 호스트 포트 없음(internal 네트워크 `db`), 비루트(999), 읽기 전용 루트, `pg_isready` healthcheck, `POSTGRES_PASSWORD_FILE`(D84, 평문 환경 변수 없음), `--data-checksums`. 이미지는 `locks/images.lock`의 `POSTGRES_IMAGE`(digest 고정, `lock-third-party.sh`가 기록).
- `config/postgres/initdb/10-roles.sh`: 공식 `/docker-entrypoint-initdb.d`. 멱등. 계정 `survey qa ops_log ops_failure gate`, 각 계정은 자기 데이터베이스만 접속, 슈퍼유저 권한 없음, 루프백 TCP의 trust 제거.
- `gen-secrets.sh`: 계정 암호 파일(`db-<이름>-password`)과 DSN 파일(`db-<이름>-dsn`), `postgres-password`. `--db-only` 옵션. 이름 규칙 표는 `docs/RUN.md` 4-1-1.
- `pg-backup.sh`, `pg-restore.sh`, `pg-roles.sh sync`, `dev-postgres.sh up|down`(영역 개발용, 포트는 Docker가 배정, 암호는 일회용), 자체 시험 `test-postgres.sh`.
- `record-e2e.sh`: 환경 칸이 gpu-dev도 '이 PC (WSL2)'로 적던 버그를 고쳤다. `DEPLOY_ENV_NAME`이 있으면 그것, 없으면 hostname으로 식별(`gpu-dev*`만 gpu-dev, 원문 hostname은 기록하지 않음). 자체 시험은 `test-check-all.sh`.
- 이 단계에서 하지 않은 것: 서비스 컨테이너 설정 변경, `e2e.sh` 백업 단계에 Postgres 넣기, TLS, 디스크 암호화·WAL 보관 정책.

## demo.sh swap-adapters, 추론 서버 측정 도구 probe-serving.py (OPEN_GAPS U08)
- `demo.sh swap-adapters [--adapter-a/-b DIR --prompt-a/-b FILE]`: 떠 있는 데모에서 새 모델 패키지를 게시, 자동 검사, 시험용 승인자(스크립트) 승인, 활성화해 model-serving만 새 번들을 적재시킨다. 어댑터 인자는 `up --llm`과 같은 사전 검사를 거치고 거부되면 아무것도 게시하지 않는다. 전후 컨테이너 StartedAt(Env는 읽지 않음)과 새 release_id의 LOADED를 출력한다. 이전에는 `reset`(데모 전체 재생성)뿐이었다.
- `scripts/e2e_steps.py`: 단계 3의 게시·재확인을 `publish_packages()`로 뽑아 단계 3과 새 단계 `demo_swap`이 같이 쓴다(`demo_active`는 활성 포인터 읽기). 두 단계는 demo 전용이라 E2E 기본 실행에 들어가지 않는다. 단계 3의 동작은 같고, 어댑터 열기 위치만 패키지 ID가 들어간 폴더로 바뀌었다.
- `scripts/probe-serving.py`(+ 자체 시험 `scripts/test_probe_serving.py`): model-serving extract에 입력 묶음을 보내 성공/OUTPUT_INVALID 건수, 위반 키워드별 빈도, 첫 호출 대 이후 중앙값 지연, X-Openit-Outcome 분포를 표로 낸다. 토큰은 파일에서 읽고 출력하지 않는다.
- 문서: `docs/RUN.md` 7-2-3, `docs/GPU_HOLE.md` H2(교체)·H4(측정)가 두 도구를 쓰도록 바꿨다.
- 확인하지 못한 것: `--llm`(vLLM) 데모에서의 교체, 실제 모델의 OUTPUT_INVALID 분포. 전체 E2E는 돌리지 않았다.

## E2E가 값 추출 경로를 지나가게 함 (model-runtime v0.7.1 가짜 A, OPEN_GAPS U16)
- `test/fake-model/question_flow.json`을 객체 형식(`order`, `slots`, `skips`)으로 확장: 순서·건너뛰기 7규칙은 survey-service `schema/data/question_flow.json`, 칸 키·타입은 같은 스키마의 키 이름과 boundary-contracts `V2_DRAFT.md`의 값 형태에서 가져왔다(Q1.D*/Q2.D*/Q4~Q6/Q7 bool, Q8_1/Q9_1/Q10 `days` 정수. 문자열 칸 문항은 칸 정의 없음).
- E2E 단계 5g: 가짜 A 직접 호출 6건(값·타입·건너뛰기), 서비스 경유 값 있는 3턴(실패 신호 없음, 추론 실패·형식 위반 증가 0, Trace 전송). 단계 5s: 포인터 1->2 전후 survey-service·release-gate·model-registry·ops-feedback-ingest·question-authoring·gateway의 컨테이너 ID·StartedAt 불변, model-serving 새 릴리스 LOADED.
- 단언은 `scripts/e2e_asserts.py`, 자체 시험 `scripts/test_e2e_asserts.py`(틀린 값이면 실패함을 확인, e2e.sh가 실행).
- 한계: 저장된 값을 돌려주는 공개 읽기 경로가 없어 저장 값 자체는 단언하지 않는다. 가짜 A는 CORRECT를 내지 않아 정정은 시험하지 않는다.

## GPU 구멍 준비: 진짜 어댑터 얹기, 데모 비밀 점검, 위치 독립 시험 수정
- `docs/GPU_HOLE.md`: GPU 서버가 열릴 때 따라 할 순서(H1~H4, 명령·합격 기준·진단·OPEN_GAPS에 적을 항목).
- `demo.sh up --llm --adapter-a/-b DIR --prompt-a/-b FILE`: `make-llm-package.sh`가 `llm_attach_package.py`로 진짜 어댑터 패키지를 만든다. 기반 모델 불일치·순위 초과·파일 누락은 이미지 빌드 전에 거부(`--check-only`). `demo.sh config --llm`도 같은 검사.
- 비밀 점검: `check-secrets-hidden.sh`가 인자 없이 부르면 데모(`state/demo`)도 점검하고 `--secrets-dir`를 받는다. `demo.sh check-secrets` 추가, `demo.sh up` 끝에서 자동 실행(실패하면 종료 코드 비0).
- `test-inference-location.sh`: 별도 추론 서버에 시험용 fake 문항 순서 파일(`test/compose.fake-model.yaml`)을 붙였다(없어서 단계 5가 VALIDATE에서 실패했다).

## 비밀 파일화(D84)와 태그 정렬: boundary-contracts v2.0.2, turn-engine v0.4.0, model-runtime v0.7.0
- 태그 표(`lib.sh`)와 E2E·문서 표기를 새 태그로 맞췄다.
- 비밀: compose의 `env_file`로 토큰을 넣던 것을 없애고 최상위 `secrets:`(`secrets/tokens/<이름>`)를 `/run/secrets`에 마운트, 서비스는 `NAME_FILE` 경로만 받는다. `gen-secrets.sh`는 목록 값도 파일로 만든다(`secrets/<서비스>.env` 제거). 게이트웨이는 Caddy `{file./run/secrets/…}`. 외부 추론 서버의 토큰 파일과 `compose.inference.yaml`도 같은 방식(`INFERENCE_TOKENS_FILE`, `INFERENCE_RELEASE_TOKEN_FILE`).
- 새 점검: `scripts/check-secrets-hidden.sh`(E2E 단계), `scripts/check-versions.sh` + `scripts/test-check-versions.sh`(E2E 단계).

## model-runtime v0.6.2 채택 (브랜치 follow-mr-0.6.2)
- 기준 태그: model-runtime v0.6.2(`lib.sh`의 `DEPLOY_MR_TAG`; 이미지 라벨 기대값도 이 값).
- 우회 제거(CR-D22 v2 1·4항 해소): `test/fake-model/fake_server.py`(FakeBackend 응답 바꿔치기)와 `scripts/apply_system_prompts.py`를 지웠다. fake 모델은 표준 서버 + `MODEL_RUNTIME_BACKEND=fake` + `MODEL_RUNTIME_FAKE_FLOW_FILE=test/fake-model/question_flow.json`(survey-service `question_flow` 순서 사본, 31개). 중립 패키지는 `make_neutral_package.py --system-prompt-a/-b`.

## 2026-10-27 계약 2.0.0 구조로 이전 (브랜치 migrate-contracts-2.0.0)

- 기준 태그: boundary-contracts v2.0.0, model-runtime v0.6.1(prompt-4), turn-engine v0.3.0(`lib.sh`, `DEPLOY_TE_TAG`는 환경 변수로 내보내 E2E 매니페스트 lineage와 게이트 기준을 맞춘다). 이미지는 이웃 리포의 현재 main에서 빌드(방식 그대로).
- E2E v2 흐름: PUT 적재 -> extract(JSON) -> respond(text), 서버 직접 호출 검사(헤더·스키마·400·404·시스템 프롬프트 해시), 모델 패키지에 시스템 프롬프트(`ModelPackageManifest.system_prompt`), v2 문항 양식(ID 31개), v2 TurnTrace·FailureCase(LORA_A). 직원 알림은 입력원이 없음을 확인하고 알림 화면 시험은 건너뜀. fake 모델은 시험용 진입점(CR-D22; 0.6.2 채택으로 삭제됨).
- 실제 LLM 데모: `make-llm-package.sh`가 Qwen3-1.7B(`config.json` 고정 리비전 + sha256)와 데모 시스템 프롬프트(`test/llm-demo`)로 중립 패키지를 만든다. 서버 미검증.
- 지움: `test/compose.llm-demo.yaml`, `MODEL_RUNTIME_FAKE_RISK_PHRASE`(계약 2.0.0에서 없어짐).

## 2026-10-15 여섯째 구간

- model-runtime v0.5.1: init 제거, 기대값 기반 serving_config, 위험 정지 -> 직원 개입 E2E, CR-D18.

## 2026-10-15 다섯째 구간

- model-serving(추론 서버) 추가, survey가 I9로 호출, E2E 5단계가 추론 서버를 거침(중단·복구 포함), model-runtime v0.5.0·LangGraph survey 이미지, CR-D17.

## 2026-10-15 넷째 구간

- 사람 승인 출고(D53)·공개 API(D55)·계약 v1.3.1 반영, 시험용 정책·실행기 삭제, 게이트웨이가 `/v1/sessions` 전달, 승인자·키오스크·직원 토큰 추가, CR-D16.

## 2026-10-15 셋째 구간

- 검토 HTTP 면·개선 신호·게이트 운영 모드 거부·정책 스키마 검증을 E2E에 반영, 잠금 갱신, CR-D15.

## 2026-10-15 둘째 구간: 영역 사이 HTTP 연결(D49~D51)

- 서비스 5개(model-registry 추가), 모든 영역 사이 호출을 HTTP로 연결, 역할별 토큰(`gen-secrets.sh` 개편), 수집기 run-once 잡.
- E2E를 실제 서비스로 재작성(1~8단계), 시험용 정책·실행기·잡 설정 분리, 복구 검증을 HTTP로.
- 문서 갱신, 변경 요청 CR-D10..D14. 이미지 빌드(`build-images.sh`)가 model-lab 사본과 survey-service clone을 다룬다.

## 2026-10-15 첫 구성

- Compose(`compose.yaml`): gateway(Caddy)와 네 서비스. 이미지는 digest로만 참조, 네트워크 edge/serving/authoring/release/logs, 저장소별 볼륨, 읽기 전용 루트, cap_drop ALL, 비root.
- digest 잠금(`locks/images.lock`, `locks/history/`), `build-images.sh`(git archive 사본에서 빌드), `publish-images.sh`, `rollback.sh`, 로컬 레지스트리(`compose.registry.yaml`).
- 비밀 값: `scripts/gen-secrets.sh` -> `secrets/`(gitignore), `.env.example`.
- 백업·복구(`backup.sh`, `restore.sh`, `backup_tool.py`): 설정이 없으면 거부(O16 미정).
- 주기 잡 스케줄러(`scheduler.py`, `config/jobs.yaml`): 주기는 설정으로만, GPU 잡은 서버 밖.
- `scripts/e2e.sh`: 합격 시나리오 실행. 시험 대역은 `compose.test.yaml`, `test/fixtures/`로 분리.
- 문서: design, boundary, runbook, 변경 요청 CR-D01..D08.
