# STATUS (2026-10-28, 계약 v2.1.0 준비)

- E2E 단계 5n 을 선언·구현했다(`scripts/e2e_steps.py`, 선언 `scripts/e2e_plan.py`): 직원 호출 재알림·실패 기록·`pause_reason=RISK`. 새 survey-service 이미지가 들어오기 전에는 실행하지 않았다(구문·자체 시험만 확인).
- `pause_reason=REASK_LIMIT` 은 E2E 로 만들 수 없다: 가짜 A(model-runtime fake)는 NEXT 만 내고 REASK 를 내는 설정이 없다. 단계 5n 이 BLOCKED 행(`5n-reask`)으로 남긴다. 풀려면 model-runtime 쪽 변경(가짜 A 가 지정 문구에 REASK)이 필요하다(미정, 변경 요청 대상).
- I2 dataset-store(synthetic-data 8514220, D100): compose.yaml·compose.test.yaml 에 서비스, 전용 internal 네트워크 `datasets`, 볼륨 `datasets-data`, 읽기/쓰기 토큰 파일(gen-secrets.sh), `lib.sh` SERVICES·`DEPLOY_BC_TAG_DS`, build-images.sh 빌드(이 PC 에서 이미지가 빌드되는 것까지 확인), backup/복구 대상, e2e.sh 도달·차단·라벨 점검, E2E 단계 7d 를 더했다. 이유: docs/adr/0032-dataset-store-boundary.md. 전체 E2E·check-containers·백업 왕복은 아직 돌리지 않았다. `locks/images.lock` 에는 레지스트리에 게시되기 전이라 DATASET_STORE_DIGEST 가 없다. synthetic-data 잡 설정의 `output.store.kind` 는 file/memory 뿐이라 잡이 HTTP 로 게시하는 설정은 그 영역 변경이 필요하다(docs/change-requests/CR-D26-job-http-publish.md).
- 기준 태그를 v2.1.0 으로 올리는 일은 태그가 push 된 뒤에 한다(준비 목록은 이 구간의 커밋 메시지·보고).

---

# STATUS (2026-10-27 최신 구간: PostgreSQL 기반, 게이트웨이 인증 D85)

- 한 일: postgres 서비스·계정·백업(자체 시험 61건), 게이트웨이 개별 계정/역할·기기 토큰·운영자 경로, 스케줄러 주기(수집기 600/ops-feedback 3600/백업 86400, 실제 스택에서 세 잡이 OK로 도는 것 확인), `config/ops-feedback-job.yaml` 실제 파일화, check-all 규칙 11, E2E·데모의 activate를 X-Openit-User 헤더 HTTP로 변경. 자세한 것은 CHANGELOG.md.
- 다음 구간 준비(코드·구성만, 실행 전): 운영·E2E 구성을 PostgreSQL로, E2E 단계 5r, pg 백업 왕복. 서비스 이미지(PostgreSQL 지원) 준비 뒤 `e2e.sh --fast`로 확인한다.
- 남은 일: (1) 새 release-gate 이미지로 E2E를 다시 돌려 헤더 단언(401, requested_by)을 확인한다. (2) kiosk-frontend가 기기 토큰을 보내도록 바뀌면 데모 브라우저 확인. (3) 서비스가 Postgres를 쓰도록 바뀐 뒤 e2e 백업 단계에 pg-backup 추가. (4) `config/backup.env`가 없으면 backup 잡은 거부(2)로 FAIL 보고: BACKUP_DIR·보관일 결정 필요. (5) OIDC 전환은 병원 IdP 결정 뒤.
- 막힌 것: 없음(전체 E2E 모드는 이번 구간에서 돌리지 않았다).

---

# STATUS (2026-10-15, 둘째 구간: 영역 사이를 HTTP로 연결)

## 한 일

- 다섯 서비스 이미지(survey-service, question-authoring, ops-feedback, release-gate, model-registry)를 각 리포지토리 HEAD 기준으로 다시 빌드·게시하고 digest 잠금을 갱신했다. model-registry(model-lab 소스, 두 번째 Dockerfile)를 compose에 추가했다.
- 서비스 사이 연결을 모두 HTTP로 이었다(D49): base URL은 서비스 이름, 토큰은 역할별로 `secrets/`에서 환경 변수로 전달(비밀 값은 compose.yaml·이미지에 없음). 네트워크 5개 분리는 그대로 유지된다(충돌 없음, 근거는 design.md 1절). 이웃 저장소 볼륨은 공유하지 않는다(D50).
- 수집기 run-once(`job-release-gate-collect`)와 ops-feedback 잡을 컴포즈 잡으로 구성했다.
- E2E를 실제 서비스의 HTTP로 다시 짰다. 시험용 정책(`test/policy/`), 시험용 평가 실행기(`test/gate-runner/`), 시험용 잡 설정(`test/ops-job/`)은 `compose.test.yaml`에서만 연결한다.
- 문서: design(연결 표), boundary(서비스 5개 표), runbook, CR-D10..D14.

## 시험 결과 (실제로 돌린 것)

`bash scripts/e2e.sh` (이미지 빌드부터): 검사 73개 PASS, FAIL 0. 단계별:

