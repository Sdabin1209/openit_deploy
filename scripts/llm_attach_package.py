#!/usr/bin/env python3
"""진입점: 학습 서버가 만든 진짜 LoRA 어댑터 두 개를 실제 LLM 데모용 모델 패키지로 만든다(make-llm-package.sh --adapter-a ... 가 부른다). 사용법은 --help.
어댑터 판정은 openit_deploy/components/adapter_check.py, 연결·복사·매니페스트는 wiring/cli_llm_attach_package.py (ADR 0045)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from openit_deploy.wiring.cli_llm_attach_package import main  # noqa: E402

if __name__ == "__main__":
    main()
