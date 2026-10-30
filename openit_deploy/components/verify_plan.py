"""컴포넌트 verify_plan: 영역 하나가 바뀌었을 때 전체 E2E 없이 확인할 범위(실행 계획)를 정한다. 입력 VerifyPlanRequest, 출력 VerifyPlanResult. 파일·Docker·git 을 건드리지 않는다.
돌릴 것: (1) 그 영역의 시험 (2) check-all (3) config/verify-areas.yaml 이 그 영역에 대응시킨 E2E 단계 묶음(--only). 대응표와 근거는 config/verify-areas.yaml 한 곳, 단계 선언(repos, deps, also, why)은 e2e_steps.py 의 @step 한 곳에만 있다(wiring 이 읽어 넘긴다).
전체 합격이 아니다: 완료 선언은 옵션 없는 전체 E2E 가 기준이다.
요청의 cfg 는 verify-areas 스키마를 따르고(wiring 이 검증), cfg 밖 조건(영역·이미지 이름이 정본 목록에 있는지)은 wiring 이 본다(schemas/README.md 의 '스키마 밖 조건')."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import VerifyPlanRequest, VerifyPlanResult

import fnmatch


def closure(decls: dict, want) -> set:
    """단계가 STATE 로 읽는 앞 단계(@step 의 deps)를 모두 더한다. deps 는 ast 분석과 같음이 시험으로 강제된다."""
    want = set(want); todo = list(want)
    while todo:
        for r in decls.get(todo.pop(), {}).get("deps", []):
            if r not in want: want.add(r); todo.append(r)
    return want


def area_steps(decls: dict, area: str) -> set:
    """영역에 대응한 단계(데모·진단 제외): repos 에 영역이 있거나 also 에 적힌 단계."""
    return {n for n, d in decls.items() if not n.startswith("demo") and n != "diag"
            and (any(r.partition(":")[0] == area for r in d["repos"]) or area in dict(map(tuple, d.get("also", []))))}


def step_why(decls: dict, area: str, step: str) -> str:
    d = decls[step]
    return dict(map(tuple, d.get("also", []))).get(area) or d["why"]


def e2e_steps(cfg: dict, decls: dict, order: list, area: str):
    """영역에 대응한 단계 + 선행 단계를 실행 순서로. fast 이면 'fast', 없음이면 None."""
    e = cfg["areas"][area]["e2e"]
    if e == "fast":
        return "fast"
    if e == "none":
        return None
    want = closure(decls, area_steps(decls, area))
    return [s for s in order if s in want]


def skippable(files, globs) -> bool:
    """바뀐 파일이 전부 글롭 안이면 True. 파일이 하나도 없으면 False(판단 근거가 없다)."""
    if not files:
        return False
    return all(any(fnmatch.fnmatch(f, g) or (g.endswith("/**") and f.startswith(g[:-2])) for g in globs) for f in files)


def is_stale(record, image_exists, expected_rev, expected_stamp) -> bool:
    """build/images.env 의 한 줄(이름 이미지 커밋 [도장])이 현재 소스·의존 태그와 다르면 낡았다. 기록이 없거나 이미지가 로컬에 없거나, 커밋이 다르거나, 도장(bc=,mr=)이 없거나 다르면 낡았다(모르면 다시 빌드한다)."""
    if not record or not image_exists:
        return True
    return record.get("commit") != expected_rev or record.get("stamp") != expected_stamp


def run(request: "VerifyPlanRequest") -> "VerifyPlanResult":
    cfg, decls, order, area, root = request["cfg"], request["decls"], request["order"], request["area"], request["deploy_root"]
    spec = cfg["areas"][area]
    t = spec["tests"]
    if t["kind"] in ("pytest", "npm"):
        # 시험 명령은 영역의 setup-env 보고(SetupEnvReport.environment.test_command)가 정한다(U43): 도구·환경 배치를 deploy 가 짐작하지 않는다. also: 같은 폴더에서 이어 돌릴 명령
        if request.get("test_command") is None:
            return {"status": "NO_SETUP_ENV", "plan": [], "notes": [f"{area} 의 setup-env 보고가 없거나 실패다 (해결: bash scripts/prepare-areas.sh {area})"]}
        cmds, cwd = [request["test_command"]] + [list(c) for c in t.get("also", [])], f"{request['workspace']}/{area}"
    else:
        cmds, cwd = [list(c) for c in t["commands"]], root
    plan, notes = [], []
    for c in cmds:
        plan.append({"name": f"{area} 시험", "argv": c, "cwd": cwd, "env": {}})
    plan.append({"name": "check-all (정적 일관성)", "argv": ["bash", f"{root}/scripts/check-all.sh"], "cwd": root, "env": {}})
    if request["tests_only"]:
        return {"status": "OK", "plan": plan, "notes": ["--tests-only: E2E 를 돌리지 않는다 (전체 합격 아님)"]}
    if request.get("no_e2e_reason"):
        return {"status": "OK", "plan": plan, "notes": [f"E2E 필요 없음: {request['no_e2e_reason']} (호출자가 지정한 이유)"]}
    steps = e2e_steps(cfg, decls, order, area)
    if steps is None:
        return {"status": "OK", "plan": plan, "notes": [f"E2E 필요 없음: {spec.get('reason')}"]}
    globs = spec.get("skip_e2e_paths", cfg.get("default_skip_e2e_paths", []))
    changed = request.get("changed") or []
    if steps != "fast" and skippable(changed, globs):
        return {"status": "OK", "plan": plan, "notes": [f"E2E 필요 없음: 바뀐 파일 {len(changed)}개가 모두 이미지와 호출 경계 밖이다 ({', '.join(globs)})"]}
    if request.get("stale"):
        plan.append({"name": "낡은 이미지만 다시 빌드", "argv": ["bash", f"{root}/scripts/build-images.sh", *request["stale"]], "cwd": root, "env": {}})
    base = ["bash", f"{root}/scripts/e2e.sh", "--reuse-build"]
    env = {"DEPLOY_SKIP_CHECK_ALL": "1", "DEPLOY_NO_RECORD": "1"}   # check-all 은 위에서 돌렸다. 일부 단계 결과는 정본에 기록하지 않는다
    if steps == "fast":
        plan.append({"name": "E2E --fast (구조 전체: 전체 합격 아님)", "argv": base + ["--fast"], "cwd": root, "env": env})
    else:
        plan.append({"name": f"E2E --only {','.join(steps)}", "argv": base + ["--only", ",".join(steps)], "cwd": root, "env": env})
        mine = area_steps(decls, area)
        notes.append("E2E 범위 근거: " + "; ".join(f"{s}={step_why(decls, area, s)}" for s in steps if s in mine))
    return {"status": "OK", "plan": plan, "notes": notes}
