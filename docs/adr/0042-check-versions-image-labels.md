# 0042. 버전 표 점검은 빌드된 이미지 라벨을 기준표와 비교한다

- 상태: 채택
- 날짜: 2026-10-30

## 맥락

`check-versions.sh`(check-all 규칙 1)는 형제 영역의 requirements, lock, pyproject, Dockerfile `ARG`, 빌드 스크립트에서 `boundary-contracts`·`model-runtime` 태그를 정규식으로 찾아 기준표(`lib.sh`)와 비교했다. 영역마다 계약 고정을 적는 이름과 위치가 달라(`BOUNDARY_VERSION`, `BOUNDARY_CONTRACT[S]`, `BOUNDARY_TAG`, requirements 핀 …) model-runtime Dockerfile의 `ARG BOUNDARY_VERSION=...`을 놓쳤다(U39). 패턴을 하나씩 늘리는 것은 deploy가 영역의 파일 구조를 하나씩 배우는 일이라 구조 규칙 1·6(영역은 서로의 구조를 모른다, 영역 간 스키마는 헤드)에 어긋난다.

## 결정

영역이 이미 스스로 내는 선언인 **이미지 라벨**(D50, 계약 ImageLabels)을 기준표와 비교한다. 대상은 `build/images.env`에 기록된 이미지(`build-images.sh`가 쓴다)다.

- `io.openit.contracts.boundary` = `DEPLOY_BC_TAG` (모든 이미지)
- `io.openit.model-runtime` = `n/a` 또는 `DEPLOY_MR_TAG`
- `io.openit.contracts.survey-schema` = `n/a` 또는 `DEPLOY_SS_TAG`의 주 버전
- 소스 파일 grep(`check_versions.py`)은 걷어냈다. 시험(`test-check-versions.sh`)이 코드에 영역 파일 이름·ARG 이름이 없음을 확인한다.

**이미지가 없을 때: 종료 코드 3(검증하지 못함)이다. FAIL도 통과도 아니다.** check-all은 이를 SKIP(검증 안 함)으로 낸다. 이유: 이미지를 만들기 전 개발 중의 check-all이 FAIL로 막히면 안 되고, 그렇다고 통과로 세면 검증한 것처럼 보이기 때문이다. E2E는 빌드 전 check-all에서 이 규칙을 `CHECK_ALL_IMAGES=defer`(대상 아님 + 이유)로 두고, **빌드 뒤에** 같은 스크립트를 실행해 3도 실패로 본다.

## 왜

- 라벨은 영역의 공개 산출물이고 이름이 모든 영역에서 같다(D50). 이웃의 내부 구조를 아는 것이 아니라 계약(ImageLabels)을 읽는 것이다.
- 라벨은 이미지가 실제로 만들어질 때 영역의 빌드가 정한 값이다. 소스에 적힌 문자열이 아니라 배포되는 것의 선언이라 deploy의 질문("이 이미지가 기준 열차를 쓰는가")에 직접 답한다.

## 검토한 대안과 버리는 이유

- 소스 grep 패턴을 계속 늘리기: 위반(구조 규칙). 새 영역·새 ARG 이름마다 놓칠 위험이 되풀이된다.
- 영역이 `print-pins` 같은 산출물을 내게 하기: 영역 변경이 필요하고 라벨이 이미 같은 일을 한다.
- 이미지가 없을 때 FAIL: 빌드 전 점검(check-all)을 막는다. 통과: 검증 안 한 것을 통과로 센다.

## 결과와 한계

- 얻는 것: 영역 파일 구조를 모르는 점검, 새 영역도 자동으로 대상이 된다(이미지에 라벨이 있으면).
- 감수하는 것: **빌드 전에는 드리프트를 못 잡는다**(빌드 뒤 E2E 점검과 영역 CI가 잡는다). 6분 E2E의 빌드가 먼저 돌고 나서야 어긋남을 알게 된다. 라벨이 영역의 선언일 뿐 실제 설치된 패키지 버전과 같은지는 이 점검이 보지 못한다(model-runtime은 `build-images.sh`의 `verify_mr_label`이 `RUNTIME_VERSION`과 대조한다, ADR 0041).

## 되돌리는 조건

빌드 전 정적 점검이 꼭 필요해지면 영역이 핀을 내는 표준 산출물(예: 계약이 정하는 핀 선언 파일)을 계약에 추가해 그것을 읽는다. 영역 파일 정규식으로 돌아가지 않는다.
