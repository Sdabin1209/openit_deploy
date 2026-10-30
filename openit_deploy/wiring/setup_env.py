"""wiring: SetupEnvReport 저장소(state/setup-env/<영역>.json)와 두 컴포넌트(setup_env_record, setup_env_status)를 잇는다. 읽는 쪽(check_all, verify_area, doctor)이 쓰는 입구: load, env_status, env_python, record.
저장 폴더는 환경 변수 SETUP_ENV_DIR 로 바꾼다(시험용). 저장·읽기·경로 존재 확인이 바깥 자원이라 컴포넌트가 아니라 여기서 한다."""
import json
import os
import pathlib

from openit_deploy.components import setup_env_record, setup_env_status
from openit_deploy.wiring.call import call

ROOT = pathlib.Path(__file__).resolve().parents[2]


def store() -> pathlib.Path:
    return pathlib.Path(os.environ.get("SETUP_ENV_DIR") or ROOT / "state" / "setup-env")


def load(area: str):
    """저장된 보고(dict). 없으면 None."""
    try:
        return json.loads((store() / f"{area}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _status(area: str, ws: pathlib.Path):
    rep = load(area)
    exists = bool(rep and rep.get("environment") and (ws / area / rep["environment"]["path"]).exists())
    return rep, call(setup_env_status, "SetupEnvStatusRequest", "SetupEnvStatusResult", {"area": area, "report": rep, "env_path_exists": exists})


def env_status(area: str, ws: pathlib.Path):
    """(report, 사유): 환경이 준비됐으면 사유가 빈 문자열."""
    rep, r = _status(area, ws)
    return rep, r["reason"]


def env_python(area: str, ws: pathlib.Path):
    """python-venv 영역의 파이썬 실행 파일 경로. kind 가 다르거나 환경이 없으면 None."""
    _, r = _status(area, ws)
    return ws / area / r["python"] if r["status"] == "READY" and r["python"] else None


def record(area: str, stdout_lines: list):
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
    return 0, ""
