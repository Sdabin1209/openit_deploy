# 0035. 이미지 라벨은 게시 전에 계약 ImageLabels 스키마로 검증한다

- 상태: 채택(헤드 결정 wo8, 2026-10-29)
- 날짜: 2026-10-29

## 맥락

`publish-image.sh`는 필수 라벨 4개가 비어 있지 않은지와 revision이 `unknown`이 아닌지만 보았다. 그래서 `none`, `unset`, `unknown`, v 접두사 없는 버전, 오타 키가 통과했고, 이 PC의 실제 이미지 8개 중 5개 영역이 그런 값을 달고 있었다(docs/change-requests/contract-ready/README.md 표). `publish-images.sh`(E2E 경로)는 라벨을 아예 보지 않았다.

## 결정

1. 계약 `ImageLabels`(필수 4개, turn-engine·model-runtime·langgraph는 해당 서비스에만, 값 없음은 `n/a` 하나, revision hex만, io.openit.* 모르는 키 거부)를 정본으로 삼아 `scripts/check_image_labels.py`가 검증한다.
2. `build-images.sh`(빌드 직후), `publish-image.sh`(종료 코드 3), `publish-images.sh`, `e2e.sh`의 라벨 점검이 같은 검사기를 부른다(`lib.sh`의 `validate_image_labels`). 검사를 못 한 경우(스키마·jsonschema 없음)도 통과가 아니라 거부다.
3. 스키마 출처: 설치된 계약 패키지에 `ImageLabels.schema.json`이 있으면 그것, 없으면 `docs/change-requests/contract-ready/schemas` 사본(계약 릴리스 전의 임시 정본). 계약 태그에 오르면 사본을 지운다.
4. deploy가 Dockerfile ARG로 넘기는 값(ops-feedback, dataset-store, model-serving, question-authoring)은 deploy가 형식을 맞춘다. Dockerfile 상수나 영역 스크립트가 정하는 값(question-authoring의 `none`, release-gate의 v 접두사)은 영역이 고친다(변경 요청 CR-D28). deploy가 `docker build --label`로 덮어쓰지 않는다.

## 왜 (따른 표준과 근거)

- 표준: JSON Schema 2020-12(`jsonschema` 검증). 라벨 키를 역 도메인 이름공간(`io.openit.*`)에 두는 것은 Docker 라벨 관행이다. 값 형식을 스키마 한 곳에 두면 deploy 스크립트가 영역별 표기(`none`, `unset`, `unknown`, v 유무)를 각각 아는 일이 없어진다.
- 검사를 셸로 다시 구현하지 않고 이미 requirements.txt에 있는 `jsonschema`를 쓴다.
- 라벨은 누가 붙이든 게시 때 한 번 검사하는 것이 가장 늦지 않은 곳이다. 빌드 직후에도 검사해 게시 단계 전에 알린다.

## 검토한 대안과 버리는 이유

- 필수 4개 존재만 보는 현행: 값 이탈을 못 잡는다. 버린다.
- `--label`로 deploy가 덮어쓰기(동작은 확인했다: 명령행 라벨이 Dockerfile LABEL을 이긴다): 영역 이탈을 가려 영역이 고치지 않게 된다. 버린다.
- 영역별 규칙을 셸로 구현: 스키마와 두 벌이 된다. 버린다.

## 결과

- 얻는 것: 라벨 표기가 한 벌이다. 이탈이 게시 전에 영역 이름과 키로 드러난다.
- 감수하는 것: question-authoring과 release-gate가 고치기 전까지 `build-images.sh`와 `publish-images.sh`가 그 둘에서 멈춘다(CR-D28). 호스트에 jsonschema가 필요하다(deploy .venv, `LABELS_PYTHON`으로 바꿀 수 있다). 검사 대상은 형식뿐이고 revision이 실제 커밋인지, 버전이 기준표와 같은지는 보지 않는다(`check_versions.py`의 몫).
- 확인하지 못한 것: 수정한 build-images.sh를 처음부터 끝까지 돌려 이미지를 새로 빌드해 보지 않았다(빌드는 네트워크와 시간이 든다). Dockerfile의 ARG/LABEL 줄만 떼어 같은 build-arg로 만든 이미지의 라벨은 검사기를 통과했다(ops-feedback, dataset-store, model-serving 통과, question-authoring은 `none` 때문에 거부).

## 되돌리는 조건

계약 패키지에 ImageLabels가 오르면 사본을 지우고 패키지를 쓴다. 영역이 모두 고쳐지면 `build-images.sh` 쪽 deploy 변환(`semver_v`, `ss_major`)을 영역 Dockerfile 값으로 되돌릴 수 있다.
