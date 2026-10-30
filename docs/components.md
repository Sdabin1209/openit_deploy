# deploy 컴포넌트 분해 (D117, ADR 0045)

위에서부터 나눈 결과다. 입력은 이 영역이 **브리프**(`docs/brief.md`)와 **계약**(boundary-contracts v3.1.1, 통신은 link v0.1.0)에서 받는 일이고, 기존 코드는 정의의 근거가 아니라 빠진 업무 규칙·거부 조건을 찾는 대조 자료로만 썼다(확인한 것: 스크립트의 거부 지점을 훑어 스키마와 컴포넌트로 옮겼다. 셸 스크립트 안의 검사는 훑지 못했다: `schemas/README.md` 스키마 밖 조건).

## 1. 업무 단계와 컴포넌트가 되는 것

브리프의 일: 단일 서버에서 Compose 로 시스템을 합치고, 이미지 digest 로 코드 축을 되돌리고, 백업·복구하고, 잡을 돌리고, 외부 감시를 건다. 이 일의 **대부분은 셸과 Compose 설정**이다(docker 호출, 파일 배치, 서비스 기동). 판단이 있는 일만 컴포넌트가 된다.

| 업무 단계 | 하는 곳 | 컴포넌트인가 |
| --- | --- | --- |
| 이미지 빌드·게시·digest 잠금·롤백·기동 | `scripts/*.sh`, `compose*.yaml` | 아니다(운영 절차, ADR 0045 "셸은 컴포넌트가 아니다") |
| 이미지 라벨이 계약을 따르는지(게시 전 관문) | `image_label_check` | 예 |
| 게이트웨이 노출이 라벨 선언과 같은지 | `exposure_check` | 예 |
| 비밀 이름이 compose 와 영역 코드에서 맞는지 | `secret_name_check` | 예 |
| 영역을 가로지르는 정적 일관성 | `consistency_check` | 예 |
| deploy 내부 파일 형식(images.env, images.lock, verify-areas) | `internal_file_check` | 예 |
| 백업 보관 기간 대 데이터 보존 기간 | `retention_check` | 예 |
| 영역 환경 보고(setup-env) 기록·판정 | `setup_env_record`, `setup_env_status` | 예 |
| 영역 목록 읽기 | `area_list` | 예 |
| 바뀐 영역의 확인 범위 계획 | `verify_plan` | 예 |
| 영역이 선언한 잡의 명령 조립·실패 설명 | `job_select`, `job_command`, `job_failure_text` | 예 |
| 추론 서버 측정(호출·집계) | `link_serving_probe`, `link_serving_info`, `serving_probe` | 예 |
| 복구 검증(이웃 HTTP 로 다시 읽기) | `link_restore_verify` | 예 |
| 데모 게이트웨이 설정 사본 | `caddyfile_demo` | 예 |
| 진짜 LoRA 어댑터 부착 판정 | `adapter_check` | 예 |
| E2E 시나리오(`scripts/e2e_steps.py` 등) | 수용 시험 | 아니다(시험, ADR 0045) |

## 2. 컴포넌트 표

입력·출력 타입은 `schemas/<타입>.schema.json`(예시 `schemas/examples/`)이고 코드 타입은 `openit_deploy/types/deploy_types.py`(생성)다. 통신 컴포넌트는 `link_` 로 시작하며 보내는 쪽만 있다(deploy 는 이웃이 부르는 HTTP 서버 면이 없다: 서비스는 compose 와 게이트웨이 설정이다, 받는 쪽 컴포넌트 없음).

