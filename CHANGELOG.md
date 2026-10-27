# 변경 이력

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