| 단계 | 상태 | 내용 |
| --- | --- | --- |
| 1 | REAL | question-authoring 등록→미리보기→확인 x3, I1 HTTP 읽기(읽기 토큰), ReviewRecord·ChangeClassification·원본 해시 출처 |
| 2 | REAL | synthetic-data run-once(호스트), 문항은 I1 HTTP. 보지 못한 문항 평가 파일, 학습과 겹치지 않음, 재실행 멱등 |
| 3 | TEST-SUB | 시험용 PEFT 형식 어댑터를 model-registry에 HTTP로 게시. 게시·읽기·해시는 REAL. E2E_GPU=1 경로는 `scripts/e2e_gpu.sh`(미검증, 기본 끔) |
| 4 | REAL + TEST-SUB | 수집기 run-once가 I1·I3를 HTTP로 읽어 접수 → 판정(inline 검사 REAL) → 승인 평가는 시험용 실행기 → PASS → 릴리스·번들(해시) → 활성화 x2 |
| 5 | REAL + TEST-SUB | 실제 survey-service가 게이트 포인터를 HTTP로 폴링해 새 릴리스를 적재. 한 턴은 CLI 하네스·가짜 백엔드(공개 API O06 없음) |
| 6 | TEST-SUB + REAL | 봉투는 e2e가 만듦. 수집 ACCEPTED/DUPLICATE, 비식별 잡 run-once가 FailureCase 생성, 비식별 trace 검증 |
| 7 | TEST-SUB + REAL | 검토 확인은 이미지 안 API로 대신(CR-D11). synthetic-data가 I7 HTTP로 CONFIRMED 사례를 읽어 새 데이터셋 버전에 인용 |
| 8 | REAL | RollbackRequest → APPLIED, 서비스가 이전 릴리스로 복귀, 권한 없는 역할 403 |
| 9 | REAL | 5개 서비스 healthz/readyz, 네트워크 도달·차단, 라벨 6개, 스케줄러, 백업·복구(5개 저장소를 지웠다 복구 후 HTTP로 다시 읽음), 코드 축 롤백 |

## 아직 막힌 것 / 남은 일

- 학습(model-lab)·저작으로의 환류(7단계 뒤쪽)와 E2E_GPU=1 실제 실행: CR-D12.
- 승인 평가 실행기 구현(운영): CR-D10. 운영 통과 기준(O11)이 없어 운영 게이트는 `can_pass:false`가 정상.
- 검토 게시 HTTP 면: CR-D11. 공개 API(O06): survey-service가 Trace를 직접 내지 못한다.
- 사용자 결정: O16 백업 설정, 스케줄 주기, 도메인·TLS, 외부 감시, GPU 서버 접근 경로, 모델 추론 배포 형태(CR-D08).

## 알아 둘 것

- Docker Desktop(WSL)에서는 임의 배정 호스트 포트로의 push가 데몬에 닿지 않아 시험 레지스트리만 빈 포트를 골라 `0.0.0.0`에 잠시 띄운다.
- `locks/images.lock`의 digest는 이 환경의 임시 레지스트리에서 게시한 값이다. 다른 서버에서는 `publish-images.sh`로 다시 만든다.
- 이웃 리포지토리는 수정하지 않았다(빌드는 `git archive`/clone 사본 `build/ctx`).

## 마무리 (체크포인트 이후)

- images.env 복원 수정 후 `bash scripts/e2e.sh --reuse-build --keep` -> 통과(숫자는 `docs/E2E_RESULTS.md` 과거 기록). `locks/images.lock`을 이 실행의 값(5개 서비스 digest, survey 롤백 복귀 상태)으로 갱신하고 `locks/history/`를 보관했다. 시험 자원은 모두 내렸다.
- 7단계: synthetic-data가 I7(HTTP)로 읽는 것은 REAL, 검토 확인만 TEST-SUB(CR-D11). 8단계: REAL(요청 주체는 e2e의 ops-feedback 역할 토큰; ops 잡의 자동 롤백 평가는 설정하지 않았다). 남은 막힘은 위 표와 CR-D10..D12.
- E2E_GPU=1 경로는 신호 전이라 돌리지 않았다.
- 정리 명령: 시험이 끝나면 e2e.sh가 자동 정리한다(`--keep`일 때만 수동). 로컬 이미지 정리: `for i in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep '^deploy-build/'); do docker rmi -f $i; done`.

## 셋째 구간 (영역들이 막힘을 푼 뒤)

- 최신 HEAD로 5개 이미지를 다시 빌드·게시하고 잠금을 갱신했다. `bash scripts/e2e.sh --keep`/`--reuse-build`: 검사 76개 PASS, FAIL 0.
- 바뀐 것: 7단계 검토를 실제 HTTP(`POST /v1/cases/{id}/review`)로(잘못된 expected 400, 읽기 토큰 403, 없는 사례 404, 201, 재전송 200), 저작으로의 환류 `GET /v1/signals` 확인, 게이트 운영 모드 시험 정책 거부·eval 상태·정책 스키마 검사 추가, qa에 I7 읽기 토큰 연결(ops-ingest를 authoring 네트워크에 추가).
- 남은 막힘 표는 CR-D15와 보고서에 있다.

## 넷째 구간: 사람 승인(D53), 공개 API(D55), 계약 v1.3.1

