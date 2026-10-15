# 변경 이력

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
