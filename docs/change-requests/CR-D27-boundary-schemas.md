# CR-D27: 영역 경계를 넘는 형식 여섯 개의 스키마 초안 (이미지 라벨, 게시, 빌드 진입점, 게이트웨이 노출, setup-env, 잡 선언)

- 상태: 제안 (초안. 영역 코드는 아직 이 스키마를 쓰지 않는다. 헤드가 계약에 올린 뒤의 다음 단계다)
- 보내는 곳: deploy -> head (영향: 모든 서비스 영역, 계약 패키지)
- 근거: 점검 보고서 `docs/audit/structure-rules-2026-10-28.md`의 DP-31(E 목록 1~4, 12, 13, 17 등)과 3절 표, 규칙 R6(영역 사이의 스키마는 헤드가 책임진다).
- 위치: 스키마 `docs/change-requests/schemas/*.schema.json`, 예시 `docs/change-requests/schemas/examples/`, 검증기 `docs/change-requests/schemas/validate.py`. JSON Schema 2020-12.
- 표시: 확인한 것(코드·실제 이미지에서 가져온 값)과 제안(아직 없는 인터페이스)을 구분한다. 제안은 "[제안]"이다.

## 검증 (재현 명령과 출력)

```
cd deploy && .venv/bin/python docs/change-requests/schemas/validate.py
PASS build-image-request.invalid.json: 거부 2건 [revision: pattern; versions: required] (기대: 거부)
PASS build-image-request.valid.json: 통과 (기대: 통과)
PASS build-image-result.invalid.json: 거부 1건 [labels: required] (기대: 거부)
PASS build-image-result.valid.json: 통과 (기대: 통과)
PASS exposure.invalid.json: 거부 1건 [routes/0/auth: required] (기대: 거부)
PASS exposure.valid.json: 통과 (기대: 통과)
PASS image-labels.invalid-2.json: 거부 3건 [io.openit.contracts.survey-schema: pattern; io.openit.turn-engine: pattern; io.openit.model-runtime: pattern] (기대: 거부)
PASS image-labels.invalid-bad-jobs-content.json: 거부 1건 [io.openit.jobs/jobs/0/idempotent: const] (기대: 거부)
PASS image-labels.invalid-typo.json: 거부 2건 [(최상위): required; (최상위): not] (기대: 거부)
PASS image-labels.invalid.json: 거부 1건 [io.openit.model-runtime: pattern] (기대: 거부)
PASS image-labels.valid-with-declarations.json: 통과 (기대: 통과)
PASS image-labels.valid.json: 통과 (기대: 통과)
PASS jobs-declaration.invalid.json: 거부 1건 [jobs/0/idempotent: const] (기대: 거부)
PASS jobs-declaration.valid.json: 통과 (기대: 통과)
PASS publish-request.invalid.json: 거부 1건 [service: enum] (기대: 거부)
PASS publish-request.valid.json: 통과 (기대: 통과)
PASS publish-result.invalid.json: 거부 1건 [(최상위): not] (기대: 거부)
PASS publish-result.valid.json: 통과 (기대: 통과)
PASS setup-env-report.invalid.json: 거부 1건 [status: enum] (기대: 거부)
PASS setup-env-report.valid.json: 통과 (기대: 통과)
스키마 8개, 예시 파일 20개, 어긋남 0건
```

(`.venv/bin/python`은 `jsonschema` 4.26.0과 `referencing`이 있는 deploy 가상환경이다. deploy에는 `scripts/setup-env.sh`가 아직 없어 `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`로 만든다.) `valid` 예시는 통과, `invalid` 예시는 거부되어야 하며 어긋나면 종료 코드 1이다. 예시는 이 PC의 실제 이미지 라벨(`docker image inspect`), `locks/images.lock`, `scripts/lib.sh`, `compose.yaml`, `config/Caddyfile`에서 가져왔다. 통과 근거는 이 문서를 쓴 쪽의 검증기이므로 헤드가 계약에 올릴 때 다시 검증한다.

## 1. 이미지 라벨 규칙 (`image-labels.schema.json`)

- 만드는 쪽: 각 영역의 Dockerfile(`ARG` -> `LABEL`). 읽는 쪽: deploy(`publish-image.sh`의 필수 라벨 검사, `e2e.sh`, `demo.sh`의 `mr_label_ok`, `check_versions.py`).
- 확인한 어긋남(이 PC의 로컬 이미지 `deploy-build/*`, 모두 같은 `build/images.env` 빌드):