- 이미지 5개를 계약 v1.3.1 wheel로 다시 빌드·게시하고 잠금을 갱신했다. `bash scripts/e2e.sh --reuse-build --keep`: 통과(숫자는 `docs/E2E_RESULTS.md` 과거 기록).
- 4단계: 제출 -> 자동 검사 -> AWAITING_APPROVAL -> review-report -> `POST /v1/approvals`(시험용 release-approver 토큰, TEST-SUB). 승인 전 PASS 없음, operator 403, 낡은 report_hash 409, REJECT -> REJECT 판정, APPROVE 재전송 멱등·번복 409, 승인 뒤 PASS·릴리스·번들·활성화. 시험용 정책·실행기는 삭제.
- 5단계: 게이트웨이 경유 공개 API 한 턴(Bearer 토큰, 같은 turn_id 멱등, 직원 개입 경로는 외부에 닫힘), 서비스가 Trace를 I6로 전송. 7단계: `reviewed_input` 포함 검토. 막힘은 CR-D16.

## 다섯째 구간: 추론 서버(model-serving, model-runtime v0.5.0), LangGraph survey-service

- 이미지 6개(model-serving 추가; survey-service는 LangGraph 오케스트레이터 HEAD, 게이트·survey는 model-runtime v0.5.0 wheel)를 다시 빌드·게시하고 잠금을 갱신했다. `bash scripts/e2e.sh --reuse-build --keep`: 통과(숫자는 `docs/E2E_RESULTS.md` 과거 기록).
- 5단계가 model-serving을 거친다: 서비스 -> PUT 적재(서버가 게이트 I4에서 번들 읽음) -> parse -> generate. 고정 출력 "(가짜 응답)"으로 서비스 내부 가짜가 아님을 확인했고 `/v1/info`·토큰 거부도 확인했다. 추론 서버를 멈추면 그 턴만 실패하고 서비스는 살며 다시 띄우면 다음 턴이 복구된다.
- 위험 정지 -> 직원 RESUME은 fake 출력이 고정이라 여전히 못 한다: CR-D17(fake에 시험용 위험 스위치 요청). 번들 캐시 볼륨 소유자 문제는 `model-serving-init`으로 우회(CR-D17).

## 여섯째 구간: model-runtime v0.5.1

- `model-serving`을 v0.5.1 태그로 다시 빌드(라벨 0.5.1), chown 초기화 컨테이너 제거(번들 캐시는 `serving-data:/var/lib/model-runtime`), serving_config를 `/v1/info`의 기대값으로 생성, 위험 문구 스위치는 `compose.test.yaml`에만. 5단계에 위험 정지 -> 직원 RESUME/END를 REAL로 추가. `bash scripts/e2e.sh --reuse-build --keep`: 통과(숫자는 `docs/E2E_RESULTS.md` 과거 기록). CR-D18.

## 일곱째 구간 (2026-10-15): kiosk-frontend, 게이트웨이 인증 프록시, 직원 알림 -- E2E 통과

> 정정: 커밋 3f52a4d의 "진행 중, E2E 미통과" 표기는 오프라인 체크포인트 시점의 것이다. 이후 `bash scripts/e2e.sh --reuse-build --keep`을 처음부터 돌려 **전체 통과, 종료 코드 0**을 확인했다(숫자는 `docs/E2E_RESULTS.md` 과거 기록)(헤드의 재실행도 같음). `state_of()`(0.7초 간격 재시도)로 state 조회의 429를 고친 것이 통과의 원인이다.

### 한 일
- `kiosk-frontend`(키오스크+직원 콘솔 정적 이미지) 빌드·compose 추가(`KIOSK_FRONTEND_DIGEST`), 계약 기본 태그 v1.3.2, survey 이미지 `io.openit.langgraph` 라벨(잠금 파일의 langgraph 버전을 빌드 인자로, E2E가 unknown 여부 검사).
- 게이트웨이(`config/Caddyfile`): `/v1/sessions…`에 kiosk 토큰, `/v1/staff/*`·`/v1/sessions/*/intervention`·`/staff/*`는 기본 인증 뒤에만(staff 토큰), SSE 버퍼링 끔·읽기 제한 1시간, 접근 로그에 본문 없음. 인증 없는 직원 API 호출은 401(브라우저 인증 창용), survey에 키오스크 토큰으로 직접 부르면 403.
- `locks/images.lock` 갱신(이 실행의 값, 이미지 7개: survey f52a8e0, qa f631b7d, ops 3ed586a, gate 135fbf7, model-registry e93e6b6, model-serving 0a87bb1, kiosk-frontend 13ee06b).
- `e2e.sh`가 구간별 소요 시간(구간 끝에 `(소요 Ns)`, 요약에 표)을, `e2e_steps.py`가 단계 1~8별 소요 시간을 출력한다.

