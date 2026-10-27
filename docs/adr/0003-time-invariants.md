# 0003. 시간 불변식 체인: 키오스크 10s > gateway 9.5s > survey 턴 마감 6s > survey의 model-serving 읽기 4s > model-runtime 요청 상한 3.5s

- 상태: 채택(값은 초기값, 측정 안 함)
- 날짜: 2026-10-28

## 맥락

환자 턴은 키오스크 → gateway → survey-service → model-serving(extract, respond) 순으로 지나고, 각 단계가 자기 아래 단계보다 오래 기다려야 아래 단계의 분류된 실패 응답이 위에서 소켓 timeout으로 바뀌지 않는다(FAULT_POLICY 3·4).

## 결정

값: 키오스크 대기 10초(kiosk-frontend 영역), gateway 연결 1초 + 응답 헤더 8.5초 = 합 9.5초 상한(`config/Caddyfile`, 두 타이머는 순차라 합이 상한), survey 서버 턴 마감 6초(`SURVEY_TURN_DEADLINE_SECONDS`), survey의 model-serving 읽기 timeout 4초, model-runtime 요청 상한 3.5초(`MODEL_RUNTIME_REQUEST_DEADLINE_S`). 사람이 쓰는 화면 경로는 키오스크 한도가 없어 연결 2초 + 헤더 10~15초.

## 왜 (따른 표준과 근거)

- 표준 관행: 호출 체인에서 바깥 timeout > 안쪽 timeout(데드라인 전파 원칙), 재시도는 가장 바깥에서만(gateway는 재시도하지 않는다, `lb_try_duration 0`). 출처: head/docs/FAULT_POLICY.md 원칙 3·4·6·7.
- gateway 9.5초는 E2E 5w가 gateway 접근 로그 duration으로 재서 설정과 같음(8.5초 + 인증)을 확인했다. 클라이언트 측 지연은 Docker Desktop 환경에서 +0.5~1.9초 더해질 수 있어 별도 정책 단언이다(docs/E2E.md).
- **실제 모델 지연으로 측정한 값이 아니다**: 3.5초와 6초 등은 가짜 백엔드·1.7B 중앙값 약 1.7초에서 나온 초기값이다. H1(24GB 실측)에서 `scripts/probe-serving.py` 표로 재정한다(docs/GPU_HOLE.md H1).

## 검토한 대안과 버리는 이유

- 모든 timeout을 크게 한 값: 장애 때 환자 화면이 오래 멈춘다. 버린다.
- gateway가 재시도: 같은 요청이 두 번 처리될 수 있어 멱등이 서비스 몫이 되는 위험을 gateway에서 키운다. 키오스크가 같은 `turn_id`로 재시도하는 쪽을 택했다.

## 결과

- 값이 서로 다른 리포(kiosk-frontend, survey-service, model-runtime, deploy)에 있어 어긋날 위험이 있다(FAULT_MATRIX N21). E2E 5w·5m·5p가 일부를 대조한다.
- 실모델이 3.5초를 넘으면 `ENGINE_TIMEOUT`이 난다: 재정 대상.

## 되돌리는 조건

H1 실측에서 extract 또는 respond의 p95가 요청 상한(3.5초)을 넘거나 survey 턴 마감(6초) 안에 두 호출이 들지 않으면 체인의 값을 위에서 아래로 다시 정한다.
