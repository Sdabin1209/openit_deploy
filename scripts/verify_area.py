#!/usr/bin/env python3
"""영역 하나가 바뀌었을 때 전체 E2E 없이 확인할 범위를 정하고 돌린다 (사용: scripts/verify-area.sh <영역>).

돌리는 것: (1) 그 영역의 시험 (2) check-all (3) config/verify-areas.yaml 이 그 영역에 대응시킨 E2E 단계 묶음(--only).
대응표와 각 대응의 근거는 config/verify-areas.yaml 한 곳에만 있다. 이 파일은 표를 읽어 명령을 조립한다.
전체 합격이 아니다: 완료 선언은 옵션 없는 전체 E2E 가 기준이다.
"""
import argparse, fnmatch, os, re, subprocess, sys, time
from pathlib import Path

try:
    import yaml
except ImportError:  # --stale-images 는 yaml 없이도 돈다. 대응표를 읽는 쪽에서 필요하면 알린다
    yaml = None

HERE = Path(__file__).resolve().parent
DEPLOY_ROOT = HERE.parent
CONFIG = DEPLOY_ROOT / "config" / "verify-areas.yaml"
AREAS = ["survey-service", "release-gate", "ops-feedback", "question-authoring", "model-runtime",
         "model-lab", "kiosk-frontend", "admin-console", "synthetic-data", "deploy"]
# 이미지 이름 -> 소스 리포지토리. scripts/build-images.sh 의 SRC 표와 같아야 한다(시험이 대조한다)
IMAGE_SRC = {"survey-service": "survey-service", "question-authoring": "question-authoring", "ops-feedback": "ops-feedback",
             "release-gate": "release-gate", "model-registry": "model-lab", "model-serving": "model-runtime",
             "kiosk-frontend": "kiosk-frontend", "admin-console": "admin-console"}


class ConfigError(Exception):
    pass


def step_order(steps_py=None):
    """e2e_steps.py 의 STEPS 목록에서 단계 이름을 실행 순서대로 읽는다."""
    src = Path(steps_py or HERE / "e2e_steps.py").read_text(encoding="utf-8")
    m = re.search(r"^STEPS = \[(.*)\]\s*$", src, re.M)
    if not m:
        raise ConfigError("e2e_steps.py 에서 STEPS 목록을 찾지 못했다")
    return re.findall(r'\("([^"]+)",\s*\w+\)', m.group(1))


def load_config(path=CONFIG, order=None):
    if yaml is None:
        raise ConfigError("PyYAML 이 필요하다 (deploy/.venv 의 python 으로 실행하라: scripts/verify-area.sh 가 고른다)")
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    order = order if order is not None else step_order()
    errs = []
    areas = cfg.get("areas") or {}
    for a in AREAS:
        if a not in areas:
            errs.append(f"영역 {a} 의 대응이 없다")
    for a in areas:
        if a not in AREAS:
            errs.append(f"모르는 영역 {a}")
    for s in list(cfg.get("e2e_base", [])) + [k for k in cfg.get("step_requires", {})] + [x for v in cfg.get("step_requires", {}).values() for x in v]:
        if s not in order:
            errs.append(f"e2e_steps.py 에 없는 단계 {s} (e2e_base/step_requires)")
    for a, spec in areas.items():
        t = spec.get("tests") or {}
        if t.get("kind") not in ("pytest", "npm", "commands"):
            errs.append(f"{a}: tests.kind 는 pytest|npm|commands")
        if t.get("kind") == "commands" and not t.get("commands"):
            errs.append(f"{a}: commands 목록이 없다")
        e = spec.get("e2e")
        if e == "fast":
            pass
        elif isinstance(e, dict) and e.get("none"):
            if not str(e.get("reason", "")).strip():
                errs.append(f"{a}: E2E 필요 없음에는 reason 이 필수다")
        elif isinstance(e, dict) and e:
            for s, v in e.items():
                if str(s) not in order:
                    errs.append(f"{a}: e2e_steps.py 에 없는 단계 {s}")
                if not (isinstance(v, dict) and str(v.get("why", "")).strip()):
                    errs.append(f"{a}: 단계 {s} 의 why(어느 호출 경계를 보는지)가 없다")
        else:
            errs.append(f"{a}: e2e 는 단계 표, {{none: true, reason: ...}}, fast 중 하나")
        for img in spec.get("image", None) or []:
            if img not in IMAGE_SRC:
                errs.append(f"{a}: 모르는 이미지 {img}")
        if "image" not in spec:
            errs.append(f"{a}: image 목록이 없다(없으면 [])")
    if errs:
        raise ConfigError("; ".join(errs))
    cfg["_order"] = order
    return cfg