| 컴포넌트 | 파일 | 입력 타입 | 출력 타입 | 하는 일 |
| --- | --- | --- | --- | --- |
| adapter_check | `openit_deploy/components/adapter_check.py` | AdapterCheckRequest | AdapterCheckResult | 가져온 LoRA 어댑터 한 쌍이 프로파일의 기반 모델·순위 한도에 얹을 수 있는지 판정한다 |
| area_list | `openit_deploy/components/area_list.py` | AreaListRequest | AreaListResult | 영역 목록에서 조건(kind, 버전 열차, 제외)에 맞는 영역 이름을 고른다 |
| caddyfile_demo | `openit_deploy/components/caddyfile_demo.py` | CaddyfileDemoRequest | CaddyfileDemoResult | 운영 Caddyfile 에서 /config.json 404 블록 하나만 푼 데모용 사본을 만든다 |
| consistency_check | `openit_deploy/components/consistency_check.py` | ConsistencyCheckRequest | ConsistencyCheckResult | 영역을 가로지르는 정적 일관성 규칙(버전표, 예시 키 순서, 삭제된 이름 등)을 점검한다 |
| exposure_check | `openit_deploy/components/exposure_check.py` | ExposureCheckRequest | ExposureCheckResult | Caddyfile 의 노출이 이미지 노출 선언(라벨 io.openit.exposure)과 같은지 대조한다 |
| image_label_check | `openit_deploy/components/image_label_check.py` | ImageLabelCheckRequest | ImageLabelCheckResult | 이미지 라벨이 계약 ImageLabels(와 jobs·exposure 안쪽 JSON)를 따르는지 판정한다 |
| internal_file_check | `openit_deploy/components/internal_file_check.py` | InternalFileCheckRequest | InternalFileCheckResult | images.env·images.lock·verify-areas.yaml 을 deploy 내부 스키마로 검증한다 |
| job_command | `openit_deploy/components/job_command.py` | JobCommandRequest | JobCommandResult | 선택한 잡을 docker run 명령(argv)으로 조립한다 |
| job_failure_text | `openit_deploy/components/job_failure_text.py` | JobFailureRequest | JobFailureResult | 잡 종료 코드와 stderr 마지막 줄을 한 줄 설명으로 바꾼다 |
| job_select | `openit_deploy/components/job_select.py` | JobSelectRequest | JobSelectResult | 이미지 라벨의 잡 선언(io.openit.jobs)에서 이름이 맞는 잡 하나를 고른다 |
| link_restore_verify | `openit_deploy/components/link_restore_verify.py` | RestoreVerifyRequest | RestoreVerifyResult | 복구한 저장소를 이웃 서비스의 HTTP 로 다시 읽어 검증한다 (보내는 쪽) |
| link_serving_info | `openit_deploy/components/link_serving_info.py` | ServingInfoRequest | ServingInfoResult | model-serving 의 /v1/info 로 적재된 릴리스 목록을 읽는다 (보내는 쪽) |
| link_serving_probe | `openit_deploy/components/link_serving_probe.py` | ServingCallRequest | ProbeRecord | model-serving 에 extract·respond 를 한 번 부르고 호출 기록으로 줄인다 (보내는 쪽) |
| retention_check | `openit_deploy/components/retention_check.py` | RetentionCheckRequest | RetentionCheckResult | 백업 보관 일수가 운영 데이터 보존 일수의 최솟값 이하인지 본다 |
| secret_name_check | `openit_deploy/components/secret_name_check.py` | SecretNameCheckRequest | SecretNameCheckResult | compose 가 주는 비밀 *_FILE 이름과 영역 코드가 읽는 이름을 대조한다 |
| serving_probe | `openit_deploy/components/serving_probe.py` | ServingProbeRequest | ServingProbeResult | 추론 서버 호출 기록을 집계해 지연 표와 OUTPUT_INVALID 보고서를 만든다 |
| setup_env_record | `openit_deploy/components/setup_env_record.py` | SetupEnvRecordRequest | SetupEnvRecordResult | 영역 setup-env 출력에서 보고를 골라 저장해도 되는지 판정한다 |
| setup_env_status | `openit_deploy/components/setup_env_status.py` | SetupEnvStatusRequest | SetupEnvStatusResult | 저장된 보고로 영역 환경이 준비됐는지와 환경 파이썬 위치를 판정한다 |
| verify_plan | `openit_deploy/components/verify_plan.py` | VerifyPlanRequest | VerifyPlanResult | 바뀐 영역의 시험·check-all·E2E 단계 실행 계획을 세운다 |

## 3. 컴포넌트가 아닌 것

- `openit_deploy/wiring/`: 컴포넌트를 잇고 바깥 자원(파일, 환경 변수, docker, git, setup-env 저장소)을 읽어 입력으로 바꾸고 출력을 사람이 읽는 형태·종료 코드로 바꾼다. 스키마 검증은 여기서 한다(`wiring/call.py`: 내는 쪽이 넘기기 전에 검증, 받는 컴포넌트는 다시 검증하지 않는다, R7).
- `scripts/*.py` 진입점: 인자를 wiring 에 넘기는 얇은 파일(문장 8개 이하를 구조 시험이 강제한다).
- `scripts/e2e_steps.py`, `e2e_plan.py`, `e2e_asserts.py`: 수용 시험. 이웃 호출은 `openit_link.clients` 로만 한다.
- `scripts/*.sh`, `compose*.yaml`, `config/`: 운영 절차와 설정.

## 4. 알려진 한계 (고지, 해결이 아니다)

- `consistency_check` 는 읽기 전용 워크스페이스를 입력 경로로 받아 파일·git·영역 시험 실행(규칙 8)을 한다. 순수 함수가 아니다(바깥 자원 접근을 컴포넌트 안에 둠). 근거와 되돌리는 조건은 ADR 0045.
- `secret_name_check`, `consistency_check` 외의 컴포넌트는 파일을 읽지 않는다(텍스트·문서를 입력으로 받는다).
- `wiring/cli_llm_attach_package.py` 는 매니페스트를 만들려고 `model_runtime` 을 import 한다(구조 규칙 1 위반, 기존 동작 유지). 변경 요청: `docs/change-requests/CR-U400-attach-package-model-runtime-import.md`.
