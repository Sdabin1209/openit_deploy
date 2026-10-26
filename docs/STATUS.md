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

- images.env 복원 수정 후 `bash scripts/e2e.sh --reuse-build --keep` -> 73 PASS / 0 FAIL. `locks/images.lock`을 이 실행의 값(5개 서비스 digest, survey 롤백 복귀 상태)으로 갱신하고 `locks/history/`를 보관했다. 시험 자원은 모두 내렸다.
- 7단계: synthetic-data가 I7(HTTP)로 읽는 것은 REAL, 검토 확인만 TEST-SUB(CR-D11). 8단계: REAL(요청 주체는 e2e의 ops-feedback 역할 토큰; ops 잡의 자동 롤백 평가는 설정하지 않았다). 남은 막힘은 위 표와 CR-D10..D12.
- E2E_GPU=1 경로는 신호 전이라 돌리지 않았다.
- 정리 명령: 시험이 끝나면 e2e.sh가 자동 정리한다(`--keep`일 때만 수동). 로컬 이미지 정리: `for i in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep '^deploy-build/'); do docker rmi -f $i; done`.

## 셋째 구간 (영역들이 막힘을 푼 뒤)

- 최신 HEAD로 5개 이미지를 다시 빌드·게시하고 잠금을 갱신했다. `bash scripts/e2e.sh --keep`/`--reuse-build`: 검사 76개 PASS, FAIL 0.
- 바뀐 것: 7단계 검토를 실제 HTTP(`POST /v1/cases/{id}/review`)로(잘못된 expected 400, 읽기 토큰 403, 없는 사례 404, 201, 재전송 200), 저작으로의 환류 `GET /v1/signals` 확인, 게이트 운영 모드 시험 정책 거부·eval 상태·정책 스키마 검사 추가, qa에 I7 읽기 토큰 연결(ops-ingest를 authoring 네트워크에 추가).
- 남은 막힘 표는 CR-D15와 보고서에 있다.

## 넷째 구간: 사람 승인(D53), 공개 API(D55), 계약 v1.3.1

- 이미지 5개를 계약 v1.3.1 wheel로 다시 빌드·게시하고 잠금을 갱신했다. `bash scripts/e2e.sh --reuse-build --keep`: 72 PASS / 0 FAIL.
- 4단계: 제출 -> 자동 검사 -> AWAITING_APPROVAL -> review-report -> `POST /v1/approvals`(시험용 release-approver 토큰, TEST-SUB). 승인 전 PASS 없음, operator 403, 낡은 report_hash 409, REJECT -> REJECT 판정, APPROVE 재전송 멱등·번복 409, 승인 뒤 PASS·릴리스·번들·활성화. 시험용 정책·실행기는 삭제.
- 5단계: 게이트웨이 경유 공개 API 한 턴(Bearer 토큰, 같은 turn_id 멱등, 직원 개입 경로는 외부에 닫힘), 서비스가 Trace를 I6로 전송. 7단계: `reviewed_input` 포함 검토. 막힘은 CR-D16.

## 다섯째 구간: 추론 서버(model-serving, model-runtime v0.5.0), LangGraph survey-service

- 이미지 6개(model-serving 추가; survey-service는 LangGraph 오케스트레이터 HEAD, 게이트·survey는 model-runtime v0.5.0 wheel)를 다시 빌드·게시하고 잠금을 갱신했다. `bash scripts/e2e.sh --reuse-build --keep`: 80 PASS / 0 FAIL.
- 5단계가 model-serving을 거친다: 서비스 -> PUT 적재(서버가 게이트 I4에서 번들 읽음) -> parse -> generate. 고정 출력 "(가짜 응답)"으로 서비스 내부 가짜가 아님을 확인했고 `/v1/info`·토큰 거부도 확인했다. 추론 서버를 멈추면 그 턴만 실패하고 서비스는 살며 다시 띄우면 다음 턴이 복구된다.
- 위험 정지 -> 직원 RESUME은 fake 출력이 고정이라 여전히 못 한다: CR-D17(fake에 시험용 위험 스위치 요청). 번들 캐시 볼륨 소유자 문제는 `model-serving-init`으로 우회(CR-D17).

## 여섯째 구간: model-runtime v0.5.1

- `model-serving`을 v0.5.1 태그로 다시 빌드(라벨 0.5.1), chown 초기화 컨테이너 제거(번들 캐시는 `serving-data:/var/lib/model-runtime`), serving_config를 `/v1/info`의 기대값으로 생성, 위험 문구 스위치는 `compose.test.yaml`에만. 5단계에 위험 정지 -> 직원 RESUME/END를 REAL로 추가. `bash scripts/e2e.sh --reuse-build --keep`: 80 PASS / 0 FAIL. CR-D18.

## 일곱째 구간 (2026-10-15): kiosk-frontend, 게이트웨이 인증 프록시, 직원 알림 -- E2E 통과

