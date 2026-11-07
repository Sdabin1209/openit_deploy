"""wiring: Git의 저장소 등록 정보를 사용해 실제 워크스페이스를 찾는다."""
from pathlib import Path
import subprocess


def workspace_of(repository: Path) -> Path:
    repository = Path(repository).resolve()
    if (repository / ".git").is_file():
        common = subprocess.run(["git", "-C", str(repository), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True).stdout.strip()
        return Path(common).resolve().parent.parent
    return repository.parent
