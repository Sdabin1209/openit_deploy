"""영역이 이미지 라벨 io.openit.jobs(계약 JobsDeclaration)로 선언한 잡을 `docker run` 명령으로 만든다(U43). 영역의 모듈 이름·cwd·설정 위치·호스트 환경을 deploy 가 모른다.
왜 따로 파일인가: e2e_steps.py 는 인자 파서와 단계 정의가 섞인 스크립트라 시험하기 어렵다. 명령 조립은 순수 함수로 두고 시험이 실제 이미지로 돌려 본다(test_sd_jobs.py).
어떤 비밀 파일을 어느 NAME_FILE 에 연결할지는 deploy 가 정한다(D84, JobsDeclaration.secret_files 설명): SECRET_FILES."""
import json, pathlib

# NAME_FILE -> tokens/ 아래 파일 이름(E2E 가 만든 토큰). 선언에 여기 없는 NAME_FILE 이 있으면 연결할 토큰을 모르는 것이라 멈춘다(짐작해서 아무거나 주지 않는다)
SECRET_FILES = {"QUESTION_READER_TOKEN_FILE": "qa-read-synthetic-data", "FAILURE_STORE_TOKEN_FILE": "ops-read-synthetic-data",
                "DATASET_STORE_WRITE_TOKEN_FILE": "dataset-store-write-synthetic-data"}


def find_job(labels: dict, name: str, validator) -> dict:
    """라벨에서 JobsDeclaration 을 읽어 계약 validator 로 검증하고 잡 name 을 돌려 준다."""
    if "io.openit.jobs" not in labels:
        raise AssertionError("이미지에 라벨 io.openit.jobs 가 없다(영역이 잡을 선언하지 않았다)")
    decl = json.loads(labels["io.openit.jobs"])
    errs = list(validator("JobsDeclaration").iter_errors(decl))
    if errs:
        raise AssertionError(f"JobsDeclaration 스키마 위반: {errs[0].message}")
    job = next((j for j in decl["jobs"] if j["name"] == name), None)
    if job is None:
        raise AssertionError(f"잡 선언에 {name} 가 없다: {[j['name'] for j in decl['jobs']]}")
    return job


def docker_cmd(docker, image, job, cfg_path, work, secrets_dir, uid, gid, extra_ro=(), network="host") -> list:
    """설정 파일은 config.container_path 에 읽기 전용으로, 비밀은 NAME_FILE 환경 변수 + 읽기 전용 마운트로 넘긴다.
    work 는 같은 경로로 마운트(설정의 작업·저장소 폴더가 호스트와 같은 경로), --user 는 만든 파일을 호스트 사용자 소유로 두려는 것, --network host 는 이웃이 호스트에 게시된 포트로 닿는 E2E 용."""
    cmd = [docker, "run", "--rm", "--network", network, "--user", f"{uid}:{gid}", "-v", f"{work}:{work}", "-v", f"{cfg_path}:{job['config']['container_path']}:ro"]
    for d in extra_ro:
        cmd += ["-v", f"{d}:{d}:ro"]
    for nf in job.get("secret_files", []):
        if nf not in SECRET_FILES:
            raise AssertionError(f"잡 선언의 비밀 파일 {nf} 에 연결할 토큰을 deploy 가 정하지 않았다")
        cmd += ["-v", f"{pathlib.Path(secrets_dir) / 'tokens' / SECRET_FILES[nf]}:/run/secrets/{nf.lower()}:ro", "-e", f"{nf}=/run/secrets/{nf.lower()}"]
    return cmd + [image] + job["argv"]
