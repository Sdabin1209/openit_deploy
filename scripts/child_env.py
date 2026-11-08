"""openit_deploy.wiring.child_env 의 얇은 진입(scripts/ 의 스크립트·시험이 sys.path[0]=scripts 로 가져온다). 정의는 한 곳(openit_deploy/wiring/child_env.py)이다."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.child_env import ALLOWED, PREFIXES, child_env  # noqa: E402,F401
