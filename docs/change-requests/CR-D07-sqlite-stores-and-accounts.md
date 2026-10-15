# CR-D07: 저장소가 모두 SQLite라 "저장소별 DB 계정·읽기 전용 계정"을 DB로 만들 수 없다

- 상태: 확인 요청(deploy의 대체안 제안)
- 보내는 곳: deploy -> head (영향: 전 영역, O10)

## 확인한 것

브리프: "저장소마다 데이터베이스와 계정이 나뉘고, 다른 영역에는 읽기 전용 계정만 준다. 기본값은 DB 인스턴스 하나."  영역 문서 확인: survey-service(SQLite 두 개), question-authoring(SQLite), ops-feedback(`log.db`, `failures.db`), release-gate(SQLite + `releases/`). DB 서버가 없고 계정 개념이 없다.

## deploy의 대체안(구현함)

- 저장소마다 볼륨 하나, 쓰기 마운트는 소유 서비스만. 이웃은 HTTP와 영역별 토큰.
- 읽기 전용 마운트 공유는 쓰지 않았다. 시험에서 확인한 이유: WAL 모드 SQLite는 읽기 전용 마운트에서 `-shm`을 만들지 못하면 열리지 않는다(백업이 처음에 `unable to open database file`로 실패해 쓰기 가능 마운트+읽기 전용 연결로 바꿨다). 소비자가 읽기 전용 마운트로 열려면 각 영역이 WAL 사용 여부와 `immutable` 읽기 가능성을 밝혀야 한다.

## 요청

(1) 위 대체안으로 충분한지 확인한다. DB 서버(예: PostgreSQL)가 필요하다고 판단하면 각 영역에 알려야 하고, deploy는 `compose.dev.yaml`이 아닌 운영 Compose에 DB 서비스를 더한다. (2) 영역이 SQLite의 저널 모드(WAL 여부)를 문서에 밝히게 한다.
