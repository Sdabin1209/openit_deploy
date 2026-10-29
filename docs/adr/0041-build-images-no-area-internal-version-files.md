# 0041. build-images는 영역의 내부 버전 파일을 읽지 않는다

- 상태: 채택
- 날짜: 2026-10-29

## 맥락

`build-images.sh`가 이웃 영역의 내부 파일 둘을 직접 읽었다: model-runtime의 `pyproject.toml`(`project.version`, 라벨 `io.openit.model-runtime` 값)과 kiosk-frontend의 `package.json`(`version`, 라벨 `io.openit.app-version` 값). 구조 규칙(영역은 서로의 구조를 모른다, 영역 사이는 스키마와 산출물로만 만난다)에 어긋난다. 앞서 survey-schema 라벨은 같은 이유로 영역이 내는 산출물(`build/wheels/SURVEY_SCHEMA_VERSION`)에서 읽도록 바꿨다(커밋 d8a3301).

> **갱신(U42, 커밋 이 ADR 다음)**: `build-images.sh`는 이제 영역 빌드 구조를 전혀 모른다(계약 BuildImageRequest/Result, 영역 `scripts/build-image.sh`만 부른다). model-runtime 라벨은 요청의 `versions.model_runtime`(기준표)을 영역이 라벨로 쓰고, `verify_mr_label`(이미지 안에서 `model_runtime.RUNTIME_VERSION`을 실행)은 영역 내부 모듈 이름을 아는 일이라 없앴다. 라벨-표 일치는 `check-versions.sh`(ADR 0042)가 본다. 아래 본문은 당시 결정의 기록이다.

## 결정

- **model-runtime 라벨**: deploy 자신의 기준표 `DEPLOY_MR_TAG`(lib.sh)에서 만든다(`v` 접두사 포함). deploy는 model-serving 이미지를 그 태그의 소스(`git archive $MR`)로 빌드하므로 라벨의 버전은 deploy가 이미 아는 사실이다. 빌드한 이미지가 정말 그 버전인지는 **이미지가 스스로 내는 `model_runtime.RUNTIME_VERSION`**(영역이 내는 공개 산출물)을 실행해 비교하고 다르면 빌드를 멈춘다(`verify_mr_label`).
- **kiosk-frontend `app-version` 라벨**: deploy가 값을 넘기지 않는다. 영역 Dockerfile의 `ARG APP_VERSION` 기본값을 쓴다. 이 값을 `package.json`에서 정하는 일은 영역 빌드 안의 몫이다(변경 요청 CR-D29).

## 왜

- (b) deploy 기준표를 택한 이유: model-runtime 버전은 이미 deploy의 열차 표(계약, model-runtime, survey-schema 태그)에 있는 값이다. 같은 사실을 영역 파일에서 다시 읽으면 두 곳이 어긋날 수 있다. 어긋남은 이미지 자체의 `RUNTIME_VERSION`과 대조해 잡는다(영역의 내부 파일 구조가 아니라 영역이 내는 값).
- (a) 영역 산출물(이미지 라벨)을 택하지 못한 곳: model-runtime Dockerfile의 라벨은 빌드 인자 `MODEL_RUNTIME_VERSION`이 비면 빌드를 실패시킨다(D50 규칙). 즉 라벨은 빌더가 넘겨야 하는 값이라 읽어 올 산출물이 아직 없다. wheel 메타데이터는 model-serving 이미지 빌드에 wheel을 만들지 않으므로 쓸 수 없다.
- kiosk의 앱 버전은 deploy의 사실이 아니라 영역의 사실이다. 그래서 deploy가 대신 정하지 않고 영역 기본값에 맡긴다.

## 검토한 대안과 버리는 이유

- 영역 파일을 계속 읽기: 구조 규칙 위반이고, 파일 형식·경로가 바뀌면 deploy가 깨진다.
- 라벨 값 없이 빌드: model-runtime Dockerfile이 거부한다(D50).
- 영역이 `scripts/print-version` 같은 인터페이스를 내게 하기: 영역 변경이 필요하고 model-runtime은 이미 `RUNTIME_VERSION`을 이미지에 내고 있어 충분하다.

## 결과와 한계

- 얻는 것: `build-images.sh`가 영역 소스 트리의 버전 파일을 읽지 않는다(`scripts/test-build-images-static.sh`가 `pyproject.toml`, `package.json`, `tomllib`, 옛 `mr_version`, `APP_VERSION` 전달이 없음을 확인한다. 수정 전에는 5건 실패).
- 감수: 기준표 태그와 영역의 `RUNTIME_VERSION`이 어긋나면 빌드가 멈춘다(의도). 이미지를 실행해야 해서 model-serving 빌드마다 컨테이너 한 번을 더 띄운다(약 1초, 측정 안 함). GPU 이미지도 같은 확인을 한다. kiosk의 app-version 라벨은 영역 기본값이 package.json과 어긋나도 deploy가 잡지 못한다(영역 몫).

## 되돌리는 조건

영역이 버전을 빌드 산출물 파일(예: `build/VERSION`)로 내기 시작하면(a)로 바꾸고 이 ADR을 대체한다.
