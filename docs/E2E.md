# 끝에서 끝까지 한 바퀴 (합격 시나리오)

> 헤드 전달본(2026-10-15). 이 시나리오를 한 번에 실행하는 스크립트는 deploy가 소유한다. 모델 단계(3)는 GPU 호스트가 필요하므로, 이 환경에서는 model-runtime의 가짜 백엔드와 시험용 어댑터 디렉터리로 단계를 대신하고 그 사실을 보고서에 표시한다(시험 자료는 이름에 test를 넣는다).

시스템이 모델 성능을 제외하고 완성되었는지 확인하는 기준이다(D38). 품질은 보지 않고 **각 단계가 다음 단계의 입력을 만들고 순환이 닫히는지**만 본다. 이 시나리오를 한 번에 실행하는 스크립트는 deploy가 소유하며, 각 단계의 시험 자료(작은 문항 자료, 작은 기반 모델, 짧은 학습 설정)는 시험용임을 이름에 표시한다. 시험 자료가 운영 설정으로 흘러들어가면 안 된다.

| # | 단계 | 담당 | 인터페이스 | 확인할 것 |
| --- | --- | --- | --- | --- |
| 1 | 저자가 문항 자료를 올리고 미리보기를 확인한다 | question-authoring | I1 | `QuestionBank` 버전, `ReviewRecord`(clinical_basis_approved), `ChangeClassification`, 원본 해시 출처 |
| 2 | 문항을 읽어 학습·평가 데이터를 만든다(보지 못한 문항 평가 포함) | synthetic-data | I1→I2 | `DatasetManifest`, 평가 시나리오가 학습과 겹치지 않음 |
| 3 | 설정 하나로 학습·평가·패키징·게시가 돈다 | model-lab | I2→I3 | `ModelPackageManifest`(어댑터 해시, 계보), 같은 설정과 시드로 재실행 시 같은 결과 |
| 4 | 후보 수집기가 새 조합을 찾아 판정하고, 통과하면 릴리스와 번들을 만든다 | release-gate | I1,I3→I4,I5 | `GateDecision`, `ReleaseManifest`, 번들 해시 검증 |
| 5 | 서비스가 새 포인터를 보고 새 세션부터 새 릴리스로 한 턴 이상을 처리한다 | survey-service | I4,I8,I9→I6 | 턴 처리, `TraceEnvelope` 전송, 재전송해도 중복 없음 |
| 6 | Trace를 수집·비식별해 실패 사례를 만든다(보지 못한 문항 발화를 일부러 넣어 유도) | ops-feedback | I6→I7 | `FailureCase`에 비식별 전 데이터 없음 |
| 7 | 실패 사례가 데이터 생성·학습·저작으로 돌아간다 | synthetic-data, model-lab, question-authoring | I7 | 새 데이터셋 버전이 실패 사례를 시드로 인용 |
| 8 | 롤백 요청이 활성 릴리스를 되돌린다 | ops-feedback→release-gate | I5 | `RollbackReceipt`, 서비스가 새 세션부터 이전 릴리스 사용 |
| 9 | 모든 서비스가 Compose에서 이미지로 뜨고 주기 잡이 스케줄러로 돈다 | deploy | — | `/healthz`, digest 잠금으로 코드 축 롤백 |

합격 조건: 1~9가 사람 손 없이 순서대로 실행되고, 모든 레코드가 계약 스키마와 해시 검증을 통과한다.

## 단계 5c: 정정(CORRECT) 흐름 (deploy 소유, 시나리오 5의 일부)

`scripts/e2e_steps.py`의 `5c`. 가짜 A(model-runtime 0.7.2)의 선택 항목 `corrections`를 `test/fake-model/question_flow.json`에 둔다: 발화에 `아까 말`이 있고 입력 `question_id`가 `Q1.D02`이면 `Q1.D01.diagnosed`를 `false`로 정정하는 `CORRECT`를 낸다(`Q1.D01.diagnosed`는 survey-service의 문진 스키마 `QuestionFlow`/시험 문항 세트에 있는 실제 칸 키다). 흐름: (1) 추론 서버를 직접 불러 `Q1.D02`에서는 `CORRECT`(값 `CORRECTION`), `Q1.D03`에서는 일반 `NEXT`임을 본다. (2) 서비스를 거쳐 `Q1.D01`에 "네 있어요"(저장) 뒤 "아까 말한 거 아니에요"를 보낸다. (3) 같은 발화를 `Q1.D01`에서 보낸 대조 세션은 정정이 아니다.