| 키 | survey-service | model-serving | question-authoring | admin-console |
| --- | --- | --- | --- | --- |
| `io.openit.service` | survey-service | `model-runtime` (deploy 서비스 이름은 model-serving) | question-authoring | admin-console |
| `io.openit.contracts.survey-schema` | `1` | `1` | `survey-schema-v1.0.0` | `n/a` |
| `io.openit.model-runtime` | `v0.7.6` | `0.7.6` (v 없음) | `none` | `n/a` |
| `io.openit.turn-engine` | `v0.4.2` | `v0.4.2` | `none` | `n/a` |

  초안의 표기: 계약·turn-engine·model-runtime은 `vX.Y.Z`, 해당 없음은 `n/a`(`none` 아님), 문진 스키마는 주 버전 정수 또는 `n/a`. 이 선택은 제안이다(가장 많은 영역이 쓰는 값). 다른 표기를 정하면 정규식만 바꾼다.
- 거부 예시: model-serving의 실제 라벨(`0.7.6`), question-authoring의 실제 라벨(`survey-schema-v1.0.0`, `none`), 라벨 키 오타(`io.openit.revison`).
- 모르는 키 정책: `io.openit.*` 이름공간의 모르는 키는 거부(오타가 조용히 무시되면 필수 라벨 검사는 통과하는데 deploy가 읽지 못한다). 그 밖의 라벨(`org.opencontainers.*`)은 무시(베이스 이미지가 붙인다).
- 불변식(deploy가 지킨다): revision이 `unknown`이 아니다(`publish-image.sh`), 라벨의 계약 태그가 `scripts/lib.sh` 표와 같다(`check_versions.py`는 지금 영역 소스 파일을 읽는다. 라벨 비교로 바꾸면 파일 경로를 deploy가 몰라도 된다, DP-02).
- `io.openit.jobs`, `io.openit.exposure`는 JSON 문자열 라벨이고 내용은 5·6절 스키마를 따른다.

## 2. 이미지 게시 인터페이스 (`publish-request`, `publish-result`)

- 만드는 쪽: 영역 CI가 호출을 만들고(`publish-request`), deploy가 결과를 낸다(`publish-result`). 읽는 쪽: deploy / 영역 CI.
- 확인한 것: `scripts/publish-image.sh`의 인자, 종료 코드 0~5, 표준 출력 마지막 줄 `PUBLISHED|UNCHANGED <서비스> <digest> <revision>`, 멱등(`docs/ci.md` 2절, `scripts/test-publish.sh`). 이 스키마는 그 줄을 객체로 풀어 쓴 것이다.
- 모르는 키 정책: 거부. 호출·결과 규약이 바뀌는 것을 CI가 조용히 놓치지 않게 한다.
- 불변식: 같은 이미지를 다시 올리면 같은 digest로 `UNCHANGED`, 잠금·history가 바뀌지 않는다. 0이 아니면 `status`·`digest`가 없다. `digest`는 레지스트리가 아는 값과 push 출력이 같을 때만 기록한다.
- 서비스 이름 집합은 `scripts/lib.sh`의 `SERVICES`(+선택 `model-serving-gpu`)다. 새 서비스는 deploy가 먼저 등록한다.

## 3. [제안] 영역 빌드 진입점 인터페이스 (`build-image-request`, `build-image-result`)

- 만드는 쪽: deploy가 요청을 만들고, 영역의 `scripts/build-image.sh <요청 JSON 파일>`이 결과(표준 출력 JSON 한 줄)를 낸다. 지금은 이 진입점이 없다.
- 확인한 현재 결합: `scripts/build-images.sh`가 영역마다 다른 Dockerfile 인자(`COMMIT`/`REVISION`, `BOUNDARY_TAG`/`BC_VERSION`/`BOUNDARY_VERSION`/`BOUNDARY_CONTRACT`/`BOUNDARY_CONTRACTS`, `SURVEY_SCHEMA_VERSION`/`SURVEY_SCHEMA_TAG`/`SCHEMA_CONTRACT_VERSION`...)과 빌드 컨텍스트 이름(`wheels`, `survey_schema`, `boundary`, `schema`)을 직접 쓴다(`build-images.sh:76-178`). 예시의 요청 값은 이 인자들에 넘기는 값(`lib.sh` 표 v2.1.1 / v0.4.2 / v0.7.6, 커밋)에서 가져왔다. 진입점 자체의 예시는 실제 구현이 없어 만든 것이다.
- 모르는 키 정책: 거부(요청에 없는 능력을 영역이 짐작하지 않게).
- 불변식: 결과의 `labels`가 `image-labels` 스키마를 통과한다. deploy는 영역 소스 파일(requirements, package.json)이 아니라 이 라벨만 본다. 같은 요청은 같은 라벨을 낸다.

## 4. 게이트웨이 노출 표 (`exposure.schema.json`)

