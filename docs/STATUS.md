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