**정정이 처리됐다고 판단하는 신호.** 저장된 값을 읽는 환자용 공개 경로는 없지만, 직원 세션 조회 `GET /v1/staff/sessions/{id}`(게이트웨이 경유, 직원 계정, `StaffSessionView`, boundary-contracts `PUBLIC_API.md`의 직원 콘솔 절)가 읽기 전용으로 두 가지를 낸다: `turns[].action`(LoRA-A가 낸 절차, 이 턴이 `CORRECT`인지)과 `values[]`(저장된 칸의 `value`와 `status`, 정정된 적이 있으면 `CORRECTION`). 근거 문구는 survey-service `docs/change-requests/CR-013-staff-session-view-public-api.md`(PUBLIC_API.md가 채택)와 `docs/design.md`의 저장 규칙(ANSWERED·CORRECTION만 저장)이다. 단언: 정정 전 `Q1.D01.diagnosed=true`(ANSWERED), 정정 뒤 턴 기록 action이 `[NEXT, CORRECT]`, 값 `false`·`CORRECTION`, 세션 `IN_PROGRESS`, 턴 실패 신호 없음, Trace 전송 수 증가. 이 단계는 서비스가 `CORRECT`를 검증·저장·기록하는 데까지만 본다.

**못 보는 것.** 직원 조회는 값의 현재 상태만 주므로, 정정 전 값이 이력(`NEW_REVISION`)에 남았는지는 볼 수 없다. 다음에 어느 문항을 묻는지(`progress_record.current_question_id`)도 공개 조회에 없어, 정정 뒤 같은 문항을 다시 묻는지는 확인하지 못한다. 응답 문장은 가짜 B의 고정 문장이라 환자에게 나간 문장의 내용은 보지 않는다. 가짜 A의 규칙(키워드와 `at`)이 맞는지를 볼 뿐 모델이 실제 정정 표현을 알아듣는지는 보지 않는다. 단독 실행은 활성 릴리스를 만드는 단계가 필요하다: `bash scripts/e2e.sh --only 1,2,3,4,5c`.

## 단계 5p: PostgreSQL 컨테이너 재시작 (deploy 소유, 시나리오 9의 일부)

`scripts/e2e_steps.py`의 `5p`. question-authoring에 자료를 등록해 쓴 뒤 postgres 컨테이너를 `docker stop`하고, 서비스 `/readyz`가 200이 아닌 상태가 되는 것(`/healthz`는 200 유지)을 관찰해 단계 출력에 코드와 경과 시간을 남긴다. `docker start`로 다시 띄우면 모든 서비스 `/readyz`가 200으로 돌아오는지, 재시작 전후 데이터베이스 행 지문(`pg-fingerprint.sh`)이 같은지, 복구 뒤 새 쓰기가 되는지 본다. 단계 8 뒤에 돈다. 단독 실행: `bash scripts/e2e.sh --only 5p`(활성 릴리스가 없어 survey-service는 제외). survey-service까지 보려면 활성 릴리스를 만드는 단계를 함께 준다: `--only 1,2,3,4,5p`. `--only`는 전체 합격이 아니며 `E2E_RESULTS.md`에 기록하지 않는다. 관찰에서 나온 영역 요청: [CR-D23](change-requests/CR-D23-survey-readyz-db-outage.md).

## gateway(Caddy)의 상류 장애 응답과 /readyz (FAULT_POLICY 5·6, deploy 소유)

