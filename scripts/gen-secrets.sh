#!/usr/bin/env bash
# 서비스 토큰과 salt를 만든다. 사용: gen-secrets.sh [디렉터리]  (기본 secrets/, gitignore). 이미 있으면 건드리지 않는다.
# 영역마다 토큰이 다르다(CONVENTIONS 9절): 게이트 쓰기 토큰은 역할마다 하나, 서비스 사이 토큰은 서로 다른 값.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
D=${1:-$DEPLOY_ROOT/secrets}; mkdir -p "$D/tokens"; chmod 700 "$D" "$D/tokens"
rnd() { python3 -c 'import secrets;print(secrets.token_hex(24))'; }
mk() { [ -s "$D/tokens/$1" ] || { rnd > "$D/tokens/$1"; chmod 600 "$D/tokens/$1"; }; }   # 개별 토큰: 그 토큰을 쓰는 클라이언트에만 준다
for t in gate-read-survey-service gate-read-ops-feedback gate-read-question-authoring \
         gate-write-operator gate-write-ops-feedback gate-write-release-gate-collector gate-write-question-authoring gate-write-model-lab \
         ops-ingest-survey-service qa-author-e2e deid-salt; do mk "$t"; done
t() { cat "$D/tokens/$1"; }
[ -s "$D/release-gate.env" ] || { printf 'GATE_READ_TOKEN=%s\nGATE_WRITE_TOKENS=operator=%s,ops-feedback=%s,release-gate-collector=%s,question-authoring=%s,model-lab=%s\n' \
  "$(t gate-read-survey-service)" "$(t gate-write-operator)" "$(t gate-write-ops-feedback)" "$(t gate-write-release-gate-collector)" "$(t gate-write-question-authoring)" "$(t gate-write-model-lab)" > "$D/release-gate.env"; chmod 600 "$D/release-gate.env"; }
[ -s "$D/ops-feedback-ingest.env" ] || { printf 'OPS_INGEST_TOKEN=%s\n' "$(t ops-ingest-survey-service)" > "$D/ops-feedback-ingest.env"; chmod 600 "$D/ops-feedback-ingest.env"; }
[ -s "$D/ops-feedback-job.env" ] || { printf 'OPS_DEID_SALT=%s\n' "$(t deid-salt)" > "$D/ops-feedback-job.env"; chmod 600 "$D/ops-feedback-job.env"; }
[ -s "$D/question-authoring.env" ] || { printf 'QA_AUTHOR_TOKENS=%s:author-e2e:question-author\n' "$(t qa-author-e2e)" > "$D/question-authoring.env"; chmod 600 "$D/question-authoring.env"; }
echo "비밀 값 위치: $D (리포지토리에 커밋하지 않는다)"
