"""wiring/진입: 영역 하나가 바뀌었을 때 전체 E2E 없이 확인할 범위를 정하고 돌린다 (사용: scripts/verify-area.sh <영역>).
계획을 세우는 일은 컴포넌트 verify_plan 이 하고, 여기는 정본 목록(areas.json, lib.sh), 대응표(yaml), 단계 선언(e2e_steps.py), setup-env 보고, git·Docker 를 읽어 넘기고 계획을 실행한다(ADR 0045).
전체 합격이 아니다: 완료 선언은 옵션 없는 전체 E2E 가 기준이다.
"""
import argparse, os, subprocess, sys, time
from pathlib import Path

from openit_deploy.components import verify_plan
from openit_deploy.wiring import areas_file, setup_env as SER
from openit_deploy.wiring.call import call
from openit_deploy.wiring.schema_check import SchemaError, check as schema_check

try:
    import yaml
except ImportError:  # --stale-images 는 yaml 없이도 돈다. 대응표를 읽는 쪽에서 필요하면 알린다
    yaml = None

DEPLOY_ROOT = Path(__file__).resolve().parents[2]
HERE = DEPLOY_ROOT / "scripts"
sys.path.insert(0, str(HERE))
import e2e_plan as PLAN  # noqa: E402  (E2E 수용 시험의 단계 선언 읽기: scripts/e2e_plan.py)
CONFIG = DEPLOY_ROOT / "config" / "verify-areas.yaml"
# 영역 목록의 정본은 head/shared/areas.json 하나다. 시험이 있는 영역 = python·node·compose 종류(docs·library 는 verify-areas.yaml 에 없다)
AREAS = areas_file.names(kinds={"python", "node", "compose"})
# 이미지 이름 -> 소스 리포지토리. 정본은 scripts/lib.sh 의 SERVICES·service_repo 한 곳이다(두 정본을 두지 않는다, U42): 여기서 셸에 물어 만든다.
def _image_src():
    out = subprocess.run(["bash", "-c", 'DEPLOY_NO_DOCKER=1; source "$1/scripts/lib.sh"; for s in $SERVICES; do echo "$s $(service_repo "$s")"; done', "_", str(DEPLOY_ROOT)],
                         capture_output=True, text=True, check=True).stdout
    return dict(line.split() for line in out.splitlines() if line.strip())


IMAGE_SRC = _image_src()


class ConfigError(Exception):
    pass


def step_order(steps_py=None):
    """e2e_steps.py 의 STEPS 목록에서 단계 이름을 실행 순서대로 읽는다(e2e_plan 과 같은 읽기)."""
    try:
        return PLAN.steps_in_source(Path(steps_py or HERE / "e2e_steps.py"))
    except SystemExit as e:
        raise ConfigError(str(e))


def step_decls(steps_py=None):
    return PLAN.decls_from_source(Path(steps_py or HERE / "e2e_steps.py"))


def _plain_decls(decls) -> dict:
    return {n: {"repos": list(d.repos), "deps": list(d.deps), "why": d.why, "also": [list(x) for x in d.also]} for n, d in decls.items()}


def load_config(path=CONFIG, order=None, decls=None):
    if yaml is None:
        raise ConfigError("PyYAML 이 필요하다 (deploy/.venv 의 python 으로 실행하라: scripts/verify-area.sh 가 고른다)")
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    order = order if order is not None else step_order()
    decls = decls if decls is not None else step_decls()
    errs = []
    try:   # 형식 조건(tests.kind 열거, commands 필수, e2e 열거, none 의 reason, image 필수, also 이유)은 전부 스키마가 본다
        schema_check("VerifyAreas", cfg)
        schema_check("StepDecls", _plain_decls(decls))
    except SchemaError as e:
        raise ConfigError(str(e))
    # 스키마 밖 조건(schemas/README.md): 정본 목록(areas.json, lib.sh SERVICES)과의 대조
    areas = cfg.get("areas") or {}
    for a in AREAS:
        if a not in areas:
            errs.append(f"영역 {a} 의 대응이 없다")
    for a in areas:
        if a not in AREAS:
            errs.append(f"모르는 영역 {a}")
    for a, spec in areas.items():
        for img in spec.get("image") or []:
            if img not in IMAGE_SRC:
                errs.append(f"{a}: 모르는 이미지 {img}")
    for n, d in decls.items():
        for ar, why in d.also:
            if ar not in AREAS: errs.append(f"단계 {n}: also 의 모르는 영역 {ar}")
    if errs:
        raise ConfigError("; ".join(errs))
    cfg["_order"] = order; cfg["_decls"] = decls
    cfg["_requires"] = {n: list(d.deps) for n, d in decls.items()}
    return cfg


def closure(cfg, want):
    return verify_plan.closure(_plain_decls(cfg["_decls"]), want)


