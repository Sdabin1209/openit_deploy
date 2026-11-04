"""wiring: SetupEnvReport 저장소(state/setup-env/<영역>.json)와 두 컴포넌트(setup_env_record, setup_env_status)를 잇는다. 읽는 쪽(check_all, verify_area, doctor)이 쓰는 입구: load, env_status, env_python, record.
저장 폴더는 환경 변수 SETUP_ENV_DIR 로 바꾼다(시험용). 저장·읽기·경로 존재 확인이 바깥 자원이라 컴포넌트가 아니라 여기서 한다."""
import json
import os
import pathlib
import subprocess

from openit_deploy.components import setup_env_record, setup_env_status
from openit_deploy.wiring.call import call

ROOT = pathlib.Path(__file__).resolve().parents[2]


def store() -> pathlib.Path:
    # 보고는 이 작업 트리(DEPLOY_ROOT)의 state/ 안에만 둔다: 다른 실행·트리의 보고를 이어받지 않는다(공용 가변 상태 금지). 시험은 SETUP_ENV_DIR 로 바꾼다
    if os.environ.get("SETUP_ENV_DIR"): return pathlib.Path(os.environ["SETUP_ENV_DIR"])
    return ROOT / "state" / "setup-env"


def head_commit(repo: pathlib.Path):
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() or None if r.returncode == 0 else None


def load_commit(area: str):
    try:
        return (store() / f"{area}.commit").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def load(area: str):
    """저장된 보고(dict). 없으면 None."""
    try:
        return json.loads((store() / f"{area}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _status(area: str, ws: pathlib.Path):
    rep = load(area)
    exists = bool(rep and rep.get("environment") and (ws / area / rep["environment"]["path"]).exists())
    return rep, call(setup_env_status, "SetupEnvStatusRequest", "SetupEnvStatusResult", {"area": area, "report": rep, "env_path_exists": exists, "report_commit": load_commit(area), "current_commit": head_commit(ws / area)})


def env_status(area: str, ws: pathlib.Path):
    """(report, 사유): 환경이 준비됐으면 사유가 빈 문자열."""
    rep, r = _status(area, ws)
    return rep, r["reason"]


def env_python(area: str, ws: pathlib.Path):
    """python-venv 영역의 파이썬 실행 파일 경로. kind 가 다르거나 환경이 없으면 None."""
    _, r = _status(area, ws)
    return ws / area / r["python"] if r["status"] == "READY" and r["python"] else None


def record(area: str, stdout_lines: list, ws=None):
    """(종료 코드, 표준 오류 메시지). 계약 검증은 계약 패키지 validator."""
    errs = []
    lines = [l for l in stdout_lines if l.strip()]
    if lines:
        try:
            rep = json.loads(lines[-1])
            from boundary_contracts import validator
            errs = [e.message[:120] for e in validator("SetupEnvReport").iter_errors(rep)]
        except ValueError:
            pass
        except Exception as e:
            errs = [f"마지막 줄을 SetupEnvReport 로 읽지 못했다({type(e).__name__})"]
    r = call(setup_env_record, "SetupEnvRecordRequest", "SetupEnvRecordResult", {"area": area, "stdout_lines": stdout_lines, "contract_errors": errs})
    if r["status"] != "STORE":
        return (2 if r["status"] == "NO_LINE" else 1), r["message"]
    d = store(); d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{area}.json.tmp"; tmp.write_text(json.dumps(r["report"], ensure_ascii=False), encoding="utf-8"); tmp.replace(d / f"{area}.json")
    c = head_commit(pathlib.Path(ws) / area) if ws else None   # 보고를 만든 영역 커밋(낡은 보고 판정용)
    if c: (d / f"{area}.commit").write_text(c + "\n", encoding="utf-8")
    return 0, ""