`config/Caddyfile`. Caddy v2.11.7(`locks/images.lock`의 digest 이미지, `caddy validate`는 `scripts/test-gateway-auth.sh`가 돌린다). 설정에 명시한 것: 상류 연결(`dial_timeout`)과 응답 헤더 대기(`response_header_timeout`; 환자 API는 연결 1초 + 응답 헤더 8.5초 = 합 9.5초 상한으로, 서버 턴 총 마감 6초(survey-service 기본)보다 길고 키오스크 대기 10초보다 짧게 / 직원·정적 화면은 연결 2초 + 10초 / `/readyz`는 연결 1초 + 2초). 두 타이머는 순차라 합이 상한이다, 재시도 없음(`lb_try_duration 0`). `handle_errors`가 Caddy의 502·503을 `503`, 504를 `504`로 바꾸고 둘 다 본문 `{"code":"UPSTREAM_UNAVAILABLE"}`, `Content-Type: application/json`, `Retry-After: 2`, `Cache-Control: no-store`를 준다. Caddy의 `{http.error.*}`를 쓰지 않으므로 본문에 상류 주소·오류 문구가 없다. gateway `/healthz`는 상류와 무관한 정적 200이고, `/readyz`는 survey-service `/readyz`를 프록시해 2xx면 `ok` 200, 아니면 서비스의 상태 코드와 `{"ready":false}`(서비스의 내부 문제 목록은 밖에 내지 않는다)를 준다.

**Caddy 기본 동작의 관찰(추정이 아니라 설정 없이 돌려 본 값, 이 PC, 같은 이미지, `docker stop`/`pause` 한 python 서버 앞에서).** 설정 없는 `reverse_proxy`: 이름 해석 실패 502(3.0초 뒤), 상류 컨테이너 중지 502(3.1초 뒤), 상류 무응답(pause)은 60초를 기다려도 응답이 없었다(시간 제한 없음, 호출자가 먼저 끊음). 위 설정을 단 같은 구성: 중지 503(2.0초 뒤), 무응답 504(응답 헤더 대기를 3초로 둔 시험에서 3.0초 뒤). 즉 기본 상태에서는 "연결 거부는 503, 시간 초과는 504"가 저절로 되지 않고 무응답에는 마감이 없어서 명시 설정이 필요하다.

## 단계 5q, 5w, 5p 확장: 장애 주입 (FAULT_POLICY, deploy 소유)

모두 `scripts/e2e_steps.py`. 단독 실행은 활성 릴리스가 필요해 `bash scripts/e2e.sh --only 1,2,3,4,5q,5w,5p`처럼 단계 1~4를 함께 준다(`--only`는 전체 합격이 아니고 정본에 기록하지 않는다). 상태 `POLICY-PENDING`은 실패가 아니다: FAULT_POLICY가 정한 기대인데 현재 영역 코드로는 통과하지 않는 정책 단언이며, 약화하지 않고 어떤 변경을 기다리는지와 지금 값을 단계 출력에 남긴다(통과하면 같은 줄이 REAL로 나온다).

