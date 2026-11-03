#!/usr/bin/env python3
"""진입점: 이미지 라벨 io.openit.jobs 에서 compose 잡 서비스의 command·시간 한도 덧씌우기 파일을 만든다(S10). 사용: dc <프로젝트> config --format json | gen-jobs.py --out state/compose.jobs.yaml
종료 코드 0 성공, 1 선언 없음·위반. 일은 openit_deploy/components/job_overlay.py."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_gen_jobs import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
