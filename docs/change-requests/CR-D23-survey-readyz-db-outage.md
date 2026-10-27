# CR-D23: survey-service /readyz가 PostgreSQL 중지 중에 503으로 답하지 않고 연결을 끊는다

- 상태: survey-service가 수정함(d8f4243, 4d78b3e). deploy E2E 5p로 확인: 같은 시험에서 survey-service /readyz가 postgres 중지 16초 뒤 503(`problems`: session_db, outbox_db, alert_db)으로 답하고, 기동 뒤 7초에 200으로 복구됐다. 아래는 수정 전 관찰의 기록 (영향: survey-service의 /readyz 응답 시간과 형태)
- 확인(관찰): E2E 단계 5p(`bash scripts/e2e.sh --only 1,2,3,4,5p`, 이 PC)에서 postgres 컨테이너를 `docker stop`한 뒤 각 서비스의 `/readyz`를 1초 간격으로 불렀다. question-authoring, release-gate, ops-feedback-ingest는 중지 4~18초 안에 503과 본문(`not-ready`, `PostgreSQL에 연결할 수 없다`, `UNAVAILABLE`)으로 답했다. survey-service는 503을 돌려주지 않았고 요청이 오래 걸린 끝에 `RemoteDisconnected`(연결 끊김, 시험 스크립트 기준 중지 37초 뒤)로 끝났다. `/healthz`는 중지 중에도 200이었다. postgres를 다시 띄우면 약 7초 안에 `/readyz`가 200으로 돌아왔고 이전 데이터(행 지문)도 그대로였다.
- 확인하지 않은 것: survey-service 안에서 어느 호출이 막히는지(접속 대기 시간 설정, 요청 처리 스레드 수 등). deploy는 그 코드를 읽지 않는다.
- 영향: 로드 밸런서나 감시가 `/readyz`의 503을 신호로 쓰면, survey-service는 DB가 없을 때 "준비 안 됨"을 빠르게 알리지 못하고 시간 초과·연결 끊김으로만 드러난다. 회복은 정상이다.
- 요청(survey-service): DB가 없을 때 `/readyz`가 제한 시간(예: 수 초) 안에 503과 원인 코드(접속 문자열 없이)로 답하게 한다. 다른 세 서비스와 같은 모양이면 deploy의 E2E 단계 5p가 그대로 확인한다.
