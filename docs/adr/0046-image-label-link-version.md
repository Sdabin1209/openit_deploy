# 0046. 영역 이미지의 link 버전은 영역 잠금 파일이 정본이고 deploy 가 대조한다

- 상태: 채택 (2026-10-30 헤드 결정 U59). 처음 제안한 라벨 `io.openit.link` 는 철회한다(변경 요청 문서는 지웠다).
- 날짜: 2026-10-30

## 맥락

통신 기반 라이브러리 link(D118)가 영역 이미지의 받는 쪽과 deploy 의 보내는 쪽에 쓰인다. 어느 영역이 어느 link 태그를 쓰는지 알아야 드리프트를 잡는다. 처음에는 이미지 라벨 `io.openit.link` 를 제안했으나(계약 `ImageLabels` v3.1.1 은 알 수 없는 `io.openit.*` 키를 거부한다) 계약 고정 중이라 키를 더하지 않기로 했다.

## 결정

link 버전의 정본은 각 영역 리포 **main 의 잠금 파일**이다: `requirements*.txt`, `*.lock` 의 `openit-link @ git+...@vX.Y.Z`(또는 `git+...openit_link.git@vX.Y.Z`), Dockerfile 의 `ARG LINK_VERSION=vX.Y.Z`. deploy 의 기준표는 `scripts/lib.sh` 의 `DEPLOY_LINK_TAG`(한 곳)이고, `scripts/check_link_pins.py`(컴포넌트 `link_pin_check`)가 영역 main 의 커밋된 잠금 파일을 `git show main:<파일>` 로 읽어 기준과 대조한다. 종료 코드: 0 같다, 1 어긋남(영역/파일/태그를 낸다), 3 핀을 하나도 못 찾음(통과가 아니다). 핀이 없는 영역은 따로 센다(통과로 세지 않는다). 자체 시험 `scripts/test_link_pin_check.py` 는 가짜 워크스페이스로 판정과 종료 코드를 본다(self-checks.list).

## 왜

- 영역이 실제로 설치하는 값이 잠금 파일이고(공통 규칙: "의존 버전은 잠금 파일로 고정한다"), 라벨은 그 값을 영역이 한 번 더 옮겨 적는 사본이다. 정본에서 읽으면 사본이 어긋날 일이 없다.
- 이웃의 내부 파일 읽기는 구조 규칙 1(영역은 서로의 구조를 모른다)에 기대는 약점이 있다. 헤드가 결정했고(U59), 읽는 것은 **잠금 파일의 link 줄 하나**로 한정하며 파일 이름 후보(requirements*.txt, *.lock, Dockerfile)는 흔한 형식이다. 영역이 다른 위치·형식으로 고정하면 NO_PIN 으로 드러난다(조용히 통과하지 않는다).
- main 의 커밋된 내용을 읽는 이유: 작업 트리의 미커밋 변경이 정본인 척하지 않게 한다.

## 검토한 대안

- 이미지 라벨 `io.openit.link`: 계약 변경이 먼저라 지금은 못 한다. 계약이 허용하면 라벨 대조를 더할 수 있다(그때 이 ADR 을 대체).
- `images.env` 도장에 `lk=` 를 더함: deploy 가 쓴 기록이지 이미지가 가진 것이 아니다(ADR 0042).

## 결과

얻는 것: 영역 잠금과 기준표의 어긋남을 이미지를 빌드하기 전에 정적으로 잡는다(2026-10-30 확인: 이 점검이 model-runtime·model-lab·ops-feedback·question-authoring·release-gate 의 v0.4.0 을 기준 v0.4.1 과 다르다고 낸다). 감수하는 것: 영역 잠금 파일 모양에 대한 가정(위 정규식 두 모양과 ARG), 점검은 `check-versions.sh`(이미지 라벨)와 별도 명령이고 e2e.sh 시작 점검에 기본 켜짐으로 걸었다(`DEPLOY_CHECK_LINK_PINS=0` 으로 끈다; check-all 출력 형식은 record-e2e.sh 가 읽어 건드리지 않았다). 측정한 것은 없다.

## 되돌리는 조건

계약이 `io.openit.link` 라벨을 허용하면 라벨 대조로 옮긴다. 영역이 잠금 위치를 공통 파일로 통일하면 후보 목록을 줄인다.
