#!/usr/bin/env python3
"""contract-ready/ 의 스키마를 예시에 대해 jsonschema(Draft 2020-12)로 검증한다(코드 변경 없음, 계약 승격용 점검).
사용: python3 validate.py [--common <_common.schema.json 경로>]   기본: 워크스페이스의 ../boundary-contracts/boundary_contracts/schemas/_common.schema.json (읽기 전용)
examples/valid/* 는 통과, examples/invalid/* 는 거부돼야 한다. 파일 이름의 첫 마디(`<계약 이름>.`)가 스키마 이름이다(MANIFEST 의 def 가 있으면 그 $defs 로 검증).
ImageLabels 의 io.openit.jobs·io.openit.exposure 값은 JSON 문자열이라 풀어서 contentSchema(JobsDeclaration, Exposure)로 한 번 더 검증한다(contentSchema 는 주석이라 검증기가 강제하지 않는다).
MANIFEST.json 이 모든 스키마와 짝이 맞는지도 본다. 종료 코드 0 모두 기대대로, 1 어긋남."""
import argparse, json, pathlib, sys
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

HERE = pathlib.Path(__file__).resolve().parent
def find_common():  # 위로 올라가며 형제 boundary-contracts 를 찾는다(리포 루트에서도 worktree 에서도 동작)
    for up in HERE.parents:
        c = up / "boundary-contracts/boundary_contracts/schemas/_common.schema.json"
        if c.exists(): return str(c)
    return ""
ap = argparse.ArgumentParser(); ap.add_argument("--common", default=find_common())
a = ap.parse_args()
schemas = {p.name[:-len(".schema.json")]: json.loads(p.read_text(encoding="utf-8")) for p in (HERE / "schemas").glob("*.schema.json")}
common = json.loads(pathlib.Path(a.common).read_text(encoding="utf-8"))
reg = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()] + [("_common.schema.json", Resource.from_contents(common))])
man = {m["name"]: m for m in json.loads((HERE / "MANIFEST.json").read_text(encoding="utf-8"))["items"]}


def validator(name):
    return Draft202012Validator(schemas[name], registry=reg)


def errors(name, doc):
    errs = [f"{'/'.join(map(str, e.path)) or '(최상위)'}: {e.validator}" for e in validator(name).iter_errors(doc)]
    if name == "ImageLabels":
        for key, sub in (("io.openit.jobs", "JobsDeclaration"), ("io.openit.exposure", "Exposure")):
            if isinstance(doc, dict) and key in doc:
                try: inner = json.loads(doc[key])
                except ValueError: errs.append(f"{key}: JSON 이 아니다"); continue
                errs += [f"{key}/{'/'.join(map(str, e.path))}: {e.validator}" for e in validator(sub).iter_errors(inner)]
    return errs


bad = ok_n = rej_n = 0
if set(man) != set(schemas): print(f"FAIL MANIFEST 와 schemas/ 의 이름이 다르다: {sorted(set(man) ^ set(schemas))}"); bad += 1
for name, s in sorted(schemas.items()):
    Draft202012Validator.check_schema(s)
    if s["$id"] != f"{name}.schema.json" or s["title"] != name: print(f"FAIL {name}: $id/title 이 계약 이름과 다르다"); bad += 1
    for kind in ("valid", "invalid"):
        files = sorted((HERE / "examples" / kind).glob(f"{name}.json")) + sorted((HERE / "examples" / kind).glob(f"{name}.*.json"))
        if not files: print(f"FAIL {name}: examples/{kind}/ 예시가 없다"); bad += 1
        for f in files:
            errs = errors(name, json.loads(f.read_text(encoding="utf-8")))
            want_ok = kind == "valid"; okay = (not errs) == want_ok
            if okay: ok_n += want_ok; rej_n += not want_ok
            print(f"{'PASS' if okay else 'FAIL'} {kind}/{f.name}: {'통과' if not errs else '거부 ' + str(len(errs)) + '건 [' + '; '.join(errs[:2]) + ']'}")
            bad += not okay
known = {p.name.split(".")[0] for k in ("valid", "invalid") for p in (HERE / "examples" / k).glob("*.json")}
if known - set(schemas): print(f"FAIL 스키마 없는 예시: {sorted(known - set(schemas))}"); bad += 1
# examples/observed/: 로컬 이미지에서 뽑은 실제 라벨 중 초안 스키마를 어기는 것. 통과/거부 기대가 없다(헤드가 스키마를 고칠지 영역을 고칠지 정하기 전): 결과만 알린다
obs = sorted((HERE / "examples" / "observed").glob("*.json"))
for f in obs:
    errs = errors(f.name.split(".")[0], json.loads(f.read_text(encoding="utf-8")))
    print(f"INFO observed/{f.name}: {'통과' if not errs else '거부 ' + str(len(errs)) + '건 [' + '; '.join(errs[:3]) + ']'} (기대 없음)")
print(f"관찰 예시 {len(obs)}개 중 스키마를 어기는 것 {sum(1 for f in obs if errors(f.name.split('.')[0], json.loads(f.read_text(encoding='utf-8'))))}개")
print(f"스키마 {len(schemas)}개, 통과 예시 {ok_n}건 통과, 거부 예시 {rej_n}건 거부, 어긋남 {bad}건")
sys.exit(1 if bad else 0)
