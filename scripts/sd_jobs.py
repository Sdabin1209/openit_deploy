"""호환 입구: E2E(e2e_steps.py)와 시험이 `import sd_jobs` 로 부르는 이름. 일은 openit_deploy/components/{job_select,job_command,job_failure_text}.py, 연결은 openit_deploy/wiring/sd_jobs.py (ADR 0045)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.sd_jobs import find_job, docker_cmd, describe_failure  # noqa: E402,F401
from openit_deploy.components.job_command import SECRET_FILES  # noqa: E402,F401
