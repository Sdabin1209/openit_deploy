"""하위 프로세스에 넘기는 최소 환경(RUNTIME R9.1 '시험·잡은 상속받은 환경 변수를 통째로 쓰거나 넘기지 않는다', 점검 head/scripts/check-env-inheritance.py).

왜 허용 목록인가: 호출자 셸에는 토큰·SSH 에이전트 소켓 같은 이 호출과 무관한 값이 있을 수 있고, 통째로 물려주면 시험 결과가 그 값에 기댄다(같은 입력이면 같은 출력이어야 한다).
기본 이름은 head 점검(check-container-inputs)과 같은 최소 집합이다. deploy 는 자기 스크립트(lib.sh, e2e, demo)의 설정 이름이 접두사로 정해져 있어
(아래 PREFIXES: deploy 가 읽는 자기 설정) 그 접두사의 이름만 더한다. 그 밖에 한 호출이 꼭 필요한 이름은 child_env("NAME", ...) 로 이름을 더하고,
값을 바꾸려면 child_env(KEY=value) 로 준다. 이 도우미는 한 곳에만 두고 모든 호출이 쓴다(같은 뜻 한 번만).
"""
from __future__ import annotations

import os

ALLOWED = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "DOCKER_CONFIG", "DOCKER_HOST", "GIT_CONFIG_GLOBAL", "VIRTUAL_ENV", "PYTHONPATH")
# deploy 자신의 설정 이름 접두사(scripts/lib.sh 와 e2e.sh·demo.sh 가 환경 변수로 주고받는 것). 호출자의 다른 값은 넘기지 않는다
PREFIXES = ("DEPLOY_", "DEMO_", "E2E_", "GATEWAY_", "REGISTRY_", "COMPOSE_", "SECRETS_", "STEP_", "INFERENCE_", "UP_", "BUILD_", "PUBLISH_", "CHECK_", "SETUP_ENV_", "LINK_", "BOUNDARY_", "MODEL_RUNTIME_")


def child_env(*names: str, **extra: str) -> dict:
    """ALLOWED + PREFIXES 이름 + 호출이 이름으로 더한 것(os.environ 에 있을 때만) + 값을 준 것(extra)."""
    env = {k: v for k, v in os.environ.items() if k in ALLOWED or k.startswith(PREFIXES) or k in names}
    env.update(extra)
    return env