def e2e_steps(cfg, area):
    """영역에 대응한 단계 + 선행 단계(base, step_requires)를 실행 순서로 돌려준다. fast 이면 'fast', 없음이면 None."""
    e = cfg["areas"][area]["e2e"]
    if e == "fast":
        return "fast"
    if e.get("none"):
        return None
    want = {str(s) for s in e}
    base = set(cfg.get("e2e_base", []))
    req = cfg.get("step_requires", {})
    if want - base - {"1", "2", "3", "4"} :
        want |= base   # 활성 릴리스가 필요한 단계(5 계열, 6 이후)는 선행 묶음을 같이 돌린다
    changed = True
    while changed:
        changed = False
        for s in list(want):
            for r in req.get(s, []):
                if r not in want:
                    want.add(r); changed = True
    return [s for s in cfg["_order"] if s in want]


def skippable(files, globs):
    """바뀐 파일이 전부 글롭 안이면 True. 파일이 하나도 없으면 False(판단 근거가 없다)."""
    if not files:
        return False
    return all(any(fnmatch.fnmatch(f, g) or (g.endswith("/**") and f.startswith(g[:-2])) for g in globs) for f in files)


def is_stale(record, image_exists, expected_rev, expected_stamp):
    """build/images.env 의 한 줄(이름 이미지 커밋 [도장])이 현재 소스·의존 태그와 다르면 낡았다.
    기록이 없거나 이미지가 로컬에 없거나, 커밋이 다르거나(접미사 -test2 포함), 도장(bc=,te=,mr=)이 없거나 다르면 낡았다(모르면 다시 빌드한다)."""
    if not record or not image_exists:
        return True
    return record.get("commit") != expected_rev or record.get("stamp") != expected_stamp