- **5q**: survey-service `docker stop` 동안 gateway 경유 환자 턴이 `503 {"code":"UPSTREAM_UNAVAILABLE"}`(+`Retry-After`, JSON, 내부 주소 없음), gateway `/readyz` 비정상, `/healthz` 200. `docker start` 뒤 `/readyz` 200, 이전 값 보존, 상류에 닿지 못한 턴은 기록 없음, 같은 `turn_id` 재전송이 200으로 확정. 정책 단언: 재시작 뒤 이미 확정된 `turn_id` 재전송이 저장된 응답과 같고 한 번만 기록된다.
- **5w**: survey-service `docker pause`(연결은 되나 무응답) 동안 gateway 경유 환자 요청이 응답 헤더 마감 근처에서 `504 UPSTREAM_UNAVAILABLE`(단언: gateway 접근 로그의 `duration`이 서버 총 마감 6초 이상, 키오스크 대기 10초 미만. 클라이언트가 본 시간은 따로 정책 단언: 아래 측정표), gateway `/readyz`는 2초대에 504, `/healthz` 200. `unpause` 뒤 복구. 관찰: 504를 받은 턴을 서비스가 `unpause` 뒤에 처리했는지(횟수 출력)와 같은 `turn_id` 재전송 뒤 발화 기록이 한 번인지(정책 단언).
- **5p 확장**(활성 릴리스가 있을 때): PostgreSQL 중지 중 환자 턴을 gateway 경유로 보내 FAULT_POLICY가 인정한 실패 응답, 곧 `503` + `code: UNAVAILABLE` + `retryable: true`가 오는지(아니면 FAIL), 값이 저장되지 않는지(부분 저장 없음), 복구 뒤 같은 `turn_id` 재전송이 확정되고 값이 한 번 저장되는지 본다. 정책 단언(POLICY-PENDING 가능): 총 마감(survey-service 6초 + 전달 여유 0.5초 이내), 재전송 뒤 발화 기록 한 번. `write_committed=NOT_COMMITTED` 표시 자체는 요구하지 않는다(헤드가 재시도 가능한 503 UNAVAILABLE 본문을 실패 응답으로 인정).
- 정정 신호로 쓰는 읽기 경로는 직원 세션 조회(`GET /v1/staff/sessions/{id}`)다(단계 5c와 같다). 이 조회는 survey-service 서버 상태를 읽을 뿐 gateway 경유 직원 계정으로 부르므로 survey-service가 멈춰 있는 동안은 부르지 않는다.

### 지연 측정: 환자 요청의 gateway 마감 (이 PC 대 gpu-dev, 같은 스크립트)

`curl -w`로 잰 값(`time_namelookup`/`time_connect`/`time_starttransfer`/`time_total`; 호스트에서 gateway의 게시 포트로 호출, 상류는 `caddy file-server` 컨테이너를 `docker pause`). 각 3회의 범위, 초 단위. 환경: 이 PC는 Docker Desktop 4.60.1(엔진 29.2.0), gpu-dev는 Docker Desktop 4.50.0(엔진 28.5.1), 둘 다 WSL2.

| 상황 (설정) | 이 PC | gpu-dev |
|---|---|---|
| 정상 상류: lookup / connect | 0.00002 / 0.0001 | 0.00002 / 0.0001 |
| paused, 연결 2s + 헤더 9s (이전 설정): starttransfer = total | 9.00~9.02 | 9.54~9.61 |
| paused, 연결 2s + 헤더 1s | 1.00 | 1.06 |
| paused, 연결 0.3s + 헤더 9s | 8.99~9.02 | 9.55~9.59 |
| paused, 연결 1s + 헤더 8.5s (새 설정) | 8.50~8.52 | 9.02~9.04 |
| 상류 stopped, 연결 2s (이전) → 502 | 2.00 | 2.12 |
| 상류 stopped, 연결 1s (새) → 502 | (미측정) | 1.06 |

읽는 법. 확인한 것: (1) 두 환경 모두 `time_connect`는 0.1ms대라 paused 상류로의 연결 수립에 2초가 걸리지 않는다(paused 컨테이너는 커널이 연결을 받는다). 즉 "연결 2초 + 헤더 9초"가 합쳐지는 일은 이 측정에서 일어나지 않았다. (2) gpu-dev의 Caddy 타이머 결과가 설정값의 약 1.065배로 일정하다(1초 → 1.06, 8.5초 → 9.03, 9초 → 9.57, 연결 2초 → 2.12). 같은 호스트에서 파이썬 `time.sleep(9)` 8회는 모두 9.00이었으므로 호스트 시계 문제는 아니고 Caddy(Go 타이머)·Docker Desktop 4.50 쪽의 일정한 배율로 보였다. **정정**: 아래 "5w 구간별 계측"에서 Caddy의 처리 시간(접근 로그 duration)은 정확했고 초과분은 gateway가 응답을 쓴 뒤 호스트 클라이언트가 받기까지의 구간이었다. (3) 새 설정의 상한은 gpu-dev에서도 9.04초로 키오스크 대기 10초 안이다. 이전 설정은 gpu-dev에서 9.6초였다. 확인하지 못한 것/추정: gpu-dev 전체 E2E에서 5w가 10.9초를 기록했다. 위 측정으로는 재현되지 않았고(paused 측정은 전부 9.61초 이하), 같은 gpu-dev에서 호스트 `sleep 9`가 한 번 10.93초 걸린 관찰이 있었으므로(다른 8회는 9.00) WSL2 VM의 일시 정지·지연으로 약 1.3초가 더해졌을 가능성이 있다. 이는 추정이다. Go의 두 타이머가 순차(연결 뒤 요청을 다 쓴 시점부터 헤더 대기)라는 점은 문서에 근거한 것이고 느린 연결을 만들어 합이 되는 것을 직접 재지는 않았다.

