#!/usr/bin/env bash
# 이웃 영역의 환경·패키지 짐작이 deploy 스크립트에 남지 않았는지 정적으로 본다(U43, 구조 규칙 1).
# 금지: 이웃의 .venv/bin/python, node_modules 경로, synthetic_data 패키지 이름, 호스트 잡 venv(venv-sd), 이웃 영역 소스 파일 읽기(ROOT.parent / "<영역>/…", risk_rules.py: U48). 환경·시험 명령은 영역의 setup-env 보고(SetupEnvReport)로만 안다.
# 허용(이유가 있는 것만): deploy 자신의 .venv($DEPLOY_ROOT/.venv, $HERE/../.venv, 작업 트리에서 본 리포의 $DEPLOY_COMMON_ROOT/.venv), 저장소 스캔에서 건너뛸 폴더 이름 목록(check_all.py, check_secret_names.py), 주석·문서 문장,
#   계약 SyntheticJobConfigRun 이 요구하는 adapters.factory 값(계약이 정한 설정 내용: e2e_steps.py 의 marker "계약 factory"), e2e_gpu.sh 의 model-lab GPU 잡(아직 선언 없음: CR-U49).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
hits=$(grep -nE '\.venv/bin/python|node_modules|synthetic_data|venv-sd|risk_rules\.py|ROOT\.parent *(/|\))? *"?(survey-service|question-authoring|ops-feedback|release-gate|model-lab|model-runtime|synthetic-data|kiosk-frontend|admin-console)' $(git ls-files 'prepare-*.sh' 'doctor.sh' 'lib.sh' 'build-images.sh' 'e2e*.sh' 'e2e*.py' 'check*' 'verify*' 'run-*.sh' 'publish*' 'setup_env_report.py' 2>/dev/null || ls *.sh *.py) 2>/dev/null \
  | grep -vE 'DEPLOY_ROOT/\.venv|DEPLOY_COMMON_ROOT/\.venv|HERE/\.\./\.venv|^[^:]*:[0-9]+:\s*#|계약 factory|dirs\[:\]|re\.search\(r"\(\^\|/\)|SKIP = re\.compile|e2e_gpu\.sh:|^test[-_]|"""|check-relocatable\.sh|영역의 setup-env 보고' || true)
if [ -n "$hits" ]; then echo "FAIL 이웃 환경·패키지 짐작이 남아 있다:"; echo "$hits"; exit 1; fi
echo "통과: 이웃 환경·패키지 짐작 문자열 없음 (deploy 자신의 .venv, 스캔 제외 목록, 계약 factory, e2e_gpu.sh 만 예외)"