> 정정: 커밋 3f52a4d의 "진행 중, E2E 미통과" 표기는 오프라인 체크포인트 시점의 것이다. 이후 `bash scripts/e2e.sh --reuse-build --keep`을 처음부터 돌려 **84 PASS / 0 FAIL, 종료 코드 0**을 확인했다(헤드의 재실행도 같음). `state_of()`(0.7초 간격 재시도)로 state 조회의 429를 고친 것이 통과의 원인이다.

### 한 일
- `kiosk-frontend`(키오스크+직원 콘솔 정적 이미지) 빌드·compose 추가(`KIOSK_FRONTEND_DIGEST`), 계약 기본 태그 v1.3.2, survey 이미지 `io.openit.langgraph` 라벨(잠금 파일의 langgraph 버전을 빌드 인자로, E2E가 unknown 여부 검사).
- 게이트웨이(`config/Caddyfile`): `/v1/sessions…`에 kiosk 토큰, `/v1/staff/*`·`/v1/sessions/*/intervention`·`/staff/*`는 기본 인증 뒤에만(staff 토큰), SSE 버퍼링 끔·읽기 제한 1시간, 접근 로그에 본문 없음. 인증 없는 직원 API 호출은 401(브라우저 인증 창용), survey에 키오스크 토큰으로 직접 부르면 403.
- `locks/images.lock` 갱신(이 실행의 값, 이미지 7개: survey f52a8e0, qa f631b7d, ops 3ed586a, gate 135fbf7, model-registry e93e6b6, model-serving 0a87bb1, kiosk-frontend 13ee06b).
- `e2e.sh`가 구간별 소요 시간(구간 끝에 `(소요 Ns)`, 요약에 표)을, `e2e_steps.py`가 단계 1~8별 소요 시간을 출력한다.

### E2E 단계별 상태 (84 PASS / 0 FAIL)
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

`bash scripts/e2e.sh --fast --reuse-build`: 단계 1~8과 단계 9 앞부분(compose 기동 검사)만 돌린다. 스케줄러, 백업·복구, 코드 축 롤백은 생략하고 요약에 "생략한 구간 / 전체 합격 아님"을 표시한다. 종료 코드는 돌린 검사 기준이다. 확인: 56 PASS / 0 FAIL, 합계 119초(준비 10 + compose 기동 68 + 단계 1~8 41). **인도 전에는 옵션 없는 전체 모드가 필수**다(runbook 6절).

## 여덟째 구간: admin-console(출고 승인 화면) -- 전체 모드 87 PASS / 0 FAIL, --fast 59 PASS / 0 FAIL

- 이미지 `admin-console`을 로컬 폴더에서 빌드해 compose에 추가, 게이트웨이에 `/admin/`과 승인 경로 네 개(인증 뒤, 읽기/쓰기 토큰 분리, `X-Openit-User`, 보고서 해시 헤더 통과)를 반영. 경계 계약 기본 태그 v1.3.3. E2E 4g(승인 화면 경로를 게이트웨이 경유로 한 번: 목록 -> 보고서 헤더 해시 -> 승인, 승인자 ID가 인증 계정으로 기록, 위조 헤더 무시, 닫은 경로 404, 인증 없이 401). 화면 렌더링은 BLOCKED. 확인된 어긋남은 CR-D19.

## 아홉째 구간: 이미지 게시 인터페이스(D24)

`scripts/publish-image.sh`(서비스 이름 검증, 필수 라벨 검사, push + digest 대조, flock·임시 파일로 잠금 기록, 멱등, 형식 불변), 계약 문서 `docs/ci.md`, GitHub Actions 템플릿 `docs/ci-example/publish-image.yml`, 시험 `scripts/test-publish.sh`(임시 레지스트리, 빈 포트, 전 항목 통과). E2E 전체 모드는 이번에 돌리지 않았다. 미정: CI가 서버 레지스트리에 닿는 방법, 레지스트리 TLS·push 인증·도메인, digest 제출 병합 방식.

## 열째 구간: 게이트웨이 사람 계정 역할(D71), 실패 사례 검토 화면

admin-console(25263ef) 재빌드. 게이트웨이: 계정 -> 역할(release-approver / reviewer) 매핑, 승인 경로와 검토 경로를 역할로 분리(다른 역할은 403, 인증 없음은 401), 검토 경로는 ops-feedback 읽기/reviewer 쓰기 토큰. E2E 7g 추가. `--fast` 59 PASS / 0 FAIL, 전체 모드 87 PASS / 0 FAIL. 미확인: 응답 reviewed_by(ops-feedback 작업 대기), 화면 렌더링. CR-D20.

열째 구간 보충: ops-feedback bf210fe 재빌드·잠금 갱신, E2E 7h를 REAL로(검토 응답·I7 조회의 reviewed_by가 인증 계정, 위조 X-Openit-User 무시; 승인 쪽 approver_id도 4g에서 REAL). `--fast` 59 PASS / 0 FAIL, 전체 모드 87 PASS / 0 FAIL.