- 만드는 쪽: 각 서비스 영역(라벨 `io.openit.exposure`). 읽는 쪽: deploy(`config/Caddyfile` 생성 또는 대조).
- 확인한 현재 결합: `Caddyfile`이 영역 API 경로·메서드·역할·토큰 파일·헤더를 직접 적는다(`config/Caddyfile:109-131, 281-304` 등). 예시는 survey-service의 실제 세 블록(키오스크 세션 API: 기기 토큰, 직원 API·개입: 계정 `staff` 역할 + 서비스 토큰 `survey-api-staff` + `X-Openit-User` 설정 + SSE, 내부 경로 `risk-signals`·`results`: 닫음)에서 가져왔다. 시간 값은 `Caddyfile`의 dial 1s / 헤더 8.5s 등이다.
- 모르는 키 정책: 거부. 노출은 안전과 직결되므로 선언에 없는 속성을 deploy가 짐작하지 않는다. 목록에 없는 `/v1/*`는 계속 404(기본 닫힘).
- 불변식: 인증 `account`는 역할이 하나 이상, 역할 이름은 boundary-contracts의 역할 집합(여기서는 형식만 검사. 집합은 헤드가 정한다). `user_header=set`이면 클라이언트가 보낸 `X-Openit-User`를 덮어쓴다(D69). 비밀은 이름만 적고 값은 없다.

## 5. `scripts/setup-env.sh` 규약 (`setup-env-report.schema.json`)

- 만드는 쪽: 영역이 `scripts/setup-env.sh`를 갖는다. 읽는 쪽: deploy(`prepare-areas.sh`, `doctor.sh`, `verify_area.py`).
- 확인한 것: `prepare-areas.sh`는 영역 폴더에서 `bash scripts/setup-env.sh`를 실행하고 종료 코드와 소요 시간만 요약표에 쓴다(상태 낱말은 지금 한국어 "성공/실패(종료 N)/스크립트없음/폴더없음"). 규약 문장(인자 없음, 멱등, 비밀 미출력, 0이 성공)은 `prepare-areas.sh` 머리말과 `test-prepare-areas.sh`에서 가져왔다.
- 제안: 요약 한 줄의 모양(영어 상태 `ok|fail|script-missing|folder-missing`)과 선택 필드 `environment`(`.venv` 또는 `node_modules` 위치). `doctor.sh`가 영역 폴더의 `.venv`/`node_modules`를 추측하지 않게 하려는 것이다(DP-26). 위치 선언은 `head/shared/areas.json`의 명령 필드로 가는 안도 있다(헤드 결정).
- 모르는 키 정책: 거부. 불변식: 멱등, 영역 리포 밖을 바꾸지 않음, 비밀 값을 출력하지 않음.

## 6. 잡 엔트리포인트 선언 (`jobs-declaration.schema.json`)

- 만드는 쪽: 영역(라벨 `io.openit.jobs`). 읽는 쪽: deploy(compose 잡 정의, `config/jobs.yaml` 생성).
- 확인한 현재 결합: `compose.yaml`의 잡이 영역의 파이썬 모듈과 서브커맨드를 직접 적는다(`python -m release_gate collect`, `python -m release_gate prune`, `python -m ops_feedback.job --config /config/job.yaml`, `python -m survey_service purge`, `compose.yaml:413-510`). 예시 네 건이 그 값이고 `secret_files`는 그 잡 정의의 `*_FILE` 환경 변수 이름이다.
- 모르는 키 정책: 거부. 불변식: 모든 잡이 멱등(`idempotent: true`만 허용, 워크스페이스 규칙 D39). 어느 비밀 파일을 연결할지는 deploy가 정한다(D84, 영역은 `NAME_FILE` 이름만 선언). 주기는 선언하지 않는다(스케줄은 deploy가 정한다, D39).
- 이 CR에서 다루지 않은 것: synthetic-data `run`/`import`, question-authoring `purge`, model-lab `run`은 같은 형식으로 선언할 수 있으나 영역의 설정 파일 스키마가 먼저 필요하다(점검 보고서 3절 4행). 호스트(`gpu-external`)에서 도는 잡은 컨테이너 이미지 선언이 아니라 `run-once` 진입점이 정해져야 한다(미정).

## 하지 않은 것 / 알려진 한계

- 영역 코드와 deploy 코드는 이 스키마를 쓰지 않는다(지시: 헤드가 계약에 올린 뒤).
- 라벨 표기(1절)와 역할 이름 집합(4절)은 헤드의 결정이 필요하다. 초안의 선택은 제안이다.
- `exposure`, `jobs-declaration`의 예시는 현재 코드·설정에서 가져온 값을 선언 모양으로 옮겨 쓴 것이다. 영역이 실제로 이 선언을 낸 적은 없다.
