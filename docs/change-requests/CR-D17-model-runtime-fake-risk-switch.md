# CR-D17: model-runtime fake 백엔드에 위험 신호 시험용 스위치, 그 밖의 배포 항목

- 상태: 제안
- 보내는 곳: deploy -> head -> model-runtime

## 1. 위험 정지 -> 직원 개입 시나리오를 시험할 수 없다

공개 API의 직원 개입(`POST /v1/sessions/{id}/intervention`, 역할 staff)은 위험 신호로 멈춘 세션에서만 의미가 있다(멈추지 않은 세션은 409). E2E는 키오스크 토큰 403과 "멈추지 않은 세션 409"까지만 확인한다. 세션을 위험으로 멈추려면 파서가 위험 신호 항목을 내야 하는데, fake 백엔드의 출력은 고정이다(파서 `{"items": []}`, 생성기 "(가짜 응답)").

요청: fake 백엔드가 **입력 발화에 특정 문구가 있으면 위험 신호를 내는 시험용 스위치**(예: 발화에 `TEST-RISK`가 있으면 위험 의도 항목)를 갖게 한다. 시험 전용임이 이름에 드러나야 하고(`test`), 운영 백엔드(vllm)에는 없어야 한다. 그러면 E2E에 "위험 발화 -> 세션 정지 -> 직원 토큰 RESUME/END -> 키오스크 턴 재개"를 추가한다.

## 2. fake 번들 조건의 확인 방법

`serving_config.constraint`의 `supported_features` 목록 값이 fake와 일치해야 PUT 적재가 된다는 조건을 받았다. deploy는 survey-service 이미지의 `model_runtime.fake_serving_configs()`(v0.5.0)로 만든 설정을 그대로 쓰는데 이것이 맞는 기대값인지 문서에 한 줄로 밝혀 주면 좋다(E2E는 PUT 적재 성공으로만 확인한다).

## 3. 이미지 구성

- 이미지에 문진 스키마가 없어 `MODEL_RUNTIME_SCHEMA_DIR`을 읽기 전용 마운트로 받는다. deploy는 survey-service 사본의 `schema/`를 `build/survey-schema`에 풀어 마운트한다. 문진 스키마 패키지(`openit-survey-schema`)를 이미지에 포함하거나 라벨로 버전을 밝히면 마운트가 필요 없다.
- `--build-context boundary=<폴더>`는 태그 시점 소스를 요구한다. deploy는 `git archive v1.3.1`로 풀었다. CI용 태그 설치 경로를 런북에 쓰면 deploy가 따른다.
- 이미지의 `/data`(번들 캐시 볼륨)가 앱 사용자(uid 10001) 소유가 아니라 새 named volume에서 `PUT /v1/releases/{id}`가 `PermissionError`(503 UNAVAILABLE)로 실패했다. deploy는 일회성 `model-serving-init`(chown)으로 우회했다. 이미지가 `/data`를 만들고 소유자를 지정하면 필요 없다.
