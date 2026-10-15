# CR-D12: model-lab을 E2E에 잇는 데 필요한 것 (E2E_GPU=1 경로)

- 상태: 정보 요청
- 보내는 곳: deploy -> head (영향: model-lab, synthetic-data)

## 확인한 것

- model-lab의 gpu-dev 설정(`configs/gpu-dev-http-publish.yaml`)은 데이터셋을 `tests.doubles.dataset_store:from_dir`(model-lab 자체 시험 자료 `fixtures/store`)로 읽는다. 운영용 파일 저장소(synthetic-data가 `<root>/<dataset_id>/<version>/`에 낸 것을 읽는 `FileDatasetStore`)를 설정에서 고르는 팩토리 이름이 런북에 없다. 그래서 `scripts/e2e_gpu.sh`(미검증)가 단계 2의 산출물을 학습에 쓰지 못한다.
- synthetic-data(호스트)와 model-lab(gpu-dev)은 서로 다른 호스트일 수 있어 데이터셋 저장소를 어떻게 옮기는지(rsync인지 공유 디스크인지)가 정해지지 않았다(D40).
- 레지스트리 접속: gpu-dev에서 서빙 서버의 model-registry에 닿는 길(공개 포트, SSH 역터널)이 정해지지 않았다. e2e_gpu.sh는 역터널을 가정했다. 운영에서는 model-registry를 어떤 네트워크 경계로 GPU 서버에 열지 사용자 결정이 필요하다(현재 Compose에서 model-registry는 내부 `release` 네트워크뿐이다).

## 요청

(1) 파일 저장소 팩토리 이름과 인자를 런북에 쓴다. (2) 데이터셋 이동 방식과 GPU 서버의 레지스트리 접속 방식을 헤드와 사용자가 정한다.
