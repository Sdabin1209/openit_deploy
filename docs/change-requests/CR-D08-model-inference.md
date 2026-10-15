# CR-D08: 모델 추론(GPU)의 위치와 survey-service의 실제 백엔드

- 상태: 정보 요청
- 보내는 곳: deploy -> head (영향: survey-service, model-runtime)

## 확인한 것

- 브리프의 서비스 시드에는 `inference(GPU)`가 있다. survey-service 런북은 `SURVEY_MODEL_BACKEND`의 값이 지금 `fake`(개발·스모크 전용)뿐이고 실제 백엔드는 model-runtime에 아직 없다고 한다. `/readyz`가 `model_backend_production_safe: false`를 낸다.
- 그래서 이 Compose에는 inference 서비스가 없고 survey-service는 `fake`로만 뜬다. 실제 서빙에서는 survey-service 프로세스 안에서 로컬 추론을 할지, 별도 inference 서비스(GPU 할당)를 둘지 정해지지 않았다.

## 요청

model-runtime의 실제 백엔드 배포 형태(서비스 분리 여부, 이미지, GPU 접근, 환경 변수)를 정해 알려 준다. deploy는 그에 맞춰 GPU 할당(`deploy.resources.reservations.devices`)과 서빙 네트워크 배치를 정한다. 그 전에는 운영 `compose.yaml`의 survey-service가 `SURVEY_MODEL_BACKEND=fake`로 뜨는 것을 막을 방법이 없다(이 값을 운영에서 거부하는 책임은 survey-service에 있다).
