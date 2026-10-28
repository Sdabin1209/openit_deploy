# 0033. check-all 은 구조화된 데이터만 읽는다

## 상태
채택(2026-10-28). 규칙 4·5의 읽는 방식은 ADR 0012 를 대체한다. 규칙 9·10 은 삭제한다.

## 맥락
check-all 의 규칙 4·5 는 줄을 정규식으로 읽었다. 반박에서 오탐(쉼표 뒤 다음 인자를 값으로 읽음, 9건)과 미탐(`import turn_engine as te`, `__import__`, 하위 모듈 import 오탐)이 재현됐다. 규칙 9(README 제목 문자열 찾기)와 10(문서 산문의 "N PASS" 표기를 26줄 정규식으로 판정)은 산문을 파싱하므로 문장이 바뀔 때마다 오탐·미탐과 허용 목록 갱신이 따른다. `scripts/test_function_order.py` 는 함수 본문 안의 사용을 세지 못하는 휴리스틱이었다.

## 결정
- 규칙 4·5 는 파이썬은 `ast`, JSON 은 `json`, YAML 은 `yaml`, TOML 은 `tomllib` 로 읽는다. 파서가 없는 종류(.ts, .sh, Dockerfile)는 "대상 아님(파서 없음)"으로 세고 통과로 세지 않는다.
- 정본(`_USER`, `__all__`, `PIPELINE_SCHEMA_VERSION`)은 ast 로 읽고(Assign·AnnAssign·AugAssign·`dict(...)`), 읽지 못하면 SKIP 이 아니라 FAIL 이다. `_USER` 는 키마다 대응 템플릿 함수가 같은 파일에 있는지 교차 검증한다.
- `head/shared/areas.json` 이 없거나 영역이 0개면 규칙 0·4·5 는 FAIL 이다(분모 0 은 통과가 아니다).
- `check-all.sh --strict` 는 SKIP 이 있으면 종료 코드 1 이다. `e2e.sh` 준비 단계가 쓴다.
- 규칙 9·10, `check-all-e2e-claims.txt`, `check-all-allow.txt`(쓰이는 항목이 없어졌다), `test_function_order.py` 를 삭제한다. E2E 통과 수를 한 곳(`docs/E2E_RESULTS.md`)에만 쓰는 것은 사람의 규칙으로 남고, 자동 검사는 두지 않는다.
- 긴 셸(`e2e.sh`)은 `bash -n` 과 준비 단계(check-all, doctor)의 실제 실행에 맡긴다.

## 왜
산문을 정규식으로 읽는 검사는 문장이 바뀌면 깨지고, 깨질 때마다 사람이 정규식·허용 목록을 고친다(CLAUDE 원칙: 사실이 바뀔 때 사람이 고치는 검사 금지). 파서는 언어의 문법을 알아서 별칭·kwarg·dict·상수 노드를 구분한다. 측정은 하지 않았고, 삭제한 규칙이 잡던 사례의 집계도 없다.

## 검토한 대안
- 정규식 보강: 반박이 오탐·미탐을 계속 찾는다. 버린다.
- README 절을 구조화(frontmatter)로 바꿔 검사: 영역 문서 형식 변경이 필요해 이번 범위 밖이다. 필요해지면 새 ADR.
- 함수 순서 휴리스틱 유지: 본문 안 사용을 못 세 거짓 통과가 재현됐다. 버린다.

## 결과
얻는 것: 오탐 9건 제거, 별칭·동적 import 의 미탐 감소, 정본이 거짓이면 FAIL. 감수하는 것: ts·셸·Dockerfile 의 박힌 값, 조합한 문자열·f-string·비상수 동적 import 인자는 보지 못한다(출력에 명시). README 절과 E2E 숫자 복사는 더 이상 자동으로 막지 못한다.

## 되돌리는 조건
산문 규칙이 잡아 준 실제 사고가 반복되고, 구조화된 대안이 없을 때.