### 5w 구간별 계측: 클라이언트가 본 시간과 gateway 처리 시간의 차이 (gpu-dev)

원인 조사용 임시 계측(커밋하지 않음)을 `~/openit-exp`의 사본에서 `--only 1,2,3,4,5wx`로 돌렸다. 같은 paused 상류에 같은 POST를 보내 클라이언트 측 시간과 gateway 접근 로그의 `duration`을 함께 기록했다(`docker pause` 명령 자체는 0.03~0.06초).

| 방식 (순서대로, 상류 pause 중) | 이 PC 클라이언트 | 이 PC gateway duration | gpu-dev 클라이언트 | gpu-dev gateway duration |
|---|---|---|---|---|
| python http.client | 8.51 | 8.50 | 10.44 | 8.50 |
| curl | 8.51 | 8.51 | 9.03 | 8.50 |
| python http.client | 8.51 | 8.51 | 8.51 | 8.51 |
| curl | 8.51 | 8.50 | 9.04 | 8.50 |
| python urllib(E2E의 `gwk`) | 8.51 | 8.50 | 10.40 | 8.50 |

확인한 것: gateway(Caddy)의 처리 시간은 두 환경 모두 설정값 8.50초로 정확하다. 연결·요청 전송 단계는 0.000초(클라이언트-게시 포트 사이)이고 지연은 응답을 기다리는 구간에 있다. gpu-dev에서만 클라이언트가 gateway보다 0.5초(curl) 또는 1.9초(python, 5회 중 2회)를 더 본다. 즉 초과분은 gateway가 응답을 쓴 뒤 호스트 클라이언트가 받기까지의 구간에서 생긴다. 이전 절의 "gpu-dev에서 Caddy 타이머가 약 1.065배" 해석은 이 계측으로 정정한다: curl로 잰 초과분이 같은 구간의 지연이었고 Caddy의 타이머는 정확했다. 추정(원인 미확인): Docker Desktop 4.50(WSL2)의 호스트 게시 포트 전달 계층이 오래 기다린 응답에 지연을 더한다. 같은 네트워크 안에서 부른 비교는 busybox wget의 재시도 때문에 깨끗하지 않아 결론에 쓰지 않았다. 이 PC(Docker Desktop 4.60.1)에서는 나타나지 않았다.

## 단계 2: 학습 데이터 게시 (synthetic-data 게시기 모드)

`scripts/e2e_steps.py`의 `step2`. synthetic-data가 `python -m synthetic_data import --config <설정>`로 입력 디렉터리의 jsonl 6개(`lora_{a,b}_{train,val,test}.jsonl`)를 v2 스키마로 행 단위 검증하고 건수·sha256을 기록해 게시한다. 이전의 생성 파이프라인 호출(G02: v1 내용이라 전부 제외돼 BLOCKED)은 이 단계에서 쓰지 않는다(단계 7의 시드 데이터셋 생성은 그대로 `run`을 쓴다).

