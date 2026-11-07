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


def docker_cmd(docker, image, job, cfg_path, work, secrets_dir, uid, gid, extra_ro=(), *, network, pki_root_volume=None, container_name=None, runtime_inputs=None) -> list:
    from openit_deploy.wiring.schema_check import SchemaError
    spec = {"secret_files": job.get("secret_files", []), "argv": job["argv"], "config": {"container_path": job["config"]["container_path"]}}
    pki = dict(runtime_inputs or {})
    if pki_root_volume is not None:
        pki["pki_root_volume"] = pki_root_volume
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



def execute_job(docker, image, job, cfg_path, work, secrets_dir, uid, gid, extra_ro=(), *, network, pki_root_volume=None, declaration=None, environment=None):
    """RUNTIME R9.2/R9.3: 선언 상한을 적용하고 이 호출이 만든 컨테이너만 정리한다."""
    import subprocess
    import uuid

    if declaration is None:
        raise ValueError("잡 실행에는 이미지의 ContainerInputs 선언이 필요하다")
    runtime = None
    if declaration is not None:
        from boundary_contracts import validator
        from pathlib import Path
        runtime = config_mount_inputs(declaration, job, cfg_path, work, validator=validator)
        expected_ro = {str(Path(m["source"]).resolve()) for m in runtime["mounts"] if m["read_only"]}
        if expected_ro != {str(Path(path).resolve()) for path in extra_ro}:
            raise ValueError("읽기 전용 디렉터리 요청이 잡 입력 선언과 다르다")
        extra_ro = ()
        env = dict(environment or {})
        if set(env) - set(job.get("env", [])):
            raise ValueError("잡 선언에 없는 환경 변수 주입")
        profile = declaration["jobs"][job["name"]]
        files = {item.get("path_env"): item for item in profile["files"] if item.get("path_env")}
        secrets = set(job.get("secret_files", []))
        if secrets != {key for key, item in files.items() if item["kind"] == "secret"}:
            raise ValueError("잡 비밀 목록과 주입 프로필이 다르다")
        for key in secrets:
            expected = "/run/secrets/" + key.lower()
            if files[key]["path"] != expected:
                raise ValueError("잡 비밀 경로가 주입 프로필과 다르다")
            env[key] = expected
        if pki_root_volume is not None:
            if "SSL_CERT_FILE" not in files or files["SSL_CERT_FILE"]["path"] != "/etc/openit/pki/root_ca.crt":
                raise ValueError("잡 인증서 주입이 프로필과 다르다")
            env["SSL_CERT_FILE"] = "/etc/openit/pki/root_ca.crt"
        validator(profile["env_schema"]).validate(env)
        validator("CommonEnv").validate(env)
        runtime["environment"] = dict(environment or {})
    elif environment:
        raise ValueError("환경 변수는 주입 선언을 검증한 잡에만 줄 수 있다")
    name = f"openit-synthetic-job-{uuid.uuid4().hex}"
    cmd = docker_cmd(docker, image, job, cfg_path, work, secrets_dir, uid, gid, extra_ro,
                     network=network, pki_root_volume=pki_root_volume, container_name=name, runtime_inputs=runtime)
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


def config_mount_inputs(declaration, job, config_path, work, *, validator):
    """선언한 설정 경로만 읽기·쓰기 마운트로 구체화한다. 이웃 구현 경로를 알지 않는다."""
    import json
    import os
    from pathlib import Path, PurePosixPath

    validator("ContainerInputs").validate(declaration)
    profile = declaration["jobs"].get(job["name"])
    if profile is None:
        raise ValueError("잡의 ContainerInputs 프로필이 없다")
    config_path, work = Path(config_path).resolve(), Path(work).resolve()
    config = json.loads(config_path.read_text())
    validator(job["config"]["schema"]).validate(config)
    mounts = []
    for pointer, binding in profile.get("config_paths", {}).items():
        value = config
        missing = False
        for escaped in pointer[1:].split("/"):
            key = escaped.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                if not key.isascii() or not key.isdecimal() or (key != "0" and key.startswith("0")) or int(key) >= len(value):
                    missing = True
                    break
                value = value[int(key)]
            elif isinstance(value, dict) and key in value:
                value = value[key]
            else:
                missing = True
                break
        if missing:
            if binding["required"]:
                raise ValueError(f"필수 잡 설정 경로가 없다: {pointer}")
            continue
        if not isinstance(value, str) or not value or "\0" in value:
            raise ValueError(f"잡 설정 경로가 디렉터리 문자열이 아니다: {pointer}")
        container = PurePosixPath(value)
        if not container.is_absolute():
            container = PurePosixPath(job["config"]["container_path"]).parent / container
        # posixpath.normpath removes '..' without relying on host filesystem semantics.
        import posixpath
        target = posixpath.normpath(str(container))
        source = Path(value)
        if not source.is_absolute():
            source = config_path.parent / source
        source = source.resolve()
        read_only = binding["access"] == "read"
        if not read_only:
            if not source.is_relative_to(work) or source == work:
                raise ValueError(f"출력은 전용 작업 폴더 아래에 있어야 한다: {pointer}")
            if source.exists() and (not source.is_dir() or source.stat().st_uid != os.getuid() or source.stat().st_gid != os.getgid()):
                raise ValueError(f"출력 폴더 소유자·그룹 또는 종류가 작업과 다르다: {pointer}")
        if read_only and not source.is_dir():
            raise ValueError(f"선언한 입력 디렉터리가 없다: {pointer}")
        mounts.append({"source": str(source), "target": target, "read_only": read_only})
    # A writable ancestor would silently defeat a read-only child/parent declaration.
    for index, mount in enumerate(mounts):
        for other in mounts[index + 1:]:
            first, second = PurePosixPath(mount["target"]), PurePosixPath(other["target"])
            if first == second or ((first.is_relative_to(second) or second.is_relative_to(first)) and mount["read_only"] != other["read_only"]):
                raise ValueError("잡 설정의 마운트 경로가 중복되거나 읽기·쓰기 권한이 겹친다")
    scratch = []
    for writable in profile["writable"]:
        if writable["persist"]:
            raise ValueError("지속 볼륨 잡은 compose 잡 실행 경로를 사용해야 한다")
        scratch.append({"path": writable["path"], **writable["written_by"]})
    for mount in mounts:
        if not mount["read_only"]:
            directory = Path(mount["source"])
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(directory.stat().st_mode | 0o2770)
    return {"mounts": mounts, "tmpfs": scratch, "capabilities": profile["capabilities"], "sysctls": profile["sysctls"], "read_only_root": declaration["read_only_root"]}
