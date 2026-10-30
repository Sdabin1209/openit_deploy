# 변경 요청 (deploy -> 헤드): 진짜 어댑터를 모델 패키지로 만드는 일의 정본을 model-runtime SDK 로

- 현재: `openit_deploy/wiring/cli_llm_attach_package.py` (구 `scripts/llm_attach_package.py`)가 매니페스트의 serving_config 를 만들려고 `model_runtime`(PYTHONPATH 로 이웃 소스)의 `load_profile`, `fake_serving_config`, `DEFAULT_SUPPORTED_FEATURES`, `SUPPORTED_RUNTIME_CONTRACT_VERSION`, `RUNTIME_VERSION` 을 import 한다. 구조 규칙 1(영역은 서로의 구조를 모른다)과 공통 규칙(영역 리포끼리 코드를 가져오지 않는다)에 어긋난다. 이번 구조 개편은 동작을 바꾸지 않는 이동이라 그대로 두었다.
- 제안: model-runtime 이 "받은 어댑터 + 프로파일 + 프롬프트 -> 모델 패키지(ModelPackageManifest 포함)"를 만드는 일을 자기 CLI 또는 SDK 로 제공한다. deploy 는 `adapter_check` 로 판정한 뒤 그것을 부르기만 한다(`make_neutral_package.py` 와 같은 자리).