## 열한째 구간: 다른 서버·PC에서도 도는지 (경로 고정 금지)

- `scripts/check-relocatable.sh`: (a) 형제 리포 13개의 git 추적 파일에 절대 경로·워크스페이스 이름·호스트 이름이 없음(허용 목록 `relocatable-allow.txt`, 지금 0건, 검사 정규식은 양성 시료로 확인), (b) 임시 `ws-relocate-XXXX/`에 13개 리포를 로컬 clone한 뒤 그 안의 deploy에서 `e2e.sh --fast` 통과(60 PASS / 0 FAIL), 끝나면 임시 폴더 삭제.
- `scripts/check-standalone.sh`: 형제 리포·`build/`·`.venv` 없는 deploy 리포 사본 + 임시 레지스트리의 digest 이미지만으로 `gen-secrets.sh` -> `up.sh`가 운영 구성을 띄운다(통과). 이를 위해 추론 서버의 문진 스키마를 워크스페이스의 `build/survey-schema` 대신 survey-service 이미지의 패키지에서 꺼내는 일회성 작업(`model-serving-schema`)으로 바꿨다.
- runbook 1절을 (A) 개발·CI 워크스페이스, (B) 운영·테스트 서버로 나눠 현재 사실로 고쳤다. (B)에서 아직 안 되는 것: 영역 이미지가 서버 레지스트리에 들어가는 길(CI 접근 방식, TLS·인증), 잠금 파일 전달, 레지스트리 이관 절차 -- 모두 미정.

## 열두째 구간: 누구나 따라 할 수 있는 설치 (사전 점검 + SETUP.md)

`scripts/doctor.sh`(읽기 전용 사전 점검: git, python3·venv, docker·데몬·compose·buildx, 자격증명 우회 알림, 형제 리포와 필요한 태그, 디스크, 인터넷 도달, 고정 포트 없음; 항목마다 OK/WARN/FAIL과 한국어 해결 한 줄), `e2e.sh`/`up.sh` 시작에서 자동 실행(`DEPLOY_SKIP_DOCTOR=1`로 건너뜀), 의존 태그를 `lib.sh` 한 곳으로, `docs/SETUP.md`(환경 유형별 설치). 시험: 정상 환경 전부 OK, docker 제거·없는 소켓·형제 리포 이름 변경·태그 삭제 상황에서 FAIL과 해결 문구 확인, e2e.sh가 doctor FAIL에서 즉시 멈춤.

## 열셋째 구간: 표준 docker 경로 하나로 (WSL 분기·우회 제거)

사용자 지시: 꼼수·우회 없이 표준 방법. `lib.sh`에서 docker.exe 폴백, wslpath/hostpath 변환, `/proc/version` 판정, 자격증명 우회(`check_docker_creds`, 82911c1), `--env-file`을 통한 환경 전달(envfile)을 모두 없앴다. 남은 것은 `DOCKER` 변수로 실행 파일 지정과 `docker info` 실패 시 명확한 오류 중단뿐이다. `doctor.sh`는 우회 대신 진단과 고치는 법을 낸다(데몬 꺼짐·소켓 없음·권한·compose/buildx 없음·자격증명 도우미 실행 불가). release-gate의 `build_image.sh`가 `wslpath -w`/`docker.exe`를 가정하는 점은 CR-D21로 올렸고, `build-images.sh`는 표준 `DOCKER`로 그 스크립트를 그대로 부른다(release-gate가 고친 버전이 push되기 전에는 WSL에서 release-gate 이미지 빌드가 실패한다). SETUP.md B절을 "표준 docker가 데몬에 닿는 상태가 전제 + 환경 설정 절차"로 고쳤다.

## 열넷째 구간: 데모 스크립트 (`scripts/demo.sh`)

`up [--stop-before-approval] [--rebuild] | activate | status | down | reset`. 별도 프로젝트 `deploy-demo`(상시 구성과 따로), compose.yaml + compose.test.yaml(E2E 시험 구성), 호스트 포트는 Docker 배정, 임시 레지스트리는 빈 포트. e2e_steps.py의 단계 코드를 재사용한다(`demo4`: 후보 수집·자동 검사·(시험용 승인자 승인)·활성화, `demo_activate`; 둘은 E2E 기본 실행에 들어가지 않는다). 끝에 접속 주소, 계정과 암호 파일 경로(값 출력 없음), 위험 정지 시험 문구, 승인 대기 시험 제출, 실패 사례 검토용 시험 사례, "이 데이터는 시험용 대체" 문구를 출력한다. 호스트 준비는 `scripts/prepare-host.sh`로 e2e.sh와 공유한다. **검증 한계**: 이 PC는 Docker Desktop이 꺼져 있어 실행하지 못했다(`bash -n`, 사용법·인자 오류 코드, 정적 검사만).