**상태: 배선 REAL, 데이터는 시험용.** 입력 `test/import-v2/*.jsonl` 6개는 데이터셋 담당의 실제 학습 데이터가 **아니다**. 이 E2E를 위해 `test/import-v2/make_rows.py`가 만든 아주 작은 모음(파일당 정상 4행)이고, 행 형식(`human_review`, `scenario_id`, `split`, `messages[system,user,assistant]`)은 synthetic-data 문서의 **추정**을 따랐다. user/assistant 내용은 boundary-contracts v2 스키마(`ActionExtractionInput`/`ActionExtraction`, `ResponseRequest`/`ResponseText`)로 생성 때 직접 검증했고 칸 키는 `test/fake-model/question_flow.json`의 실제 키다. 실제 데이터로 게시한 적은 없다.

확인하는 것: (a) 일부러 넣은 위반 2행(`lora_a_train`의 v2 출력 위반 1, `lora_b_val`의 JSON 아님 1)이 허용 1행을 넘으면 게시하지 않는다(종료 코드 4, `REJECTED`, 저장소에 데이터셋이 생기지 않음). (b) 허용 2행이면 26행 중 24행이 통과해 DatasetManifest가 게시된다(스키마, 파일 해시, 보고서의 입력 sha256·줄 수가 파일과 일치, 분할 TRAIN/VALIDATION/EVAL, 샘플 24개). (c) 같은 입력 재실행은 `ALREADY_PUBLISHED`. 게시된 데이터셋 참조는 `STATE["dataset"]`로 단계 3(모델 패키지 계보)·4가 쓴다.

못 보는 것: 의미 검사(targets, next_item, 건너뛰기 순서, save: 게시기가 아직 하지 않음, synthetic-data CR-006 2번), 실제 데이터 형식, 보지 못한 문항 세트(HELD_OUT) 평가 분리(이전 생성 경로가 확인하던 항목이었으나 이 입력에는 없다).

CR-006의 미해결 항목을 deploy가 정하지 않고 임시로 채운 값: 문항 세트 출처는 단계 1이 만든 문항 세트 참조(id, version, content_hash)를 설정에 넣었고, `turn_engine_version`은 lib.sh의 기준 태그(e2e.sh가 넘기는 값)이며, `source_label`은 `deploy-e2e-test-data`, `generator_version`은 게시기가 정하는 값을 그대로 둔다. 미검수(`human_review: pending`) 행은 만들지 않았다(전부 `auto_only`).

## 단계 5u: 사람이 쓰는 화면 경로의 gateway 상류 상한 (FAULT_MATRIX C7·C8·D6)

`config/Caddyfile`의 `proxy_limits` 조각이 release-gate(승인·운영자 경로), ops-feedback-ingest(검토 경로), admin-console 정적 화면 프록시에 상류 연결 2초와 응답 헤더 상한(release-gate 15초, 나머지 10초), 재시도 없음을 건다. 환자 경로(연결 1초 + 헤더 8.5초)와 달리 키오스크의 10초 한도가 없어 더 길게 잡았고, 값은 **시작값이며 근거는 추정**이다(승인 결정·활성화·롤백이 DB 쓰기와 번들 검증을 거칠 수 있다는 가정, 실측 없음; 사용자 결정 아님). 상류 장애는 환자 경로와 같은 `handle_errors`가 503/504 `{"code":"UPSTREAM_UNAVAILABLE"}`로 바꾼다.

`5u`(`--only 5u`로 단독 실행 가능, 활성 릴리스 불필요): (1) release-gate `docker stop` 중 승인 조회(`GET /v1/submissions`, release-approver 계정)와 운영자 읽기(`GET /v1/active-pointer`)가 503 JSON(4초 미만; 이 PC 관찰 3.5~3.8초), 시작 뒤 200 복구. (2) release-gate `docker pause` 중 승인 조회가 504 JSON이고 gateway 접근 로그 duration이 14.5~16초(관찰 15.0초). (3) ops-feedback-ingest `docker pause` 중 검토 목록(`GET /v1/cases`, reviewer 계정)이 504 JSON, duration 9.5~11초(관찰 10.87초: 설정 10초에 기본 인증 확인 시간 약 0.9초가 더해진다). 시험하지 않은 것: POST(결정·활성화·롤백) 경로의 상한 동작, admin-console·kiosk-frontend 정적 프록시(같은 조각이나 직접 확인 안 함).

