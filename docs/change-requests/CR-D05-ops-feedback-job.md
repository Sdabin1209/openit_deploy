# CR-D05: ops-feedback 잡 설정과 실행 환경

- 상태: 정보 요청
- 보내는 곳: deploy -> head (영향: ops-feedback)

## 확인한 것

- 런북: `OPS_DEID_SALT=... python -m ops_feedback.job --config config/job.yaml`. 예시는 리포지토리의 `config/job.example.yaml`(이미지에는 없고 deploy가 읽을 수 없는 범위)다. 비식별 기준(`deid.*`), 보관 기간, 분류체계(O11), 롤백 기준은 사용자 결정으로 되어 있다.
- 잡이 쓰는 저장소 경로(`log.db`와 `failures.db`)와 롤백 평가에 쓰는 `release_reader`·게이트 호출(I4, I5) 설정을 deploy가 알 수 없다. ingest-api의 `OPS_LOG_DB=/data/log.db`만 확인했다.
- deploy는 `job-ops-feedback`(프로필 `jobs`)을 ingest-api와 같은 이미지·같은 `ops-data` 볼륨·`logs`+`release` 네트워크로 정의했고, `python -m ops_feedback.job --help`가 Compose 안에서 도는 것까지 확인했다. 실제 실행은 설정 파일이 없어 거부한다(`run-job.sh`, 종료 코드 2).
- E2E 단계 6b(FailureCase 생성), 7이 이 때문에 BLOCKED다.

## 요청

(1) 이미지 안에 배포용 예시 설정 또는 형식 문서(런북)를 둔다. (2) 잡의 저장소 경로를 환경 변수로 받는지 설정 파일로 받는지, 게이트 호출에 쓰는 토큰의 환경 변수 이름(CR-D01의 클라이언트와 함께)을 밝힌다. (3) 잡이 `log.db`를 읽고 `failures.db`를 쓰므로 ingest-api와 볼륨을 공유하는 현재 구성(`ops-data`)이 맞는지 확인한다. 비식별 기준·분류체계는 사용자 결정 뒤에 설정 파일에 적는다(deploy가 정하지 않는다).