### E2E 단계별 상태 (당시 전체 통과, 숫자는 `docs/E2E_RESULTS.md`)
| 단계 | 상태 | 내용 |
| --- | --- | --- |
| 1, 2 | REAL | 문항 등록·검수·I1 HTTP 읽기, synthetic-data run-once(호스트) |
| 3 | TEST-SUB | 시험용 어댑터·EvaluationReport(고정 지표)를 model-registry에 게시. serving_config는 추론 서버 `/v1/info` 기대값 |
| 4 | REAL + TEST-SUB | 수집기·자동 검사·승인 요청 보고서·릴리스·번들·활성화 REAL, 승인자는 스크립트(시험용 release-approver 토큰) |
| 5 | REAL + TEST-SUB | 게이트웨이 경유 공개 API, model-serving(fake 백엔드) 경유 한 턴, 추론 서버 중단·복구. 모델은 fake |
| 5f | REAL | 정적 화면(/, /staff/ 인증, sw.js, CSP), 프론트 호출 순서(세션 시작·발화 2턴·state·종료), 권한 분리, 위험 정지(`TEST-RISK`, 시험 구성 전용) -> 알림 OPEN·SSE alert/resolved·직원 RESUME(기본 인증) -> state ACTIVE+resume_text -> 알림 RESOLVED, END 경로 |
| 6 | TEST-SUB + REAL | 실패 신호 봉투는 e2e가 만든 시험 자료, 수집·비식별 잡·FailureCase REAL |
| 7 | REAL + TEST-SUB | `reviewed_input` 포함 검토 HTTP, 개선 신호, synthetic-data의 I7 시드 인용. 학습(model-lab) 회귀 평가 미실행(CR-D12) |
| 8 | REAL | 롤백 APPLIED, 서비스가 이전 릴리스로 복귀 |
| 9 | REAL | healthz/readyz, 네트워크 도달·차단, 라벨, 스케줄러, 백업·삭제·복구(HTTP로 재확인), 코드 축 롤백, 운영 구성 누출 검사 |
| BLOCKED | | 실제 브라우저 화면 동작·STT·웹 푸시 수신(HTTPS·VAPID 필요, SSE만 확인), 운영 TLS·직원 콘솔 인증 방식(미정), 실제 GPU 모델(E2E_GPU 신호 전, CR-D08/D12) |

### 구간별 소요 시간 (--reuse-build, 이미지 빌드 제외)
준비 10s / 단계 9 앞부분(compose 기동·검사) 67s / 단계 1~8 45s / 스케줄러 7s / 백업·복구 87s / 롤백 46s = 합계 262s. 단계 1~8 안: 5단계 17.5s, 5f 8.7s, 8단계 6.1s가 큰 편이다.

### 남은 일
사용자 결정: TLS·도메인, 직원 콘솔 운영 인증, 백업 설정(O16), 스케줄 주기, GPU 서버 경로. 문서(design/boundary/runbook)에 kiosk-frontend·게이트웨이 인증을 반영하는 작업은 다음 지시로 한다.

### Docker 자원
시험 컨테이너·네트워크·볼륨·임시 레지스트리는 모두 내렸다. 로컬 `deploy-build/*` 이미지만 남아 있다.

## e2e.sh 빠른 모드 (--fast)

`bash scripts/e2e.sh --fast --reuse-build`: 단계 1~8과 단계 9 앞부분(compose 기동 검사)만 돌린다. 스케줄러, 백업·복구, 코드 축 롤백은 생략하고 요약에 "생략한 구간 / 전체 합격 아님"을 표시한다. 종료 코드는 돌린 검사 기준이다. 확인: 통과(숫자는 `docs/E2E_RESULTS.md` 과거 기록), 합계 119초(준비 10 + compose 기동 68 + 단계 1~8 41). **인도 전에는 옵션 없는 전체 모드가 필수**다(runbook 6절).

## 여덟째 구간: admin-console(출고 승인 화면) -- 전체 모드·--fast 통과(숫자는 `docs/E2E_RESULTS.md` 과거 기록)

- 이미지 `admin-console`을 로컬 폴더에서 빌드해 compose에 추가, 게이트웨이에 `/admin/`과 승인 경로 네 개(인증 뒤, 읽기/쓰기 토큰 분리, `X-Openit-User`, 보고서 해시 헤더 통과)를 반영. 경계 계약 기본 태그 v1.3.3. E2E 4g(승인 화면 경로를 게이트웨이 경유로 한 번: 목록 -> 보고서 헤더 해시 -> 승인, 승인자 ID가 인증 계정으로 기록, 위조 헤더 무시, 닫은 경로 404, 인증 없이 401). 화면 렌더링은 BLOCKED. 확인된 어긋남은 CR-D19.

## 아홉째 구간: 이미지 게시 인터페이스(D24)

`scripts/publish-image.sh`(서비스 이름 검증, 필수 라벨 검사, push + digest 대조, flock·임시 파일로 잠금 기록, 멱등, 형식 불변), 계약 문서 `docs/ci.md`, GitHub Actions 템플릿 `docs/ci-example/publish-image.yml`, 시험 `scripts/test-publish.sh`(임시 레지스트리, 빈 포트, 전 항목 통과). E2E 전체 모드는 이번에 돌리지 않았다. 미정: CI가 서버 레지스트리에 닿는 방법, 레지스트리 TLS·push 인증·도메인, digest 제출 병합 방식.

## 열째 구간: 게이트웨이 사람 계정 역할(D71), 실패 사례 검토 화면

admin-console(25263ef) 재빌드. 게이트웨이: 계정 -> 역할(release-approver / reviewer) 매핑, 승인 경로와 검토 경로를 역할로 분리(다른 역할은 403, 인증 없음은 401), 검토 경로는 ops-feedback 읽기/reviewer 쓰기 토큰. E2E 7g 추가. `--fast`·전체 모드 통과(숫자는 `docs/E2E_RESULTS.md` 과거 기록). 미확인: 응답 reviewed_by(ops-feedback 작업 대기), 화면 렌더링. CR-D20.

