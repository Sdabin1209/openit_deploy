# CR-D14: 첫 구간 변경 요청의 현재 상태와 이번에 새로 어긋난 것

- 상태: 정리

| CR | 이번 구간 상태 |
| --- | --- |
| D01 클라이언트 패키징 | 해결: `boundary_contracts.clients`(v1.2.0)와 서버 읽기 면. 모든 연결이 HTTP로 이어졌다(E2E 확인) |
| D02 게이트 항목 | 읽기 토큰 분리(`GATE_READ_TOKENS`), 수집기 run-once, 버전 자동 읽기 해결. 수집기 role 확인은 D13 |
| D03 question-authoring | HEALTHCHECK, 라벨, 스키마 wheel, 읽기 면(`QA_READ_TOKENS`) 해결 |
| D04 synthetic-data·model-lab | synthetic-data는 호스트에서 실제 실행됨. model-lab은 model-registry만 연결, 파이프라인은 D12 |
| D05 ops-feedback 잡 | 해결: 런북에 설정 키가 있고 잡이 컨테이너에서 돈다(시험용 설정). 운영 설정 값은 사용자 결정 |
| D06 라벨·태그 | 라벨 6개 통일됨(E2E가 5개 이미지 모두 확인). 경계 계약 태그는 survey/qa/ops/model-registry v1.2.0, release-gate 이미지도 v1.2.0. 단 게이트가 내는 레코드의 `pipeline_schema_version`이 "1.0"으로 남아 있다(접수 응답에서 관찰) |
| D07 SQLite | 그대로. model-registry도 파일 저장소 |
| D08 추론 | 그대로. 이번 구간에도 survey는 `fake` 백엔드 |

## 이번에 새로 어긋난 것

- model-lab `Dockerfile`: 기본 빌드가 `--ssh`와 git을 요구한다(`BC_SPEC` git+ssh). deploy는 `--build-context wheels=`와 `BC_SPEC=/wheels/…whl`로 우회했다(스모크 스크립트가 쓰는 방식). deploy가 쓰는 빌드 명령을 런북에 쓰면 좋다.
- release-gate `scripts/build_image.sh`: 컨텍스트 경로를 항상 `wslpath -w`로 바꿔 `docker`(리눅스 CLI)와 함께 쓰면 실패한다. deploy는 `DOCKER=docker.exe`로 부른다.
- survey-service: 공개 API가 없어 서비스가 Trace를 낼 수 없고, 개발용 CLI는 릴리스 로더를 거치지 않는다. 그래서 5단계의 "새 세션부터 새 릴리스"는 `/readyz`의 `active_release` 전환으로만 확인된다(O06 대기).
