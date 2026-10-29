# 영역 CI -> deploy 이미지 게시 계약 (D24)

> 구분: `publish-image.sh`(단수)는 **영역 CI가 이미지 하나**를 올릴 때, `publish-images.sh`(복수)는 로컬에서 `build-images.sh`로 만든 **이미지 전체**를 올릴 때(개발·E2E) 쓴다.

영역은 이미지를 **자기 CI에서 빌드**하고, 서버의 **로컬 레지스트리**에 올린 뒤, **digest를 deploy에 제출**한다. deploy는 `locks/images.lock`(코드 축, D07)의 digest만 보고 서비스를 띄운다. 이 문서는 영역 CI가 할 일과 형식을 정한다. (확인한 것은 `scripts/test-publish.sh`로 시험한 동작, 제안·미정은 그렇게 표시했다.)

## 1. 영역 CI가 해야 할 일 (순서대로, 하나라도 실패하면 게시하지 않는다)

1. **빌드.** 자기 `Dockerfile`로 이미지를 만든다. 의존(boundary-contracts, turn-engine, model-runtime)은 Git 태그로 고정한다(D18). 빌드 인자: 커밋(`REVISION` 또는 `COMMIT`)과 의존 버전. 이미지 라벨은 영역 Dockerfile이 `ARG`로 채운다.
2. **필수 라벨 검사(D50).** `io.openit.service`, `io.openit.revision`, `io.openit.contracts.boundary`, `io.openit.contracts.survey-schema`가 있고 비어 있지 않으며 `unknown`이 아니어야 한다. `io.openit.turn-engine`, `io.openit.model-runtime`은 해당 있는 영역만 필수(해당 없으면 `n/a` 또는 생략; `none`은 거부). `publish-image.sh`가 앞의 네 개(와 revision != unknown)를 다시 검사하고 어기면 종료 코드 3으로 거부한다. 값은 계약 `ImageLabels` 스키마(필수 4개, turn-engine·model-runtime·langgraph는 해당 서비스에만, 값 없음은 `n/a` 하나, 버전은 `v` 접두사, revision은 hex)를 따라야 하고 `publish-image.sh`가 게시 전에 이 스키마로 검증한다(어기면 종료 코드 3, ADR 0035).
3. **스모크 통과.** 영역의 `scripts/smoke.sh`(이미지 빌드, `/healthz`·`/readyz`, 비root, 라벨, 영역별 확인; 고정 포트 금지)가 통과해야 한다.
4. **게시.** `scripts/publish-image.sh <서비스 이름> <이미지 ID|이미지 이름|tar> --registry <host:port>` 를 부른다. 레지스트리에 push하고 레지스트리가 아는 digest를 push 출력과 대조한 뒤, `locks/images.lock`과 `locks/history/`에 기록한다.
5. **digest 제출.** 표준 출력 마지막 줄은 계약 `PublishResult` JSON 한 줄이다(boundary-contracts v2.6.0). 성공이면 `{"exit_code":0,"status":"PUBLISHED"|"UNCHANGED","service":…,"digest":"sha256:…","revision":…}`, 실패면 `{"exit_code":N,"service":…}`(status·digest 없음). CI는 이 줄의 `status`·`digest`와 `locks/images.lock` 변경분을 deploy 리포지토리의 변경으로 올린다(아래 3절). 예전의 `PUBLISHED <서비스> <digest> <revision>` 문자열 줄은 없다. `--help`는 이 줄을 내지 않는다.

서비스 이름은 다음 중 하나다: `survey-service`, `question-authoring`, `ops-feedback`, `release-gate`, `model-registry`(model-lab 소스), `model-serving`(model-runtime 소스), `kiosk-frontend`, `admin-console`. 목록에 없으면 종료 코드 2로 거부한다(새 서비스는 deploy가 `scripts/lib.sh`의 목록과 `compose.yaml`에 먼저 등록한다).

## 2. `publish-image.sh` 인터페이스 (자체 시험 `bash scripts/test-publish.sh`: 2026-10-28 이 PC에서 실행해 전부 통과한 것을 확인. 영구 보증이 아니니 바꾼 뒤에는 다시 돌린다)

