#!/usr/bin/env bash
# 서비스 토큰과 salt를 만든다. 사용: gen-secrets.sh [디렉터리]  (기본 secrets/, gitignore). 이미 있는 파일은 건드리지 않는다.
# CONVENTIONS 9절: 서버는 토큰에 역할을 묶는다. 호출하는 영역마다 다른 읽기 토큰, 쓰기 토큰은 역할마다 하나.
# secrets/tokens/<서버>-<read|write>-<역할> : 클라이언트(역할)에게만 주는 개별 토큰
# secrets/<서비스>.env : 서비스가 받는 환경 변수(자기 것만)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
D=${1:-$DEPLOY_ROOT/secrets}; mkdir -p "$D/tokens"; chmod 700 "$D" "$D/tokens"
rnd() { python3 -c 'import secrets;print(secrets.token_hex(24))'; }
tok() { [ -s "$D/tokens/$1" ] || { rnd > "$D/tokens/$1"; chmod 600 "$D/tokens/$1"; }; cat "$D/tokens/$1"; }
roles() { local srv=$1 kind=$2; shift 2; local out=""; for r in "$@"; do out+="${out:+,}$r=$(tok "$srv-$kind-$r")"; done; echo "$out"; }
put() { local f=$1; shift; [ -s "$D/$f" ] && return 0; printf '%s\n' "$@" > "$D/$f"; chmod 600 "$D/$f"; }

# 서버가 받는 목록
GATE_R=$(roles gate read survey-service ops-feedback question-authoring model-lab synthetic-data model-serving release-approver)
GATE_W=$(roles gate write operator ops-feedback question-authoring model-lab release-gate-collector release-approver)
QA_R=$(roles qa read release-gate synthetic-data model-lab)
OPS_R=$(roles ops read synthetic-data model-lab question-authoring reviewer)
MR_R=$(roles model-registry read release-gate model-lab)
MR_W="model-lab=$(tok model-registry-write-model-lab)"
OPS_INGEST=$(tok ops-ingest-survey-service)
QA_AUTHOR=$(tok qa-author-e2e)
tok deid-salt >/dev/null

# 각 클라이언트가 받는 자기 토큰(이웃 서버가 그 역할로 알아본다)
put release-gate.env "GATE_READ_TOKENS=$GATE_R" "GATE_WRITE_TOKENS=$GATE_W" "GATE_I1_TOKEN=$(tok qa-read-release-gate)" "GATE_I3_TOKEN=$(tok model-registry-read-release-gate)"
put release-gate-job.env "GATE_I1_TOKEN=$(tok qa-read-release-gate)" "GATE_I3_TOKEN=$(tok model-registry-read-release-gate)"
put survey-service.env "SURVEY_RELEASE_READER_TOKEN=$(tok gate-read-survey-service)" "SURVEY_TRACE_INGEST_TOKEN=$OPS_INGEST" "SURVEY_API_TOKEN=$(tok survey-api-kiosk)" "SURVEY_STAFF_API_TOKEN=$(tok survey-api-staff)" "SURVEY_INFERENCE_TOKEN=$(tok inference-survey-service)"
put ops-feedback-ingest.env "OPS_INGEST_TOKEN=$OPS_INGEST" "OPS_READ_TOKENS=$OPS_R" "OPS_REVIEW_TOKENS=reviewer=$(tok ops-review-reviewer)"
put ops-feedback-job.env "OPS_DEID_SALT=$(tok deid-salt)" "OPS_GATE_READ_TOKEN=$(tok gate-read-ops-feedback)" "OPS_GATE_WRITE_TOKEN=$(tok gate-write-ops-feedback)"
put question-authoring.env "QA_AUTHOR_TOKENS=$QA_AUTHOR:author-e2e:question-author" "QA_READ_TOKENS=$QA_R" "QA_FAILURES_TOKEN=$(tok ops-read-question-authoring)"
put model-serving.env "MODEL_RUNTIME_TOKENS=survey-service=$(tok inference-survey-service)" "MODEL_RUNTIME_RELEASE_TOKEN=$(tok gate-read-model-serving)"
put model-registry.env "MODEL_REGISTRY_READ_TOKENS=$MR_R" "MODEL_REGISTRY_WRITE_TOKENS=$MR_W"

# 게이트웨이: 브라우저 대신 survey-service 토큰을 붙인다(토큰은 게이트웨이의 비밀). 직원 콘솔은 기본 인증(개발/E2E용, 운영 방식은 미정)
put gateway.env "SURVEY_KIOSK_TOKEN=$(tok survey-api-kiosk)" "SURVEY_STAFF_TOKEN=$(tok survey-api-staff)" "GATE_APPROVER_TOKEN=$(tok gate-write-release-approver)" "GATE_APPROVER_READ_TOKEN=$(tok gate-read-release-approver)" "OPS_REVIEWER_READ_TOKEN=$(tok ops-read-reviewer)" "OPS_REVIEWER_WRITE_TOKEN=$(tok ops-review-reviewer)"
if [ ! -s "$D/gateway-staff-auth.caddy" ]; then
  GW_IMG=$(sed -n 's/^GATEWAY_IMAGE=//p' "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}")
  HASH=$("$DOCKER" run --rm "$GW_IMG" caddy hash-password --plaintext "$(tok staff-console-password)" | tr -d '\r')
  [ -n "$HASH" ] || die "caddy hash-password 실패"
  printf '(staff_auth) {\n\tbasic_auth {\n\t\tstaff %s\n\t}\n}\n' "$HASH" > "$D/gateway-staff-auth.caddy"; chmod 644 "$D/gateway-staff-auth.caddy"   # 게이트웨이(uid 10001)가 읽는다. bcrypt 해시만 있다
fi
# 사람 계정(승인 화면 /admin/): 기본 인증(개발/E2E용 시험 계정 두 개, 운영 방식은 미정). 계정 -> 역할 매핑도 이 파일에 둔다.
#   trainer-e2e = release-approver (승인 경로 4개), reviewer-e2e = reviewer (실패 사례 검토 경로). 다른 역할의 경로는 403
if [ ! -s "$D/gateway-human-auth.caddy" ]; then
  GW_IMG=$(sed -n 's/^GATEWAY_IMAGE=//p' "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}")
  H1=$("$DOCKER" run --rm "$GW_IMG" caddy hash-password --plaintext "$(tok admin-console-password)" | tr -d '\r')
  H2=$("$DOCKER" run --rm "$GW_IMG" caddy hash-password --plaintext "$(tok reviewer-console-password)" | tr -d '\r')
  [ -n "$H1" ] && [ -n "$H2" ] || die "caddy hash-password 실패"
  printf '(human_auth) {\n\tbasic_auth {\n\t\ttrainer-e2e %s\n\t\treviewer-e2e %s\n\t}\n}\n(role_matchers) {\n\t@role_approver expression `{http.auth.user.id} in ["trainer-e2e"]`\n\t@role_reviewer expression `{http.auth.user.id} in ["reviewer-e2e"]`\n}\n' "$H1" "$H2" > "$D/gateway-human-auth.caddy"; chmod 644 "$D/gateway-human-auth.caddy"
fi
echo "비밀 값 위치: $D (리포지토리에 커밋하지 않는다)"
