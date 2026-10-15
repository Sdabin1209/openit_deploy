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

## 일곱째 구간: kiosk-frontend, 게이트웨이 인증 프록시, 직원 알림 (진행 중, E2E 미통과) -- 오프라인 체크포인트

### 한 일 (커밋됨)
- `kiosk-frontend`(키오스크+직원 콘솔 정적 이미지)를 빌드·compose에 추가(`build-images.sh`가 `../kiosk-frontend` main을 `git archive`, 잠금 변수 `KIOSK_FRONTEND_DIGEST`). 계약 기본 태그를 v1.3.2로 올렸다(`BOUNDARY_TAG_ALL`).
- survey 이미지의 `io.openit.langgraph` 라벨: 빌드 때 `requirements.lock`의 `langgraph==` 값을 `LANGGRAPH_VERSION`으로 넘긴다. E2E가 unknown이 아닌지 검사한다(통과).
- 게이트웨이(`config/Caddyfile`): `/v1/sessions…`에 kiosk 토큰, `/v1/staff/*`와 `/v1/sessions/*/intervention`에는 **기본 인증 뒤에만** staff 토큰을 붙인다. SSE는 `flush_interval -1`·읽기 제한 1시간, `/staff/*`도 기본 인증, 나머지는 kiosk-frontend 정적. 접근 로그는 본문을 남기지 않는다. 비밀: `secrets/gateway.env`(두 토큰), `secrets/gateway-staff-auth.caddy`(기본 인증 해시, 0644), `tokens/staff-console-password`. 운영 인증 방식(SSO 등)·HTTPS 종단은 미정이다(STT·웹 푸시는 보안 출처가 필요).
- 인증 없는 `/v1/staff` 호출은 게이트웨이가 **401**(브라우저 인증 창용)로 답한다. 요청서의 403은 survey-service가 키오스크 토큰을 받았을 때의 응답이며 E2E가 survey 직접 호출로 확인한다.
- E2E 5f 추가: (a) `/`·`/staff/`(401/200)·`/staff/sw.js`·CSP, (b) 토큰 없이 같은 출처로 세션 시작·발화 2턴·state·종료, (c) 권한 분리, (d) 위험 정지(DELIVERY_FAILED이지만 알림은 OPEN) -> SSE alert/resolved -> 직원 RESUME(기본 인증) -> state ACTIVE+resume_text -> 알림 RESOLVED -> END 경로.

### E2E 상태
- 마지막 전체 실행: 83 PASS / 1 FAIL. 실패는 5f에서 `GET /v1/sessions/{id}/state`가 0.5초 간격 제한(429 UNAVAILABLE)에 걸린 것. `state_of()`(0.7초 간격 재시도)로 고쳤으나 **고친 뒤 다시 돌리지 못했다** (5f의 (c),(d)와 6~8단계, 9단계 검증이 그 뒤 실행에서 확인되지 않음).
- 위험 정지 관찰: SSE 구독자가 있으면 `staff_alert=DELIVERED`이고 응답의 `turn_failure_signal`이 null이다(전달 성공은 실패 신호가 아니다). 구독자가 없으면 `DELIVERY_FAILED` 신호이고 알림은 저장되어 OPEN으로 조회된다.

### 이어서 할 일
네트워크가 필요 없는 것(로컬 이미지가 남아 있다: deploy-build/{survey-service:f52a8e0, question-authoring:f631b7d, ops-feedback:3ed586a, release-gate:135fbf7, model-registry:e93e6b6, model-serving:0a87bb1, kiosk-frontend:13ee06b}):
1. `bash scripts/e2e.sh --reuse-build --keep` (빌드 생략, pip는 이미 설치된 것만 쓰면 오프라인 가능). 5f의 (c),(d)를 확인하고 실패하면 고친다.
2. 통과하면 `cp state/e2e-<pid>/images.lock locks/images.lock; cp state/e2e-<pid>/history/*.lock locks/history/`, 정리(`dc deploy-e2e-<pid> --profile jobs down -v`, `REGISTRY_PROJECT=deploy-e2e-reg-<pid> scripts/registry.sh down -v`, `rm -rf state/e2e-<pid>`), 문서(design/boundary/runbook/CHANGELOG)에 kiosk-frontend·게이트웨이 인증·CR 반영, 커밋.
네트워크가 필요한 것: 이미지 재빌드(다른 영역 HEAD가 바뀌었을 때), `npm ci`(kiosk-frontend 재빌드), pip 신규 설치, 베이스 이미지 pull.

### Docker 자원
컨테이너·네트워크·볼륨·임시 레지스트리는 모두 내렸다. 로컬 이미지(`deploy-build/*`, 오래된 태그 포함)만 남아 있다: 정리는 `for i in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep '^deploy-build/'); do docker rmi -f $i; done`.