| 항목 | 내용 |
| --- | --- |
| 호출 | `scripts/publish-image.sh <서비스 이름> <이미지 ID 또는 이름 또는 tar 파일> [--registry host:port]` |
| 레지스트리 주소 | `--registry`, 없으면 `DEPLOY_REGISTRY`, 없으면 `state/registry.env`. `http://` 접두사는 떼어 낸다 |
| 잠금 위치 | `DEPLOY_LOCK`(기본 `locks/images.lock`), 이전 잠금은 같은 폴더의 `history/` |
| 멱등 | 같은 이미지를 다시 올리면 같은 digest이고 `status: "UNCHANGED"`, 잠금·history 변화 없음 |
| 새 digest | 잠금 줄 `<서비스>_DIGEST`, `<서비스>_REVISION`만 바꾸고 이전 잠금을 history에 보관, 다른 줄(다른 서비스, 외부 이미지)은 그대로. 형식은 머리말 한 줄 + 정렬된 `KEY=value` |
| 동시 호출 | `flock`으로 직렬화하고 임시 파일에 쓴 뒤 바꿔 넣는다(여러 영역 CI가 동시에 불러도 안전) |
| 종료 코드 | 0 성공/이미 같음, 1 Docker 실행 파일/데몬에 닿지 않음(인자 검사 뒤에 확인), 2 사용법 또는 서비스 이름이 목록에 없음(Docker 없이도 항상 동작, `--help`는 0), 3 필수 라벨 누락 또는 라벨 값이 ImageLabels 를 어김, 4 이미지 없음·push·digest 확인 실패, 5 잠금 기록 실패 |

배포 적용은 별도다: 잠금이 바뀐 뒤 `scripts/up.sh`가 바뀐 서비스만 교체하고, 되돌릴 때는 `scripts/rollback.sh`다(런북 2절).

## 3. 제출 형식과 접근 (일부 미정)

- **제출 내용**: `<서비스>_DIGEST=sha256:…`와 `<서비스>_REVISION=<커밋>` 두 줄(= `locks/images.lock` 변경분). 커밋 메시지에 서비스 이름과 revision을 쓴다. 제안: CI가 deploy 리포지토리에 브랜치를 만들어 이 변경을 올리고 헤드/담당자가 병합한다(자동 병합 여부는 **미정**).
- **CI가 서버 레지스트리에 닿는 방법: 미정.** 후보: (a) 서버에 둔 self-hosted runner가 `127.0.0.1:5000`에 직접 push, (b) 사설망/VPN으로 레지스트리 포트를 열기, (c) SSH 터널. 레지스트리(`registry:2`)에는 인증·TLS가 없다. 운영 도메인과 TLS, push 인증(예: htpasswd 또는 토큰)은 사용자 결정이 필요하다. 그 전에는 레지스트리를 `127.0.0.1`에만 바인드한다(`compose.registry.yaml` 기본값).
- 비밀(레지스트리 계정, deploy 리포지토리 토큰)은 CI 시크릿의 **이름**으로만 참조하고 값을 리포지토리·이미지에 넣지 않는다. 예시 workflow가 쓰는 이름: `DEPLOY_REGISTRY`(주소, 비밀 아님), `REGISTRY_USER`, `REGISTRY_PASSWORD`, `DEPLOY_REPO_TOKEN`.

## 4. 실패 시 동작

- 빌드·라벨·스모크 단계가 실패하면 **게시하지 않는다**(잠금은 바뀌지 않는다). 영역이 고쳐서 다시 돌린다.
- `publish-image.sh`가 0이 아닌 코드로 끝나면 잠금은 바뀌지 않았거나(2, 3, 4), 임시 파일만 남기고 원래 잠금이 유지된다(5). 같은 호출을 다시 해도 안전하다(멱등).
- push는 됐지만 deploy 변경 제출이 실패하면 레지스트리에 이미지가 남는다(무해). 같은 이미지로 `publish-image.sh`를 다시 부르면 `UNCHANGED` 또는 `PUBLISHED`로 이어서 끝낸다.
- 잘못된 이미지를 게시했을 때의 복구는 `scripts/rollback.sh`(잠금을 이전 것으로 되돌림). 레지스트리의 이미지를 지우는 일은 하지 않는다.
- deploy는 게시된 digest로 E2E 전체 모드를 돌려 합격한 뒤에만 서버에 적용한다(인도 전 필수, 런북 6절).

## 5. 예시

`docs/ci-example/publish-image.yml`: GitHub Actions workflow 템플릿. 영역 리포지토리의 `.github/workflows/`에 복사해 서비스 이름과 스모크 경로를 맞춰 쓴다.