## 단계 5m: model-serving 무응답 중 환자 턴 (FAULT_MATRIX B1)

`scripts/e2e_steps.py`의 `5m`(단독: `--only 1,2,3,4,5m`). model-serving을 `docker pause`한 동안 gateway 경유 환자 턴이 survey 턴 마감(6초) 안에 분류된 실패로 끝나는지(gateway 접근 로그 duration 6.5초 미만; 이 PC 관찰 4.03초 = survey의 model-serving 읽기 timeout 4초), 값이 저장되지 않는지(이전 값 유지, 그 칸 없음), `unpause` 뒤 서비스가 복구되어 새 `turn_id`로 값이 한 번 저장되는지 본다. 같은 단계가 실제 스택에서 model-serving `/readyz` 200과 release-gate 판정 루프(`judging_loop`)의 정상 값을 직접 읽는지도 확인한다(이 PC에서 확인).

관찰과 정책 단언: 실패 응답은 `200` + `turn_failure_signal`(`NOT_COMMITTED`)이고, 실패한 턴의 발화는 대화 기록에 남는다(값은 저장되지 않음). 이 턴을 **같은 `turn_id`로 재전송**하면 model-serving이 돌아온 뒤에도 같은 실패 응답이 계속 온다(20회, 약 60초). FAULT_POLICY 원칙 1·2의 기대(NOT_COMMITTED 턴의 재전송은 확정)와 달라서 정책 단언 `POLICY-PENDING`으로 두었다. 기다리는 변경: survey-service([CR-D25](change-requests/CR-D25-survey-notcommitted-turn-id-replay.md)).

**model-runtime 요청 상한 코드가 이 E2E 이미지에 들어 있는가: 아니다(확인).** 가짜 모델 서버 이미지(`model-serving`)는 `DEPLOY_MR_TAG`(값은 `scripts/lib.sh`) 시점의 소스로 빌드된다. model-runtime 73e79f9(`MODEL_RUNTIME_REQUEST_DEADLINE_S` 3.5초, 엔진 멈춤·사망 시 `/readyz` 503, `ENGINE_TIMEOUT`)는 확인 당시의 기준 태그에 없었다(`git grep REQUEST_DEADLINE v0.7.2`가 0건, 이후 커밋에만 있고 그것을 포함하는 태그가 없다). 그래서 위 5m의 4.03초는 서버 상한이 아니라 survey의 읽기 timeout이다. model-runtime이 새 태그를 내면 `scripts/lib.sh`의 `DEPLOY_MR_TAG`(와 영역 문서의 기준 표기)를 올려야 이 코드가 E2E에 들어온다. 엔진 멈춤 시 `/readyz` 503은 `pause`로는 볼 수 없다(컨테이너가 통째로 얼어 `/readyz`도 응답하지 못한다): 그것을 보려면 가짜 백엔드에 지연·고장을 주입하는 방법이 model-runtime 쪽에 있어야 하며 지금은 확인하지 못했다.

## 영역 하나가 바뀌었을 때: verify-area (전체 합격이 아니다)

`bash scripts/verify-area.sh <영역>`은 영역 자체 시험, `check-all`, 그 영역과 연결된 E2E 단계 묶음(`e2e.sh --only`, 선행 단계 포함)을 돌린다. 영역→단계 대응과 각 단계가 보는 호출 경계는 `config/verify-areas.yaml`이 정본이고 `--list`로 본다. 낡은 이미지(소스 커밋 또는 의존 태그가 다른 것)만 다시 빌드한다. 영역 내부만 바뀌었으면 `--no-e2e <이유>`(이유 필수)로 E2E를 건너뛴다. 커밋 안 된 변경이 있으면 E2E를 거부한다(이미지는 `git archive HEAD`). 결정 근거: [ADR 0014](adr/0014-verify-area-and-fast-feedback.md). 완료 선언은 여전히 옵션 없는 전체 E2E 기준이다. 자체 시험: `python3 scripts/test_verify_area.py`(Docker 불필요).
