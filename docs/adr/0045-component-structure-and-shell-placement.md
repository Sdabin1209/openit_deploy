# 0045. 영역 구조: 판단하는 일만 컴포넌트, 셸은 운영 절차, E2E 는 수용 시험

- 상태: 채택
- 날짜: 2026-10-30
- 근거 문서: `head/docs/DESIGN.md`(D117), 구조 규칙 6개(D104)

## 맥락

deploy 는 대부분 셸·Compose 설정이다. D117 은 모든 영역에 `schemas/`, `types/`, `components/`, `wiring/` 을 요구한다. 기존 Python(`scripts/*.py` 약 20개)은 인자 파서·파일 읽기·판단·출력이 한 파일에 섞여 있고, 테스트가 파일 경로와 모듈 이름에 직접 기대고 있다. E2E 시나리오(`e2e_steps.py` 2000줄)는 이웃을 HTTP 로 부르는 단계 90여 개가 모듈 전역 상태를 공유한다.

## 결정

1. **컴포넌트 = 입력 스키마 하나에서 출력 스키마 하나로 가는 판단.** Python 으로 쓰인 판단(약 19개)을 `openit_deploy/components/` 한 파일씩으로 옮긴다(표: `docs/components.md`). 파일 읽기·환경 변수·docker/git·출력·종료 코드는 `openit_deploy/wiring/`, 진입점 `scripts/*.py` 는 wiring 의 `main` 을 부르는 얇은 파일로 남긴다(이름·CLI 불변: 셸과 문서가 그 이름을 부른다).
2. **셸 스크립트는 컴포넌트가 아니다.** `scripts/*.sh`, `compose*.yaml` 은 docker·파일 배치를 부르는 운영 절차(진입점)이고 판단은 컴포넌트를 부른다. 이유: (a) 셸은 입력·출력 스키마를 가진 함수 모양이 아니고(전역 환경, 부수 효과), (b) 이 절차들을 함수로 감싸면 스키마가 "docker 가 성공했는가"를 옮겨 적는 장식이 된다. 판단이 있으면(이미지 라벨 검사, 노출 대조, 보존 기간 비교) 컴포넌트로 뺐고, 셸은 `DEPLOY_PY`(= deploy `.venv` 파이썬)로 진입점을 부른다.
3. **E2E 시나리오(`e2e_steps.py`, `e2e_plan.py`, `e2e_asserts.py`)는 컴포넌트가 아니라 수용 시험이다.** 시스템 전체를 이웃의 HTTP 로 확인하는 시험이며(공통 규칙의 "수용 테스트"), D117 6항이 "시험을 뺀 코드"로 둔다. 이웃 호출은 통신 기반 라이브러리 link 의 `openit_link.clients` 로만 하고, 이웃의 내부 규칙을 흉내 내지 않는다(되묻기 실효 한도는 계약 출력 `SurveyReadyz.reask_limit.effective`만 읽도록 고쳤다, 계약 v3.1.0). 시험은 `scripts/` 에 두었다(경로가 셸·시험·문서에 널리 박혀 있다). 구조 시험 `tests/test_structure.py` 의 `ACCEPTANCE` 가 이 세 파일을 명시한다.
4. **스키마 검증은 wiring 이 한다.** `wiring/call.py` 가 컴포넌트 입력과 출력을 스키마로 검증하고(내는 쪽이 검증, R7), 컴포넌트는 입력을 다시 검사하지 않는다. 그래서 컴포넌트를 부르는 모든 진입점은 `jsonschema`, `referencing` 이 있는 deploy `.venv` 파이썬이 필요하다(`lib.sh` 의 `DEPLOY_PY`, 작업 트리에서는 본 리포의 `.venv`). 시스템 `python3` 로 부르던 호출(`areas.py`, `retention_check.py` 등)을 `DEPLOY_PY` 로 바꿨다.
5. **코드 타입은 TypedDict.** `scripts/gen-types.sh` 가 `schemas/*.schema.json` 을 하나로 묶어 datamodel-code-generator 0.25.9(`requirements-types.txt` 로 고정)로 `openit_deploy/types/deploy_types.py` 를 생성한다. 컴포넌트는 `TYPE_CHECKING` 에서만 가져다 주석에 쓴다(런타임 의존 없음).

## 왜

- 표준: functional core / imperative shell(Bernhardt), 포트·어댑터(Cockburn)(DESIGN.md 2절). 판단은 순수하게 두고 바깥 자원은 wiring 에 둔다.
- 영역 이름·정본 목록(areas.json, lib.sh)을 스키마에 복사하지 않고 wiring 이 읽어 넘긴다(한 사실은 한 곳에서만).
- TypedDict 를 고른 이유: 컴포넌트가 주고받는 것은 JSON 문서이고(검증기도 dict 를 검증한다), pydantic 은 런타임 의존과 변환 계층을 더한다. 측정한 것은 없다.
- 스키마를 하나로 묶어 생성하는 이유: 파일마다 생성하면 0.25.9 가 스키마 사이 `$ref` 를 잘못된 상대 import(`from ..AreasDoc import schema`)로 쓰는 것을 확인했다.

## 검토한 대안

- 셸을 컴포넌트로 보고 모든 스크립트에 스키마를 단다: 장식이 된다(결정 2). 버린다.
- E2E 단계를 컴포넌트 90개로 쪼갠다: E2E 를 돌릴 수 없는 상태에서(이번 지시가 금지) 2000줄 전역 상태 코드를 옮기면 동작 보증이 없다. 시험으로 두고 정적 시험(기존 `test_e2e_*`)으로 계속 본다. 되돌리는 조건: 헤드가 E2E 도 컴포넌트로 보라고 정하면 단계 묶음별로 `link_*` 컴포넌트를 만든다.
- pydantic 모델: 위 이유로 버린다.

## 결과

얻는 것: 판단이 파일·환경에서 떨어져 단독 시험이 되고, 입출력이 스키마와 예시로 고정된다. `structure-check.py` 가 통과한다. 감수하는 것: (1) `consistency_check`, `secret_name_check` 는 읽기 전용 워크스페이스 접근을 컴포넌트 안에 둔다(입력으로 경로를 받음). 영역 수십 개 파일을 입력 문서로 모두 만들어 넘기면 요청이 거대해지고(측정하지 않았다) 규칙이 파일 단위로 걸쳐 있어 나누지 못했다. (2) 진입점이 `.venv` 에 의존한다(예전 `python3` 호출은 jsonschema 없이도 돌았다). (3) 스키마 밖 조건 6건과 범주 2건(`schemas/README.md`). (4) `probe-serving` 은 HTTP 상태 대신 계약 클라이언트의 오류 코드를 집계한다(`other_status` 표기가 코드 이름이 된다).

## 되돌리는 조건

컴포넌트 안의 파일 접근이 시험을 어렵게 하면 읽는 일을 wiring 으로 끌어올린다. 헤드가 셸 절차도 스키마 대상으로 정하면 셸의 인자 계약을 따로 정의한다.