열째 구간 보충: ops-feedback bf210fe 재빌드·잠금 갱신, E2E 7h를 REAL로(검토 응답·I7 조회의 reviewed_by가 인증 계정, 위조 X-Openit-User 무시; 승인 쪽 approver_id도 4g에서 REAL). `--fast`·전체 모드 통과(숫자는 `docs/E2E_RESULTS.md` 과거 기록).

## 열한째 구간: 다른 서버·PC에서도 도는지 (경로 고정 금지)

- `scripts/check-relocatable.sh`: (a) 형제 리포 13개의 git 추적 파일에 절대 경로·워크스페이스 이름·호스트 이름이 없음(허용 목록 `relocatable-allow.txt`, 지금 0건, 검사 정규식은 양성 시료로 확인), (b) 임시 `ws-relocate-XXXX/`에 13개 리포를 로컬 clone한 뒤 그 안의 deploy에서 `e2e.sh --fast` 통과(숫자는 `docs/E2E_RESULTS.md` 과거 기록), 끝나면 임시 폴더 삭제.
- `scripts/check-standalone.sh`: 형제 리포·`build/`·`.venv` 없는 deploy 리포 사본 + 임시 레지스트리의 digest 이미지만으로 `gen-secrets.sh` -> `up.sh`가 운영 구성을 띄운다(통과). 이를 위해 추론 서버의 문진 스키마를 워크스페이스의 `build/survey-schema` 대신 survey-service 이미지의 패키지에서 꺼내는 일회성 작업(`model-serving-schema`)으로 바꿨다.
- runbook 1절을 (A) 개발·CI 워크스페이스, (B) 운영·테스트 서버로 나눠 현재 사실로 고쳤다. (B)에서 아직 안 되는 것: 영역 이미지가 서버 레지스트리에 들어가는 길(CI 접근 방식, TLS·인증), 잠금 파일 전달, 레지스트리 이관 절차 -- 모두 미정.

## 열두째 구간: 누구나 따라 할 수 있는 설치 (사전 점검 + SETUP.md)

`scripts/doctor.sh`(읽기 전용 사전 점검: git, python3·venv, docker·데몬·compose·buildx, 자격증명 우회 알림, 형제 리포와 필요한 태그, 디스크, 인터넷 도달, 고정 포트 없음; 항목마다 OK/WARN/FAIL과 한국어 해결 한 줄), `e2e.sh`/`up.sh` 시작에서 자동 실행(`DEPLOY_SKIP_DOCTOR=1`로 건너뜀), 의존 태그를 `lib.sh` 한 곳으로, `docs/SETUP.md`(환경 유형별 설치). 시험: 정상 환경 전부 OK, docker 제거·없는 소켓·형제 리포 이름 변경·태그 삭제 상황에서 FAIL과 해결 문구 확인, e2e.sh가 doctor FAIL에서 즉시 멈춤.

## 열셋째 구간: 표준 docker 경로 하나로 (WSL 분기·우회 제거)

사용자 지시: 꼼수·우회 없이 표준 방법. `lib.sh`에서 docker.exe 폴백, wslpath/hostpath 변환, `/proc/version` 판정, 자격증명 우회(`check_docker_creds`, 82911c1), `--env-file`을 통한 환경 전달(envfile)을 모두 없앴다. 남은 것은 `DOCKER` 변수로 실행 파일 지정과 `docker info` 실패 시 명확한 오류 중단뿐이다. `doctor.sh`는 우회 대신 진단과 고치는 법을 낸다(데몬 꺼짐·소켓 없음·권한·compose/buildx 없음·자격증명 도우미 실행 불가). release-gate의 `build_image.sh`가 `wslpath -w`/`docker.exe`를 가정하는 점은 CR-D21로 올렸고, `build-images.sh`는 표준 `DOCKER`로 그 스크립트를 그대로 부른다(release-gate가 고친 버전이 push되기 전에는 WSL에서 release-gate 이미지 빌드가 실패한다). SETUP.md B절을 "표준 docker가 데몬에 닿는 상태가 전제 + 환경 설정 절차"로 고쳤다.

## 열넷째 구간: 데모 스크립트 (`scripts/demo.sh`)

`up [--stop-before-approval] [--rebuild] | activate | status | down | reset`. 별도 프로젝트 `deploy-demo`(상시 구성과 따로), compose.yaml + compose.test.yaml(E2E 시험 구성), 호스트 포트는 Docker 배정, 임시 레지스트리는 빈 포트. e2e_steps.py의 단계 코드를 재사용한다(`demo4`: 후보 수집·자동 검사·(시험용 승인자 승인)·활성화, `demo_activate`; 둘은 E2E 기본 실행에 들어가지 않는다). 끝에 접속 주소, 계정과 암호 파일 경로(값 출력 없음), 위험 정지 시험 문구, 승인 대기 시험 제출, 실패 사례 검토용 시험 사례, "이 데이터는 시험용 대체" 문구를 출력한다. 호스트 준비는 `scripts/prepare-host.sh`로 e2e.sh와 공유한다. **검증 한계**: 이 PC는 Docker Desktop이 꺼져 있어 실행하지 못했다(`bash -n`, 사용법·인자 오류 코드, 정적 검사만).

## model-runtime 태그 통일 (v0.5.2)

