#!/usr/bin/env python3
"""진입점: 떠 있는 model-serving 의 extract 와 respond 에 입력 묶음을 보내 결과를 집계한다(docs/RUN.md '추론 서버 측정 도구'). 사용법은 --help.
호출은 openit_deploy/components/link_serving_probe.py, 집계는 components/serving_probe.py, 연결은 wiring/cli_probe_serving.py (ADR 0045)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_probe_serving import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
