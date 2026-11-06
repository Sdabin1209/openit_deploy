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


def docker_cmd(docker, image, job, cfg_path, work, secrets_dir, uid, gid, extra_ro=(), *, network, pki_root_volume=None, container_name=None) -> list:
    from openit_deploy.wiring.schema_check import SchemaError
    spec = {"secret_files": job.get("secret_files", []), "argv": job["argv"], "config": {"container_path": job["config"]["container_path"]}}
    pki = {} if pki_root_volume is None else {"pki_root_volume": pki_root_volume}
    import os
    from pathlib import Path

    work_path = Path(work)
    if work_path.exists():
        stat = work_path.stat()
        if stat.st_uid != uid or stat.st_gid != gid:
            raise AssertionError("잡 작업 폴더 소유자가 선언한 호스트 사용자·그룹과 다르다")
        # 이미지 사용자는 바꾸지 않는다. 새 출력은 작업 그룹을 상속해 호스트도 읽을 수 있다.
        os.chmod(work_path, stat.st_mode | 0o2770)
    groups = set()
    for secret in job.get("secret_files", []):
        filename = job_command.SECRET_FILES.get(secret)
        if filename is not None:
            path = Path(secrets_dir) / "tokens" / filename
            if path.exists():
                groups.add(path.stat().st_gid)
    pki["supplementary_groups"] = sorted(groups)
    if container_name is not None:
        pki["container_name"] = container_name
    try:
        return call(job_command, "JobCommandRequest", "JobCommandResult",
                    {"docker": docker, "image": image, "job": spec, "config_path": str(cfg_path), "work": str(work), "secrets_dir": str(secrets_dir),
                     "uid": uid, "gid": gid, "extra_ro": [str(d) for d in extra_ro], "network": network, **pki})["argv"]
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



def execute_job(docker, image, job, cfg_path, work, secrets_dir, uid, gid, extra_ro=(), *, network, pki_root_volume=None):
    """RUNTIME R9.2/R9.3: 선언 상한을 적용하고 이 호출이 만든 컨테이너만 정리한다."""
    import subprocess
    import uuid

    name = f"openit-synthetic-job-{uuid.uuid4().hex}"
    cmd = docker_cmd(docker, image, job, cfg_path, work, secrets_dir, uid, gid, extra_ro,
                     network=network, pki_root_volume=pki_root_volume, container_name=name)
    # JobsDeclaration.timeout_seconds: 생략 시 R9.3의 3600초. 별도 값으로 재정의하지 않는다.
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=job.get("timeout_seconds", 3600))
    finally:
        # CLI 종료만으로 컨테이너는 멈추지 않는다. 성공·실패·시간 초과 모두 같은 소유 컨테이너를 정리한다.
        # 로컬 Docker 제어 요청의 대기 상한 30초(시작값, 측정하지 않음); 잡 실행 상한과 별개다.
        cleanup = subprocess.run([docker, "rm", "-f", name], capture_output=True, text=True, timeout=30)
        if cleanup.returncode:
            # --rm으로 이미 삭제된 것은 정상이다. 그 밖의 정리 실패는 성공으로 숨기지 않는다.
            remaining = subprocess.run([docker, "ps", "-a", "--filter", f"name=^/{name}$", "--format", "{{.ID}}"],
                                       capture_output=True, text=True, timeout=30)
            if remaining.returncode or remaining.stdout.strip():
                raise RuntimeError(f"잡 컨테이너 정리를 확인하지 못했다: {name}")