def test_command(spec, ws, area):
    t = spec["tests"]
    if t["kind"] == "pytest":
        py = ws / area / ".venv" / "bin" / "python"
        return [(str(py), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider")], ws / area
    if t["kind"] == "npm":
        return [("npm", "test", "--silent")], ws / area
    return [tuple(c) for c in t["commands"]], DEPLOY_ROOT


def assemble(cfg, area, ws, *, changed=None, no_e2e_reason=None, tests_only=False, stale=()):
    """실행 계획: [(이름, argv, cwd, env)] 와 알림 줄. 파일·Docker 를 건드리지 않는다(시험 대상)."""
    spec = cfg["areas"][area]
    plan, notes = [], []
    cmds, cwd = test_command(spec, ws, area)
    for c in cmds:
        plan.append((f"{area} 시험", list(c), cwd, {}))
    plan.append(("check-all (정적 일관성)", ["bash", str(DEPLOY_ROOT / "scripts" / "check-all.sh")], DEPLOY_ROOT, {}))
    if tests_only:
        notes.append("--tests-only: E2E 를 돌리지 않는다 (전체 합격 아님)")
        return plan, notes
    if no_e2e_reason:
        notes.append(f"E2E 필요 없음: {no_e2e_reason} (호출자가 지정한 이유)")
        return plan, notes
    steps = e2e_steps(cfg, area)
    if steps is None:
        notes.append(f"E2E 필요 없음: {spec['e2e'].get('reason')}")
        return plan, notes
    globs = spec.get("skip_e2e_paths", cfg.get("default_skip_e2e_paths", []))
    if steps != "fast" and skippable(changed or [], globs):
        notes.append(f"E2E 필요 없음: 바뀐 파일 {len(changed)}개가 모두 이미지와 호출 경계 밖이다 ({', '.join(globs)})")
        return plan, notes
    if stale:
        plan.append(("낡은 이미지만 다시 빌드", ["bash", str(DEPLOY_ROOT / "scripts" / "build-images.sh"), *stale], DEPLOY_ROOT, {}))
    base = ["bash", str(DEPLOY_ROOT / "scripts" / "e2e.sh"), "--reuse-build"]
    env = {"DEPLOY_SKIP_CHECK_ALL": "1", "DEPLOY_NO_RECORD": "1"}   # check-all 은 위에서 돌렸다. 일부 단계 결과는 정본에 기록하지 않는다
    if steps == "fast":
        plan.append(("E2E --fast (구조 전체: 전체 합격 아님)", base + ["--fast"], DEPLOY_ROOT, env))
    else:
        plan.append((f"E2E --only {','.join(steps)}", base + ["--only", ",".join(steps)], DEPLOY_ROOT, env))
        notes.append("E2E 범위 근거: " + "; ".join(f"{s}={spec['e2e'][s]['why']}" for s in steps if s in spec["e2e"]))
    return plan, notes


# ---- 실제 환경을 읽는 부분 (Docker·git) ----
def _run(argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


def lib_tags():
    p = _run(["bash", "-c", 'DEPLOY_NO_DOCKER=1 source scripts/lib.sh; echo "$DEPLOY_BC_TAG $DEPLOY_TE_TAG $DEPLOY_MR_TAG"'], DEPLOY_ROOT)
    bc, te, mr = p.stdout.split()
    return {"DEPLOY_BC_TAG": bc, "DEPLOY_TE_TAG": te, "DEPLOY_MR_TAG": mr}


def stale_images(images, ws):
    tags = lib_tags()
    stamp = f"bc={tags['DEPLOY_BC_TAG']},te={tags['DEPLOY_TE_TAG']},mr={tags['DEPLOY_MR_TAG']}"   # build-images.sh 의 record 가 쓰는 도장과 같은 모양
    rec = {}
    env = DEPLOY_ROOT / "build" / "images.env"
    if env.exists():
        for line in env.read_text().splitlines():
            f = line.split()
            if len(f) >= 3:
                rec[f[0]] = {"image": f[1], "commit": f[2], "stamp": f[3] if len(f) > 3 else None}
    out = []
    for img in images:
        src = IMAGE_SRC[img]
        ref = f"{tags['DEPLOY_MR_TAG']}^{{commit}}" if img == "model-serving" else "HEAD"   # build-images.sh: model-serving 은 model-runtime 태그 시점
        rev = _run(["git", "-C", str(ws / src), "rev-parse", "--short", ref]).stdout.strip()
        exists = img in rec and _run(["docker", "image", "inspect", rec[img]["image"]]).returncode == 0
        if not rev or is_stale(rec.get(img), exists, rev, stamp):
            out.append(img)
    return out


def changed_files(ws, area, since):
    repo = DEPLOY_ROOT if area == "deploy" else ws / area
    if since:
        r = _run(["git", "-C", str(repo), "diff", "--name-only", since])
    else:
        st = _run(["git", "-C", str(repo), "status", "--porcelain"]).stdout.splitlines()
        if st:
            return [l[3:].split(" -> ")[-1] for l in st], True
        r = _run(["git", "-C", str(repo), "diff", "--name-only", "HEAD~1", "HEAD"])
    return [l for l in r.stdout.splitlines() if l], False


def main(argv=None):
    if "--stale-images" in (argv if argv is not None else sys.argv[1:]):
        # e2e.sh --reuse-build 가 쓴다: 소스 커밋·의존 태그가 이미지 라벨과 다른(낡은) 이미지 이름을 공백으로 구분해 낸다. 판정이 안 되면 0이 아닌 코드(호출자가 전부 다시 빌드한다)
        ws = Path(os.environ.get("VERIFY_WORKSPACE") or DEPLOY_ROOT.parent)
        print(" ".join(stale_images(list(IMAGE_SRC), ws)))
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("area", nargs="?", choices=AREAS)
    ap.add_argument("--list", action="store_true", help="영역별 대응(E2E 단계와 근거)을 보여 주고 끝낸다")
    ap.add_argument("--dry-run", action="store_true", help="명령만 보여 주고 돌리지 않는다")
    ap.add_argument("--tests-only", action="store_true", help="영역 시험과 check-all 만(E2E 안 함)")
    ap.add_argument("--no-e2e", metavar="이유", help="E2E 를 건너뛴다. 이유를 반드시 적는다(영역 내부 로직만 바뀌고 이미지·호출 경계가 그대로인 이유)")
    ap.add_argument("--since", metavar="REF", help="바뀐 파일을 REF 와 비교해 정한다 (기본: 커밋 안 된 변경, 없으면 마지막 커밋)")
    ap.add_argument("--allow-dirty", action="store_true", help="커밋 안 된 변경이 있어도 E2E 를 돌린다(이미지는 HEAD 로 빌드되어 그 변경을 보지 못한다)")
    a = ap.parse_args(argv)
    cfg = load_config()
    ws = Path(os.environ.get("VERIFY_WORKSPACE") or DEPLOY_ROOT.parent)
    # deploy 를 git worktree 에서 돌릴 때처럼 상위 폴더가 워크스페이스가 아니면, 정적 점검도 같은 워크스페이스를 보게 한다
    os.environ.setdefault("CHECK_ALL_WORKSPACE", str(ws)); os.environ.setdefault("CHECK_VERSIONS_WORKSPACE", str(ws))
    if a.list:
        for ar in AREAS:
            st = e2e_steps(cfg, ar)
            e = cfg["areas"][ar]["e2e"]
            print(f"{ar}: " + ("전체 구조 -> e2e.sh --fast" if st == "fast" else f"E2E 필요 없음 ({e['reason']})" if st is None else "--only " + ",".join(st)))
            if isinstance(e, dict) and not e.get("none"):
                for s, v in e.items():
                    print(f"    {s}: {v['why']}")
        return 0
    if not a.area:
        ap.error("영역이 필요하다 (--list 로 목록)")
    if a.no_e2e is not None and not a.no_e2e.strip():
        ap.error("--no-e2e 에는 이유가 필요하다")
    files, dirty = changed_files(ws, a.area, a.since)
    spec = cfg["areas"][a.area]
    plan, notes = assemble(cfg, a.area, ws, changed=files, no_e2e_reason=a.no_e2e, tests_only=a.tests_only)
    wants_e2e = any(n.startswith("E2E") for n, *_ in plan)
    if wants_e2e and dirty and not a.allow_dirty:
        sys.exit(f"커밋 안 된 변경 {len(files)}개가 있다. E2E 이미지는 git archive HEAD 로 빌드되어 이 변경을 보지 못한다: 먼저 커밋하거나 --allow-dirty (또는 --tests-only)")
    if wants_e2e and spec.get("image") and not a.dry_run:
        st = stale_images([i for i in IMAGE_SRC], ws)   # 모든 이미지를 점검: 이웃이 바뀐 채 낡은 이미지가 E2E 에 들어가지 않게 한다
        plan, notes = assemble(cfg, a.area, ws, changed=files, no_e2e_reason=a.no_e2e, tests_only=a.tests_only, stale=tuple(st))
        notes.append("낡은 이미지: " + (", ".join(st) if st else "없음 (재사용)"))
    mr = lib_tags()["DEPLOY_MR_TAG"] if a.area == "model-runtime" else None
    if mr:
        notes.append(f"model-runtime 의 E2E 이미지는 태그 {mr} 시점 소스다. 태그에 없는 변경은 E2E 에 들어오지 않는다 (lib.sh 의 DEPLOY_MR_TAG 를 올려야 한다)")
    print(f"== verify-area {a.area}  (바뀐 파일 {len(files)}개{', 커밋 안 됨' if dirty else ''})")
    for n in notes:
        print("  - " + n)
    results = []
    rc_all = 0
    for name, argv_, cwd, env in plan:
        print(f"\n-- {name}\n   $ {' '.join(argv_)}   (cwd {cwd})")
        if a.dry_run:
            continue
        t0 = time.time()
        rc = subprocess.run(argv_, cwd=cwd, env={**os.environ, **env}).returncode
        results.append((name, rc, time.time() - t0))
        if rc != 0:
            rc_all = rc
            break
    print("\n== 요약")
    for n, rc, sec in results:
        print(f"  {'PASS' if rc == 0 else 'FAIL'} {sec:6.1f}s  {n}")
    if a.dry_run:
        print("  (--dry-run: 돌리지 않았다)")
    print("  전체 합격이 아니다. 완료 선언 전에는 옵션 없는 전체 E2E (bash scripts/e2e.sh)를 돌린다.")
    return rc_all


if __name__ == "__main__":
    sys.exit(main())
