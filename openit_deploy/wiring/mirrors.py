"""wiring: 영역 시험·빌드를 돌리는 deploy 도구가 영역 실행 환경에 로컬 미러 git 설정(GIT_CONFIG_GLOBAL=build/gitconfig-local-mirrors)을 주게 한다(S14).
왜: 원격이 동결된 동안 영역의 build_image·setup_env 시험은 의존 리포(link, boundary-contracts, model-runtime)를 로컬 전용 태그로 받는다. 미러 설정이 없으면 GitHub 에서 그 태그를 찾다 실패한다(check-all 에서 확인).
이미 GIT_CONFIG_GLOBAL 이 있으면 그것을 존중한다(호출자가 정한 입력)."""
import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]


def ensure_env(environ=None) -> str:
    env = os.environ if environ is None else environ
    if env.get("GIT_CONFIG_GLOBAL"):
        return env["GIT_CONFIG_GLOBAL"]
    out = subprocess.run(["bash", str(ROOT / "scripts" / "write-local-mirrors.sh")], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("로컬 미러 git 설정을 만들 수 없다: " + out.stderr.strip()[-300:])
    env["GIT_CONFIG_GLOBAL"] = out.stdout.strip().splitlines()[-1]
    return env["GIT_CONFIG_GLOBAL"]
