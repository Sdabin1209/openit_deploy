# CR-D24: boundary-contracts README의 개발 설치 줄에 pytest가 없다

- 상태: 제안 (영향: boundary-contracts README의 "실행 방법")
- 확인(읽기): `boundary-contracts/README.md`의 개발 설치는 `python3 -m venv .venv && . .venv/bin/activate` 뒤 `pip install -e .`(또는 `pip install jsonschema`)이다. pytest가 없다. 다른 파이썬 영역은 줄에 pytest를 포함한다(`'.[dev]'`, 인자 `pytest` 등).
- 영향: deploy의 `scripts/check-all.sh` 규칙 8(영역별 시험 수집)은 `.venv`에 pytest가 없으면 그 영역을 "검증 안 함"(SKIP)으로 둔다. README 줄대로만 설치한 새 머신에서 boundary-contracts가 SKIP이 된다.
- deploy의 대응: `docs/SETUP.md` F절에 "줄에 pytest가 없으면 `.venv/bin/pip install pytest`를 더한다"를 썼고 doctor가 짚는다.
- 요청(boundary-contracts): 개발 설치 줄에 pytest를 포함한다(예: `pip install -e . pytest` 또는 `pyproject.toml`의 dev 추가 의존).
