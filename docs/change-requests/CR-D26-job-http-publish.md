# CR-D26: synthetic-data 잡이 dataset-store(I2 HTTP)로 게시할 수 있게 한다

- 상태: **구현됨**(synthetic-data b850f95, `output.store.kind: http`, ADR 0013). 토큰은 잡 쪽 `<token_env>_FILE`(기본 `DATASET_STORE_WRITE_TOKEN_FILE`, 단수). deploy 쪽: E2E 단계 7d 가 호스트에서 import 잡을 `kind: http` 로 돌려 확인한다(이 PC 에서 단독 실행으로 통과, 잡 실행 환경에 boundary-contracts v2.1.0 이 있을 때만 잡 경유, 없으면 tar 직접 게시로 대신하고 기록에 남긴다). `run`(시드) 모드의 HTTP 게시는 확인하지 않았다.

- 요청자: deploy. 대상: synthetic-data(헤드 경유). 날짜: 2026-10-28.
- 확인한 것: `synthetic-data/synthetic_data/config.py` 는 `output.store.kind` 로 `file`, `memory` 만 받는다(`kind not in ("file", "memory")` 는 설정 오류). 서버(dataset-store)는 완성됐고 deploy 스택에 올렸지만, 잡(import·run)은 파일 저장소에 쓰므로 서버의 쓰기 경로(HTTP 게시)를 쓰지 못한다. `docs/runbook.md` 도 파일 저장소를 같은 호스트에서 model-lab 이 `FileDatasetStore` 로 읽는 방식을 적는다.
- 요청: `output.store` 에 `{"kind": "http", "base_url": ..., "token_env" 또는 token 파일 경로}` 를 더해 `HttpDatasetStore.publish`(boundary-contracts v2.1.0)로 게시하게 한다. 토큰은 `NAME_FILE`(D84)로 읽는다. 쓰기 토큰 파일은 deploy 의 `secrets/tokens/dataset-store-write-synthetic-data`.
- deploy 쪽: E2E 단계 7d 는 단계 2 가 파일 저장소에 만든 데이터셋을 tar 로 만들어 HTTP 로 게시해 서버 쪽을 확인한다. 잡 자체가 HTTP 로 게시하는 경로는 이 CR 이 반영된 뒤에 단계 2 설정을 바꿔 확인한다(미확인).
- model-lab: 읽기 구성(`inputs.dataset_store.factory`)을 `boundary_contracts.clients:HttpDatasetStore` 로 하는 것은 model-lab 영역의 구성이다. deploy 의 `config/` 에는 model-lab 구성이 없다(확인: deploy 안에 model-lab 설정 파일 없음).
