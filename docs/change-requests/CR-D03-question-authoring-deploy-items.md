# CR-D03: question-authoring 배포 항목

- 상태: 제안
- 보내는 곳: deploy -> head (영향: question-authoring)

## 확인한 것

1. 이미지에 `HEALTHCHECK`가 없다(다른 세 영역에는 있다). deploy는 Compose에서 대신 지정했다(영향 없음, 그러나 `docker run` 단독 사용 시 없음).
2. `Dockerfile`이 `build/survey-schema`(CONTRACT_VERSION, schemas)를 복사하는데 `scripts/build_contract_wheel.sh`도 `scripts/smoke.sh`도 이것을 만들지 않는다. 오래된 `build/`가 있는 작업 폴더에서만 스모크가 되고, `git archive HEAD`로 새로 꺼낸 사본에서는 빌드가 실패한다. deploy는 사본의 `../survey-service/schema`에서 만들어 넣었다(`scripts/build-images.sh`).
3. I1 읽기는 SQLite SDK뿐이고 HTTP 읽기 면이 없다(CR-D01).
4. 토큰이 `QA_AUTHOR_TOKENS`(토큰:actor-id:역할) 하나다. 읽기 전용 역할 토큰이 필요한 소비자(게이트 수집기, 합성 데이터, model-lab)를 위한 읽기 면이 없어 구분할 수 없다.
5. `pipeline_schema_version` 1.0(boundary-contracts v1.0.0)을 쓴다. survey-service·ops-feedback은 v1.1.0이다(CR-D06).

## 요청

- (1) `HEALTHCHECK` 추가. (2) 이미지에 필요한 스키마를 빌드 스크립트가 만들도록(`build/survey-schema` 생성 단계) 하고, 가능하면 survey-service가 배포하는 `openit-survey-schema` 패키지로 대체. (3)(4)는 CR-D01의 읽기 면 결정에 따른다.
