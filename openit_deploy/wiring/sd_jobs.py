"""wiring: 잡 선언(io.openit.jobs)으로 잡을 돌리는 세 컴포넌트(job_select, job_command, job_failure_text)를 잇는다. E2E 와 시험이 부르는 입구(find_job, docker_cmd, describe_failure).
계약 validator(boundary_contracts)는 여기서 부르고 결과만 컴포넌트에 넘긴다. 컴포넌트가 AssertionError 를 던지던 자리는 결과 status 를 보고 여기서 같은 메시지로 AssertionError 를 낸다(E2E 의 실패 모양을 바꾸지 않는다)."""
import json

from openit_deploy.components import job_command, job_failure_text, job_select
from openit_deploy.wiring.call import call


def find_job(labels: dict, name: str, validator) -> dict:
    errs = []
    if "io.openit.jobs" in labels:
        errs = [e.message for e in validator("JobsDeclaration").iter_errors(json.loads(labels["io.openit.jobs"]))][:1]
    r = call(job_select, "JobSelectRequest", "JobSelectResult", {"labels": labels, "job_name": name, "declaration_errors": errs})
    if r["status"] == "NO_JOBS_LABEL":
        raise AssertionError("이미지에 라벨 io.openit.jobs 가 없다(영역이 잡을 선언하지 않았다)")
    if r["status"] == "INVALID_DECLARATION":
        raise AssertionError(f"JobsDeclaration 스키마 위반: {r['message']}")
    if r["status"] == "NO_SUCH_JOB":
        raise AssertionError(f"잡 선언에 {name} 가 없다: {r['available']}")
    return r["job"]


def docker_cmd(docker, image, job, cfg_path, work, secrets_dir, uid, gid, extra_ro=(), *, network) -> list:
    from openit_deploy.wiring.schema_check import SchemaError
    spec = {"secret_files": job.get("secret_files", []), "argv": job["argv"], "config": {"container_path": job["config"]["container_path"]}}
    try:
        return call(job_command, "JobCommandRequest", "JobCommandResult",
                    {"docker": docker, "image": image, "job": spec, "config_path": str(cfg_path), "work": str(work), "secrets_dir": str(secrets_dir),
                     "uid": uid, "gid": gid, "extra_ro": [str(d) for d in extra_ro], "network": network})["argv"]
    except SchemaError as e:
        raise AssertionError(f"잡 명령을 만들 수 없다(잡 선언이 deploy 의 비밀 연결표와 맞지 않는다): {e}")


def describe_failure(returncode: int, stderr: str, validator) -> str:
    lines = [l for l in (stderr or "").splitlines() if l.strip()]
    tail = lines[-1] if lines else ""
    is_json, errs = True, []
    if returncode in (2, 3, 75):
        try:
            errs = [e.message for e in validator("SyntheticJobError" if returncode == 2 else "BoundaryError").iter_errors(json.loads(tail))]
        except ValueError:
            is_json = False
    return call(job_failure_text, "JobFailureRequest", "JobFailureResult",
                {"returncode": returncode, "stderr_tail": tail, "tail_is_json": is_json, "tail_errors": errs[:1]})["text"]
