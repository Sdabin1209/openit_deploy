"""컴포넌트 job_command: 선택한 잡을 `docker run` 명령(argv 목록)으로 만든다. 입력 JobCommandRequest, 출력 JobCommandResult.
설정 파일은 config.container_path 에 읽기 전용으로, 비밀은 NAME_FILE 환경 변수 + 읽기 전용 마운트로 넘긴다. work 는 같은 경로로 마운트(설정의 작업·저장소 폴더가 호스트와 같은 경로), 이미지 USER를 유지하고 호스트 작업 그룹을 보조 그룹으로 준다.
network 는 호출자가 반드시 고른다(기본값 없음): 이웃을 부르는 잡은 그 서비스들이 붙은 compose 네트워크 + 서비스 이름 주소, 이웃이 없는 잡은 "none".
어떤 비밀 파일을 어느 NAME_FILE 에 연결할지는 deploy 가 정한다(D84, JobsDeclaration.secret_files 설명): SECRET_FILES. 선언에 여기 없는 NAME_FILE 이 있으면 스키마(JobSpec.secret_files 열거)가 거부한다: 짐작해서 아무거나 주지 않는다."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import JobCommandRequest, JobCommandResult


# NAME_FILE -> tokens/ 아래 파일 이름(E2E 가 만든 토큰). schemas/JobCommandRequest.schema.json 의 secret_files enum 과 같아야 한다(tests/test_structure.py 가 대조)
SECRET_FILES = {"QUESTION_READER_TOKEN_FILE": "qa-read-synthetic-data", "FAILURE_STORE_TOKEN_FILE": "ops-read-synthetic-data",
                "DATASET_STORE_WRITE_TOKEN_FILE": "dataset-store-write-synthetic-data"}


def run(request: "JobCommandRequest") -> "JobCommandResult":
    job = request["job"]
    cmd = [request["docker"], "run", "--rm", "--network", request["network"], "--group-add", str(request["gid"])]
    def mount(source, target, read_only, kind="bind"):
        import csv
        import io
        options = io.StringIO()
        fields = [f"type={kind}", f"src={source}", f"dst={target}"]
        if read_only:
            fields.append("readonly")
        csv.writer(options, lineterminator="\n").writerow(fields)
        return ["--mount", options.getvalue().removesuffix("\n")]
    cmd += mount(request["config_path"], job["config"]["container_path"], True)
    if request.get("read_only_root"):
        cmd += ["--read-only", "--cap-drop", "ALL"]
    for name, value in sorted(request.get("sysctls", {}).items()):
        cmd += ["--sysctl", f"{name}={value}"]
    for capability in request.get("capabilities", []):
        cmd += ["--cap-add", capability]
    for binding in request.get("mounts", []):
        cmd += mount(binding["source"], binding["target"], binding["read_only"])
    for scratch in request.get("tmpfs", []):
        cmd += ["--tmpfs", f"{scratch['path']}:uid={scratch['uid']},gid={scratch['gid']},mode=1770"]
    for group in request.get("supplementary_groups", []):
        if group != request["gid"]:
            cmd += ["--group-add", str(group)]
    if "container_name" in request:
        cmd += ["--name", request["container_name"]]
    if "pki_root_volume" in request:
        cmd += mount(request["pki_root_volume"], "/etc/openit/pki", True, "volume") + ["-e", "SSL_CERT_FILE=/etc/openit/pki/root_ca.crt"]
    for d in request.get("extra_ro") or ():
        cmd += mount(d, d, True)
    for name, value in sorted(request.get("environment", {}).items()):
        cmd += ["-e", f"{name}={value}"]
    for nf in job.get("secret_files", []):
        cmd += mount(f"{request['secrets_dir'].rstrip('/')}/tokens/{SECRET_FILES[nf]}", f"/run/secrets/{nf.lower()}", True) + ["-e", f"{nf}=/run/secrets/{nf.lower()}"]
    return {"argv": cmd + [request["image"]] + job["argv"]}
