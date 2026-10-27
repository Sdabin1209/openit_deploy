#!/usr/bin/env bash
# 서비스 토큰과 salt를 만든다. 사용: gen-secrets.sh [디렉터리]  (기본 secrets/, gitignore). 이미 있는 파일은 건드리지 않는다.
# CONVENTIONS 9절: 서버는 토큰에 역할을 묶는다. 호출하는 영역마다 다른 읽기 토큰, 쓰기 토큰은 역할마다 하나.
# secrets/tokens/<이름> : 비밀 값 하나가 파일 하나(개별 토큰, 서버가 받는 목록 값 "역할=토큰,...", salt, 콘솔 암호).
#   compose.yaml 의 최상위 secrets 가 이 파일을 /run/secrets/<이름> 에 마운트하고, 서비스는 NAME_FILE 경로로만 읽는다(D84).
#   예전 방식 secrets/<서비스>.env(환경 변수로 토큰 주입)는 없앴다: 남아 있으면 지워도 된다(아래에서 알려 준다).
# 권한: 디렉터리 700(호스트 다른 사용자 차단), 파일 644. 컨테이너는 uid 10001 로 실행되는데 compose 의 파일 secrets 는 호스트 소유자·모드를
#   그대로 마운트하므로(uid/gid/mode 옵션은 swarm 전용) 600 이면 서비스가 읽지 못한다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
D=${1:-$DEPLOY_ROOT/secrets}; mkdir -p "$D/tokens"; chmod 700 "$D" "$D/tokens"
rnd() { python3 -c 'import secrets;print(secrets.token_hex(24))'; }
tok() { [ -s "$D/tokens/$1" ] || rnd > "$D/tokens/$1"; chmod 644 "$D/tokens/$1"; cat "$D/tokens/$1"; }
putlist() { local f="$D/tokens/$1"; [ "$(cat "$f" 2>/dev/null)" = "$2" ] || printf '%s\n' "$2" > "$f"; chmod 644 "$f"; }
roles() { local srv=$1 kind=$2; shift 2; local out=""; for r in "$@"; do out+="${out:+,}$r=$(tok "$srv-$kind-$r")"; done; echo "$out"; }

# 서버가 받는 목록 값(역할=토큰,...): 값 하나짜리 파일로 만든다
GATE_R=$(roles gate read survey-service ops-feedback question-authoring model-lab synthetic-data model-serving release-approver)
GATE_W=$(roles gate write operator ops-feedback question-authoring model-lab release-gate-collector release-approver)
QA_R=$(roles qa read release-gate synthetic-data model-lab)
OPS_R=$(roles ops read synthetic-data model-lab question-authoring reviewer)
MR_R=$(roles model-registry read release-gate model-lab)
MR_W="model-lab=$(tok model-registry-write-model-lab)"
QA_AUTHOR=$(tok qa-author-e2e)
# 개별 토큰(compose.yaml 의 secrets 와 같은 이름). 클라이언트(역할)와 서버가 같은 파일 값을 쓴다
for t in gate-read-survey-service ops-ingest-survey-service survey-api-kiosk survey-api-staff inference-survey-service qa-read-release-gate \
         model-registry-read-release-gate deid-salt gate-read-ops-feedback gate-write-ops-feedback ops-read-question-authoring gate-read-model-serving \
         gate-write-release-approver gate-read-release-approver ops-read-reviewer ops-review-reviewer staff-console-password admin-console-password reviewer-console-password; do
  tok "$t" >/dev/null
done
# 목록 값 파일: 서비스가 받는 형식 그대로 한 줄. 토큰이 이미 있으면 내용이 같아서 다시 써도 같다(다르면 갱신한다).
putlist gate-read-tokens "$GATE_R"
putlist gate-write-tokens "$GATE_W"
putlist qa-read-tokens "$QA_R"
putlist ops-read-tokens "$OPS_R"
putlist model-registry-read-tokens "$MR_R"
putlist model-registry-write-tokens "$MR_W"
putlist ops-review-tokens "reviewer=$(tok ops-review-reviewer)"
putlist qa-author-tokens "$QA_AUTHOR:author-e2e:question-author"
putlist model-runtime-tokens "survey-service=$(tok inference-survey-service)"

# 게이트웨이(Caddy)는 위의 개별 토큰 파일을 {file./run/secrets/<이름>} 으로 읽는다(환경 변수 없음). 직원 콘솔은 기본 인증(개발/E2E용, 운영 방식은 미정)
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
old=$(cd "$D" && ls *.env 2>/dev/null | tr '\n' ' ') || true
[ -z "$old" ] || echo "알림: 예전 방식의 비밀 env 파일이 남아 있다($old). 더는 쓰지 않는다(환경 변수로 평문이 노출됐다). 지워도 된다: (cd $D && rm -f $old)" >&2
echo "비밀 값 위치: $D (리포지토리에 커밋하지 않는다)"