- 서버의 `demo.sh up --llm`에서 제출 3건이 `REJECTED_AUTO`(`CONTRACT_COMPAT`: 학습 때의 model-runtime 0.5.2이 게이트 기준 0.5.1과 다르다)였다. 중립 패키지·GPU 이미지는 v0.5.2, release-gate·survey-service·CPU model-serving은 v0.5.1로 빌드된 어긋남이 원인이다(`demo.sh diag`로 확인). 우회하지 않고 `scripts/lib.sh`의 `DEPLOY_MR_TAG` 하나(기본 v0.5.2)로 모든 이미지와 중립 패키지 생성기를 통일했다(`DEPLOY_MR_TAG_GPU` 제거). `demo.sh up`의 `have_images`는 이미지 라벨 `io.openit.model-runtime`이 현재 태그와 다르면 기본 8개를 다시 빌드한다(GPU 이미지는 라벨이 같으면 재빌드하지 않는다). 이 PC에서의 실행 확인 범위는 보고에 적었다. 위 '여섯째 구간'의 v0.5.1 서술은 당시 기록이다.

## model-runtime v0.5.3 후보 (deploy가 compose로 대신하고 있는 것)

model-runtime 리포는 수정하지 않았다. 아래는 지금 `compose.llm.yaml`이 환경 변수로 돌리는 것이며, 장기적으로는 이미지(Dockerfile ENV)의 기본값이어야 한다.

- 읽기 전용 루트에서 쓰기 가능한 경로로 돌리는 캐시·홈: `HOME=/var/lib/model-runtime/home`, `XDG_CACHE_HOME=/var/lib/model-runtime/cache`, `VLLM_CACHE_ROOT=…/cache/vllm`, `TORCHINDUCTOR_CACHE_DIR=…/cache/torchinductor`, `TRITON_CACHE_DIR=…/cache/triton`, `TORCH_HOME=…/cache/torch`. 안 돌리면 vLLM 적재가 `~/.cache(컨테이너 HOME 아래)`에서 `OSError: [Errno 30]`(GPU 서버에서 확인)로 실패한다. 이미지가 이 하위 디렉터리를 uid 10001 소유로 미리 만들어 두면 더 좋다.
- 원격 측정 기본 차단(의료 시스템): `VLLM_NO_USAGE_STATS=1`, `DO_NOT_TRACK=1`, `HF_HUB_DISABLE_TELEMETRY=1`.
- 앞선 확인: HF 캐시는 이미지가 준비한 `/var/lib/model-runtime/hf`를 쓴다(HF_HOME 덮어쓰기 불필요).
- 미정: `/tmp`(tmpfs, noexec)에서 실행이 필요한 산출물이 있는지(GPU 서버에서 확인 전). 있다면 `TMPDIR`를 이미지가 준비한 볼륨 경로로 돌리는 편이 tmpfs exec 허용보다 낫다.

- v0.5.3 채택: `DEPLOY_MR_TAG` 기본을 v0.5.3으로 올렸다(통일 태그 정책 유지). v0.5.3 이미지가 캐시·홈·원격 측정 차단 ENV를 기본값으로 갖고 서버가 캐시 디렉터리를 만들므로 `compose.llm.yaml`의 중복 환경 변수를 제거했다(위 후보 항목 해소). GPU 서버 확인 전.

## 열다섯째 구간: 계약 2.0.0 구조로 이전 (2026-10-27, 브랜치 migrate-contracts-2.0.0, 이 PC 한 환경)

기준: boundary-contracts v2.0.0, turn-engine v0.3.0, model-runtime v0.6.1. 이웃 main: survey-service 846dc79, release-gate 7139123, ops-feedback acaf413, synthetic-data 507f58b, model-lab e3fd917, question-authoring f5f02b9, admin-console 4517e91, kiosk-frontend b4a27ea, model-runtime fd185c4(= v0.6.1).

### 시험 결과 (실제로 돌린 것, 이 PC의 WSL2 + Docker Desktop 한 환경. 깨끗한 두 번째 환경 확인은 못 했다)
- `bash scripts/doctor.sh`: 통과(WARN 0). `bash scripts/build-images.sh`: 8개 이미지 빌드 exit=0.
- `bash scripts/e2e.sh --reuse-build`(전체 모드): **전체 통과**(숫자는 `docs/E2E_RESULTS.md` 과거 기록), 합계 247초. `--fast` 중간 실행에서는 단계 5의 기대값(fake 출력)만 실패해 고친 뒤 전체 모드로 다시 돌렸다. 전체 모드 이후에 `e2e_steps.py`의 실제 LLM 경로(`--llm-package`)의 기반 모델 표기를 패키지 값으로 고쳤고 이 경로는 실행해 보지 못했다(구문 검사만).
- 단계 상태: 1 REAL(v2 문항 양식 31개 ID) / 2 **BLOCKED**(synthetic-data NOTHING_TO_DO, G02) / 3 TEST-SUB(시스템 프롬프트 포함 패키지) / 4 REAL+TEST-SUB(자동 검사·사람 승인·릴리스·번들) / 5 REAL(PUT -> extract -> respond, 서버 직접 호출 검사) / 5d REAL(알림이 나오지 않음, `staff_alert_source.active=false`) / 5d-skip **SKIPPED**(직원 콘솔 알림 화면: 시험용 입력원이 survey-service tests/ 에만 있음) / 6 TEST-SUB+REAL / 7 REAL(시드 인용 포함) / 8 REAL / 9 REAL.
- 확인한 것과 못 한 것: `make-llm-package.sh gpu-12g`는 실행해 두 번 같은 바이트(결정성)와 `ModelPackageManifest` 스키마 통과를 확인했다. `demo.sh config --llm`(병합 검증)은 통과했다. **GPU가 필요한 실제 LLM 데모, GPU 이미지 빌드, Qwen3-1.7B 적재는 하지 않았다(서버 미검증, OPEN_GAPS U07/U01).** 서버 절차는 RUN.md 7-2-2.
- 막힌 점은 CR-D22: (1) model-runtime fake 기본 출력(next_item=END)이 v2 흐름에서 모든 턴을 반려시켜 deploy가 시험 전용 진입점으로 고정 출력을 바꿨다, (2) synthetic-data G02, (3) 직원 알림 시험용 입력원, (4) `make_neutral_package.py`가 프롬프트 인자를 받지 않음.
- `locks/images.lock`은 건드리지 않았다(E2E는 임시 잠금을 쓴다).

