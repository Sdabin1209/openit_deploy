#!/usr/bin/env python3
"""영역 scripts/setup-env.sh 의 SetupEnvReport(표준 출력 마지막 줄)를 검증해 state/setup-env/<영역>.json 에 모으고, 읽는 쪽(doctor, check-all)에 환경 위치와 시험 명령을 알려 준다.
왜: deploy 가 이웃 영역의 .venv 위치·pytest·npm 같은 환경 모양을 짐작하지 않게 한다(구조 규칙 1, U43). 영역이 낸 보고는 계약 validator 로 한 번만 검증하고 읽는 쪽은 다시 검증하지 않는다(R7).
사용:
  <setup-env 출력> | setup_env_report.py record <영역>     마지막 비어 있지 않은 줄을 SetupEnvReport 로 검증해 저장(0 저장, 1 계약 위반·영역 이름 불일치, 2 줄 없음)
  setup_env_report.py check <영역> [--ws DIR]               환경 경로가 있는지(0 있음, 1 없음·보고 없음: 사유를 표준 출력에)
  setup_env_report.py show <영역>                           저장된 보고 JSON (0, 없으면 1)
  setup_env_report.py field <영역> kind|path|command0       보고의 environment.kind / path / test_command[0] 한 값 (없으면 1)
환경 변수 SETUP_ENV_DIR 로 저장 폴더를 바꾼다(시험용)."""
import json, os, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent


def store() -> pathlib.Path:
    return pathlib.Path(os.environ.get("SETUP_ENV_DIR") or ROOT / "state" / "setup-env")


def load(area: str):
    """저장된 보고(dict). 없으면 None."""
    try:
        return json.loads((store() / f"{area}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def env_status(area: str, ws: pathlib.Path):
    """(report, 사유): 환경이 준비됐으면 사유가 빈 문자열. 보고가 없거나 환경 경로가 없으면 사유를 낸다."""
    rep = load(area)
    if rep is None:
        return None, f"{area} 의 setup-env 보고가 없다 (해결: bash scripts/prepare-areas.sh {area})"
    if rep.get("status") != "ok":
        return rep, f"{area} 의 setup-env 가 실패했다(status={rep.get('status')}, exit_code={rep.get('exit_code')}) (해결: bash scripts/prepare-areas.sh {area})"
    env = rep["environment"]
    if not (ws / area / env["path"]).exists():
        return rep, f"{area} 의 환경 경로 {env['path']} 가 없다 (해결: bash scripts/prepare-areas.sh {area})"
    return rep, ""


def env_python(area: str, ws: pathlib.Path):
    """python-venv 영역의 파이썬 실행 파일 경로. kind 가 다르거나 환경이 없으면 None. (venv 표준 배치: <path>/bin/python)"""
    rep, why = env_status(area, ws)
    if why or rep["environment"]["kind"] != "python-venv":
        return None
    return ws / area / rep["environment"]["path"] / "bin" / "python"


def main(argv):
    if len(argv) < 3 or argv[1] not in ("record", "check", "show", "field"):
        print(__doc__, file=sys.stderr); return 2
    cmd, area = argv[1], argv[2]
    if cmd == "show":
        rep = load(area)
        if rep is None: return 1
        print(json.dumps(rep, ensure_ascii=False)); return 0
    if cmd == "field":
        rep = load(area)
        if rep is None or len(argv) < 4: return 1
        env = rep["environment"]; v = {"kind": env["kind"], "path": env["path"], "command0": env["test_command"][0]}.get(argv[3])
        if v is None: return 1
        print(v); return 0
    if cmd == "check":
        ws = pathlib.Path(argv[argv.index("--ws") + 1]) if "--ws" in argv else ROOT.parent
        _, why = env_status(area, ws)
        if why: print(why); return 1
        return 0
    lines = [l for l in sys.stdin.read().splitlines() if l.strip()]
    if not lines:
        print(f"{area}: setup-env.sh 가 표준 출력에 아무것도 내지 않았다", file=sys.stderr); return 2
    try:
        rep = json.loads(lines[-1])
        from boundary_contracts import validator
        errs = [e.message[:120] for e in validator("SetupEnvReport").iter_errors(rep)]
    except Exception as e:
        errs = [f"마지막 줄을 SetupEnvReport 로 읽지 못했다({type(e).__name__})"]; rep = None
    if not errs and rep.get("area") != area:
        errs = [f"보고의 area({rep.get('area')})가 영역 이름({area})과 다르다"]
    if errs:
        print(f"{area}: SetupEnvReport 계약 위반: {'; '.join(errs[:3])}", file=sys.stderr); return 1
    d = store(); d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{area}.json.tmp"; tmp.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8"); tmp.replace(d / f"{area}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