def area_steps(cfg, area):
    return verify_plan.area_steps(_plain_decls(cfg["_decls"]), area)


def step_why(cfg, area, step):
    return verify_plan.step_why(_plain_decls(cfg["_decls"]), area, step)


def e2e_steps(cfg, area):
    return verify_plan.e2e_steps(cfg, _plain_decls(cfg["_decls"]), cfg["_order"], area)


skippable = verify_plan.skippable
is_stale = verify_plan.is_stale


def test_command(spec, ws, area):
    """(명령 목록, cwd). 시험 명령은 영역의 setup-env 보고가 정한다(U43): 도구·환경 배치를 deploy 가 짐작하지 않는다."""
    t = spec["tests"]
    if t["kind"] in ("pytest", "npm"):
        rep = SER.load(area)
        if rep is None or rep.get("status") != "ok":
            raise ConfigError(f"{area} 의 setup-env 보고가 없거나 실패다 (해결: bash scripts/prepare-areas.sh {area})")
        return [tuple(rep["environment"]["test_command"])] + [tuple(c) for c in t.get("also", [])], ws / area
    return [tuple(c) for c in t["commands"]], DEPLOY_ROOT


def assemble(cfg, area, ws, *, changed=None, no_e2e_reason=None, tests_only=False, stale=()):
    """실행 계획: [(이름, argv, cwd, env)] 와 알림 줄. 파일·Docker 를 건드리지 않는다(시험 대상)."""
    spec = cfg["areas"][area]
    rep = SER.load(area) if spec["tests"]["kind"] in ("pytest", "npm") else None
    tc = list(rep["environment"]["test_command"]) if rep and rep.get("status") == "ok" else None
    req = {"cfg": {k: v for k, v in cfg.items() if not k.startswith("_")}, "decls": _plain_decls(cfg["_decls"]), "order": cfg["_order"], "area": area,
           "workspace": str(ws), "deploy_root": str(DEPLOY_ROOT), "changed": list(changed or []), "no_e2e_reason": no_e2e_reason, "tests_only": tests_only,
           "stale": list(stale), "test_command": tc}
    r = call(verify_plan, "VerifyPlanRequest", "VerifyPlanResult", req)
    if r["status"] == "NO_SETUP_ENV":
        raise ConfigError(r["notes"][0])
    return [(p["name"], p["argv"], Path(p["cwd"]), p["env"]) for p in r["plan"]], r["notes"]


# ---- 실제 환경을 읽는 부분 (Docker·git) ----
def _run(argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


def lib_tags():
    p = _run(["bash", "-c", 'DEPLOY_NO_DOCKER=1 source scripts/lib.sh; echo "$DEPLOY_BC_TAG $DEPLOY_MR_TAG"'], DEPLOY_ROOT)
    bc, mr = p.stdout.split()
    return {"DEPLOY_BC_TAG": bc, "DEPLOY_MR_TAG": mr}


def stale_images(images, ws):
    tags = lib_tags()
    stamp = f"bc={tags['DEPLOY_BC_TAG']},mr={tags['DEPLOY_MR_TAG']}"   # build-images.sh 의 record 가 쓰는 도장과 같은 모양
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
        # 기본 비교 범위(점검 M5): 마지막 커밋 하나가 아니라 기준 브랜치와의 차이 전체. 기준은 origin/main -> origin/master -> main -> master 중 처음 있는 것(없으면 마지막 커밋 하나로 물러서고 경고한다).
        # 여러 커밋짜리 작업에서 마지막 커밋이 문서뿐이어서 E2E 를 잘못 건너뛰는 일을 막는다. 다른 기준은 --since REF.
        base = next((b for b in ("origin/main", "origin/master", "main", "master") if _run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", b]).returncode == 0), None)
        r = None
        if base:
            mb = _run(["git", "-C", str(repo), "merge-base", base, "HEAD"]).stdout.strip()
            if mb and _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip() != mb:
                r = _run(["git", "-C", str(repo), "diff", "--name-only", mb, "HEAD"])
        if r is None:
            print(f"경고: 기준 브랜치와 갈라진 커밋이 없어(또는 기준 브랜치가 없어) 마지막 커밋 하나만 비교한다. 여러 커밋을 바꿨다면 --since REF 를 준다", file=sys.stderr)
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
    ap.add_argument("--since", metavar="REF", help="바뀐 파일을 REF 와 비교해 정한다 (기본: 커밋 안 된 변경, 없으면 기준 브랜치(origin/main 등)와 갈라진 지점부터 HEAD 까지)")
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
            if e == "auto":
                for s in sorted(area_steps(cfg, ar), key=cfg["_order"].index):
                    print(f"    {s}: {step_why(cfg, ar, s)}")
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