## 열여섯째 구간: model-runtime v0.6.2 채택 (2026-10-27, 브랜치 follow-mr-0.6.2, 이 PC 한 환경)

기준: boundary-contracts v2.0.0, turn-engine v0.3.0, model-runtime v0.6.2. 이웃 main: survey-service ef94945, release-gate 9f0ff9e, model-lab 3b3c812, ops-feedback acaf413 (모두 이 PC에서 확인).
- 한 일: `DEPLOY_MR_TAG` v0.6.2(이미지 라벨 기대값 포함). 우회 제거: `test/fake-model/fake_server.py`, `scripts/apply_system_prompts.py` 삭제. fake 모델은 표준 서버 + `MODEL_RUNTIME_FAKE_FLOW_FILE=test/fake-model/question_flow.json`(survey-service `question_flow`의 31개 순서 사본). `make-llm-package.sh`는 `make_neutral_package.py --system-prompt-a/-b`를 쓴다. CR-D22 v2 1·4항은 해소.
- 시험(실제로 돌린 것, 깨끗한 두 번째 환경은 확인하지 못했다): `doctor.sh` 통과(WARN 0), `build-images.sh` exit=0(model-serving·survey-service·release-gate 이미지 라벨 `io.openit.model-runtime`=0.6.2 확인), `e2e.sh --reuse-build`(새 이미지를 빌드한 뒤, 전체 모드) 통과(숫자는 `docs/E2E_RESULTS.md` 과거 기록), 246초. `make-llm-package.sh gpu-12g`를 두 번 돌려 결과가 같고 매니페스트의 프롬프트 해시가 `lora_a.system.txt`와 일치함을 확인. GPU 서버·실제 LLM 모드는 확인하지 않았다.
- 남은 것: 단계 2 BLOCKED(G02), 5d 직원 알림 화면 SKIPPED(G01)는 그대로. push·태그는 하지 않았다.

## 열일곱째 구간: 태그 정렬(bc v2.0.2, te v0.4.0, mr v0.7.0), 비밀 파일화(D84), 점검 스크립트 (커밋 37117d2 -> 85e2d27, 이 PC 한 환경)

근거는 CHANGELOG.md와 커밋 메시지다. 이 구간의 E2E는 이 세션에서 다시 돌리지 않았다.
- 기준 태그(`scripts/lib.sh`, 이 세션에서 읽어 확인): boundary-contracts v2.0.2(synthetic-data용도 v2.0.2), turn-engine v0.4.0, model-runtime v0.7.0. 위 열다섯째·열여섯째 구간의 태그는 그 시점 값이다.
- 시험 결과: 커밋 85e2d27의 메시지가 E2E 통과를 적었다(숫자와 근거는 `docs/E2E_RESULTS.md` 과거 기록). 같은 이 PC 한 환경이며 깨끗한 두 번째 환경은 확인하지 못했다. 옮겨 적히던 다른 숫자 하나는 리포지토리 안에서 근거를 찾지 못했다(`docs/E2E_RESULTS.md`에 '근거 없음'으로 적음). 5728769 이후 E2E 재실행 기록도 없다(미확인).
- 비밀 파일화(D84): compose의 `env_file` 토큰을 없애고 최상위 `secrets:`(`secrets/tokens/<이름>`)를 `/run/secrets`에 마운트하며 서비스는 `NAME_FILE` 경로만 받는다. `gen-secrets.sh`는 목록 값도 파일로 만든다. 게이트웨이는 Caddyfile의 `{file./run/secrets/<이름>}`로 읽는다. 원인은 환경 변수의 토큰이 `docker inspect`/`exec env`로 평문 노출된 것이다.
- `scripts/check-secrets-hidden.sh`(정적+동적 노출 검사, 값은 출력하지 않음, E2E 단계). 5728769부터 인자 없이 부르면 데모(`state/demo`)도 점검하고 `--secrets-dir`를 받는다. `demo.sh check-secrets` 추가, `demo.sh up` 끝에서 자동 실행.
- `scripts/check-versions.sh` + 자기 점검 `scripts/test-check-versions.sh`(E2E 단계): `lib.sh` 표와 형제 영역 파일의 태그 표기를 비교하고 어긋나면 `파일:줄`을 출력하며 실패한다.
- GPU 구멍: `docs/GPU_HOLE.md`(H1~H4의 순서·명령·합격 기준·진단·OPEN_GAPS에 적을 항목). 진짜 어댑터 얹기: `demo.sh up --llm --adapter-a/-b DIR --prompt-a/-b FILE`(네 개 모두 필요, `--llm`과 함께만). `make-llm-package.sh`가 `llm_attach_package.py`로 패키지를 만들고, 기반 모델 불일치·순위 초과·파일 누락은 이미지 빌드 전에 거부한다(`--check-only`). `demo.sh config --llm`도 같은 검사를 한다. GPU 서버가 없어 진짜 어댑터로 한 턴은 돌려 보지 못했다(미확인).
- `test-inference-location.sh`: 별도 추론 서버에 시험용 fake 문항 순서 파일(`test/compose.fake-model.yaml`)을 붙였다(없어서 단계 5가 실패했다).

