#!/usr/bin/env python3
"""CR-D27 의 스키마 초안을 예시 문서에 대해 jsonschema 로 검증한다. 사용: .venv/bin/python docs/change-requests/schemas/validate.py
`<이름>.valid*.json` 은 통과해야 하고 `<이름>.invalid*.json` 은 거부돼야 한다. 라벨의 io.openit.jobs·io.openit.exposure 값은 JSON 문자열이라 풀어서 contentSchema 로 한 번 더 검증한다. 종료 코드 0 모두 기대대로, 1 어긋남."""
import json, pathlib, sys
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

HERE = pathlib.Path(__file__).resolve().parent
schemas = {p.name[:-len(".schema.json")]: json.loads(p.read_text(encoding="utf-8")) for p in HERE.glob("*.schema.json")}
reg = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()])


def errors(name, doc):
    v = Draft202012Validator(schemas[name], registry=reg)
    errs = [f"{'/'.join(map(str, e.path)) or '(최상위)'}: {e.validator}" for e in v.iter_errors(doc)]
    if name == "image-labels":   # JSON 문자열 라벨의 내용
        for key, sub in (("io.openit.jobs", "jobs-declaration"), ("io.openit.exposure", "exposure")):
            if key in doc:
                try: inner = json.loads(doc[key])
                except ValueError: errs.append(f"{key}: JSON 이 아니다"); continue
                errs += [f"{key}/{'/'.join(map(str, e.path))}: {e.validator}" for e in Draft202012Validator(schemas[sub], registry=reg).iter_errors(inner)]
    return errs


bad = 0
for name in sorted(schemas):
    Draft202012Validator.check_schema(schemas[name])
    files = sorted((HERE / "examples").glob(f"{name}.*.json"))
    if not any(".valid" in f.name for f in files) or not any(".invalid" in f.name for f in files):
        print(f"FAIL {name}: 통과 예시와 거부 예시가 각각 하나 이상 있어야 한다"); bad += 1
    for f in files:
        errs = errors(name, json.loads(f.read_text(encoding="utf-8")))
        want_ok = ".invalid" not in f.name
        okay = (not errs) == want_ok
        print(f"{'PASS' if okay else 'FAIL'} {f.name}: {'통과' if not errs else '거부 ' + str(len(errs)) + '건 [' + '; '.join(errs[:3]) + ']'} (기대: {'통과' if want_ok else '거부'})")
        bad += not okay
print(f"스키마 {len(schemas)}개, 예시 파일 {len(list((HERE / 'examples').glob('*.json')))}개, 어긋남 {bad}건")
sys.exit(1 if bad else 0)
