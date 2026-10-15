# CR-D04: synthetic-data, model-lab 주기 잡 정보

- 상태: 정보 요청
- 보내는 곳: deploy -> head (영향: synthetic-data, model-lab)

## 확인한 것

deploy는 네 서비스 영역의 문서만 읽을 수 있어 synthetic-data와 model-lab의 `run-once` 명령, 설정 파일, 필요한 이웃 접근(I1, I7, I2)을 알 수 없다. 둘 다 GPU가 필요한 일(LLM 생성, 학습)을 포함하므로 D40에 따라 서빙 서버 밖 GPU 서버에서 돈다고 보고 `config/jobs.yaml`에 `where: gpu-external`로 자리만 두었다. Compose에는 넣지 않았다. E2E 단계 2, 3(실제 파이프라인), 7이 이 때문에 BLOCKED다. 단계 3은 시험용 어댑터와 model-runtime FakeBackend로 대신했고 그 사실을 표시했다.

## 요청

두 영역이 각자 `docs/runbook.md`에 (1) 한 번 실행하는 명령, (2) 설정 파일 형식, (3) 필요한 환경 변수와 토큰, (4) 어디서(서빙 서버/GPU 서버) 돌리는지를 쓰고, GPU 서버에서 이웃 읽기(I1 문항, I7 실패 사례, I2/I3 게시)를 어떻게 하는지(CR-D01의 원격 클라이언트) 정한다. 그러면 deploy가 GPU 서버용 잡 호출 스크립트(서빙 서버 밖) 자리를 채운다. GPU 서버의 위치·접속 방법은 사용자 결정이다.