## 점검 대상에 kiosk-frontend·admin-console 추가 (이 세션, 이 PC 한 환경)

- `scripts/check-versions.sh`의 대상 영역을 8개에서 10개로 늘렸다. 두 영역은 `Dockerfile`의 `ARG BOUNDARY_CONTRACT(S)=vX.Y.Z`로 태그를 적는데 기존 정규식이 이 표기(`BOUNDARY_TAG`, `boundary-contracts@v…`만 봤다)를 못 읽어서 `_TAG` 외에 `_CONTRACT`·`_CONTRACTS`도 읽게 했다. 두 영역 파일은 읽기만 했고 수정하지 않았다.
- 현재 결과(읽기만으로 확인): kiosk-frontend(32f3dff)와 admin-console(f62869c)의 `Dockerfile`은 이미 v2.0.2여서 `bash scripts/check-versions.sh`가 통과한다(태그 표기 28건, 영역 10개). 두 영역의 작업 트리가 계약 정렬 중이면 값은 바뀔 수 있다.
- 두 영역이 v1.3.x이면 이 점검은 실패하는 것이 올바른 출력이다. `scripts/test-check-versions.sh`가 두 영역에 v1.3.3을 넣은 임시 워크스페이스로 `kiosk-frontend/Dockerfile:2`, `admin-console/Dockerfile:2`가 `파일:줄`로 출력되며 종료 코드 1이 되는 것을 확인한다. 정렬이 끝나기 전에는 이 점검(E2E 단계 포함)이 실패하고, 두 영역이 표와 같은 태그가 된 뒤 통과해야 한다.
- 자체 시험 `bash scripts/test-check-versions.sh`: 3개 ok / 0 FAIL, 종료 코드 0.

## E2E 값 추출 경로 (U16)
- 가짜 A 흐름 파일을 객체 형식(slots/skips)으로 확장하고 E2E에 단계 5g(값 추출·건너뛰기·서비스 경유 3턴)와 5s(어댑터 교체 시 다른 서비스 불변, 새 릴리스 LOADED)를 추가했다. 둘 다 REAL(모델은 가짜). 확인: `bash scripts/e2e.sh --fast --reuse-build` 통과(전체 모드 아님, 숫자는 `docs/E2E_RESULTS.md` 과거 기록), `scripts/test-check-all.sh` 통과.
- 확인하지 못한 것: 저장된 값 내용(공개 읽기 경로 없음, ops-feedback은 실패 사례만 노출), CORRECT(가짜 A가 내지 않음), 전체 모드.

## 어댑터 교체 경로와 측정 도구 (U08)
- `demo.sh swap-adapters`를 추가했다. model-serving만 새 번들을 적재하게 하는 경로가 deploy에 없던 구멍(D72)을 메운다. E2E 단계 코드(게시 `publish_packages`, 컨테이너 비교 `container_ids`)를 재사용한다. 승인자는 시험용 스크립트(TEST-SUB)다.
- `scripts/probe-serving.py`: model-serving extract 측정 도구(GPU_HOLE H4에서 쓴다). 자체 시험 `scripts/test_probe_serving.py`.
- 확인한 것(이 PC, 가짜 백엔드 데모): 시험용 어댑터 교체가 통과하고 다른 서비스 컨테이너의 StartedAt이 불변이며 새 릴리스가 LOADED. 기반 모델 불일치 어댑터는 거부되고 활성 릴리스는 그대로. probe는 데모의 model-serving에 돌아 표가 나온다.
- 확인하지 못한 것: `--llm`(vLLM)에서의 교체, 실제 모델의 OUTPUT_INVALID 분포, 전체 E2E.

## E2E 단계 2를 synthetic-data 게시기 모드로 (배선 REAL, 데이터는 시험용)

- 한 일: 단계 2가 `synthetic_data import`로 `test/import-v2/`의 시험용 v2 jsonl 6개를 검증·게시한다(허용치 초과 거부 종료 4, 허용 안 게시, 재실행 멱등). 상세와 한계는 docs/E2E.md "단계 2". compose에는 synthetic-data 서비스가 없고(GPU 서버 몫, D40) 게시기도 호스트에서 돌리므로 compose 설정은 바꾸지 않았다.
- 남은 것: 실제 학습 데이터 파일로 게시한 적 없음. 의미 검사와 CR-006 항목(문항 세트 출처, 버전 값, 미검수 행 정책)은 헤드/synthetic-data 결정을 기다린다.
