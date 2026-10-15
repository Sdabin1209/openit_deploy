#!/usr/bin/env bash
# 합격 시나리오(docs/E2E.md)를 사람 손 없이 순서대로 실행한다.
#  - 임시 레지스트리·프로젝트(deploy-e2e-*)를 만들고 끝나면 지운다. 호스트 포트는 Docker가 배정한 것을 읽는다(레지스트리는 빈 포트를 고른다).
#  - 단계 상태: REAL(실제 서비스) / TEST-SUB(시험 대역으로 대신함) / BLOCKED(지금 구현으로는 이어지지 않음). 시험 자료는 이름에 test가 들어간다.
#  - 합격: 하나라도 FAIL이면 종료 코드 1. BLOCKED는 실패가 아니지만 요약에 그대로 보인다.
# 사용: scripts/e2e.sh [--keep] [--keep-images] [--reuse-build]   (--keep-images 는 로컬 빌드 이미지를 남겨 다음 실행이 --reuse-build 로 시간을 아낀다)
set -o pipefail
source "$(dirname "$0")/lib.sh"
KEEP=0; REUSE=0; KEEPIMG=0
for x in "$@"; do case "$x" in --keep) KEEP=1;; --reuse-build) REUSE=1; KEEPIMG=1;; --keep-images) KEEPIMG=1;; esac; done
ID=$$; PROJECT=deploy-e2e-$ID; RPROJ=deploy-e2e-reg-$ID
W="$DEPLOY_ROOT/state/e2e-$ID"; mkdir -p "$W"
export DEPLOY_LOCK="$W/images.lock" DEPLOY_REGISTRY_ENV="$W/registry.env" DEPLOY_PROJECT=$PROJECT
export REGISTRY_PROJECT=$RPROJ REGISTRY_HOST_BIND=0.0.0.0 REGISTRY_HOST_PORT=
UTIL_REF=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock")
export SECRETS_DIR="$W/secrets" COMPOSE_EXTRA="$DEPLOY_ROOT/compose.test.yaml" GATEWAY_PORT=
RESULT=(); FAILS=0
res() { RESULT+=("$1|$2|$3"); [ "$2" = FAIL ] && FAILS=$((FAILS+1)); printf '  [%s] %s: %s\n' "$2" "$1" "$3"; }
chk() { local name=$1; shift; local out; if out=$("$@" 2>&1); then res "$name" PASS "$(echo "$out" | tail -1 | cut -c1-150)"; else res "$name" FAIL "$(echo "$out" | tail -3 | tr '\n' ' ' | cut -c1-300)"; fi; }
cleanup() {
  local rc=$?
  [ $KEEP = 1 ] && { echo "--keep: 프로젝트 $PROJECT, 레지스트리 $RPROJ, 작업 폴더 $W 를 남겼다"; return; }
  echo; echo "== 정리"
  dc "$PROJECT" --profile jobs down -v --remove-orphans >/dev/null 2>&1
  bash "$DEPLOY_ROOT/scripts/registry.sh" down -v >/dev/null 2>&1
  # 레지스트리에 올리려고 붙인 태그는 지운다. 로컬 빌드(deploy-build/*)는 --reuse-build 가 쓰도록 --keep-images 가 아니면 지운다
  for img in $("$DOCKER" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | tr -d '\r' | grep -E '^127\.0\.0\.1:[0-9]+/openit/'); do "$DOCKER" rmi -f "$img" >/dev/null 2>&1; done
  if [ $KEEPIMG = 0 ]; then for img in $("$DOCKER" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | tr -d '\r' | grep -E '^deploy-build/'); do "$DOCKER" rmi -f "$img" >/dev/null 2>&1; done; fi
  # 백업 도구가 만든 파일은 호스트 사용자 소유다
  rm -rf "$W" 2>/dev/null || "$DOCKER" run --rm -v "$(hostpath "$DEPLOY_ROOT/state"):/s" "$UTIL_REF" rm -rf "/s/e2e-$ID"
  echo "정리 완료 (프로젝트 $PROJECT, 레지스트리 $RPROJ, 이미지 deploy-build/*, 임시 폴더)"
  return $rc
}
trap cleanup EXIT

cat <<BANNER
=============================================================================
 E2E 합격 시나리오 실행 (프로젝트 $PROJECT)
 !! 시험 대역 사용 표시 !!
   - 단계 3 모델: GPU가 없어 model-runtime FakeBackend + 시험용 어댑터(test/fixtures/e2e-test-adapter)로 대신한다
   - 서비스 compose는 compose.test.yaml 로 덮어쓴다: survey-service의 I4/I6는 survey 리포지토리의 시험용 대역이다
   - 단계 6의 TraceEnvelope는 survey-service가 아니라 이 스크립트가 만든 시험 자료다
   - 시험 자료는 운영 설정(compose.yaml, config/)에 들어가지 않는다
=============================================================================
BANNER

echo "== 준비: 이미지 빌드, 임시 레지스트리, digest 잠금"
[ -d "$DEPLOY_ROOT/.venv" ] || python3 -m venv "$DEPLOY_ROOT/.venv"
"$VENV/bin/pip" install -q -r "$DEPLOY_ROOT/requirements.txt" setuptools wheel 2>&1 | tail -1
have_images() { [ -f "$DEPLOY_ROOT/build/images.env" ] && [ "$(wc -l < "$DEPLOY_ROOT/build/images.env")" -ge 4 ] && while read -r _ img _; do "$DOCKER" image inspect "$img" >/dev/null 2>&1 || return 1; done < "$DEPLOY_ROOT/build/images.env"; }
if [ $REUSE = 0 ] || ! have_images; then
  chk "빌드: 네 영역 이미지" bash "$DEPLOY_ROOT/scripts/build-images.sh"
fi
abort_if_failed() { [ "$FAILS" = 0 ] || { echo "준비 단계가 실패해 중단한다"; exit 1; }; }
abort_if_failed
"$VENV/bin/pip" install -q --force-reinstall --no-deps "$DEPLOY_ROOT"/build/ctx/ops-feedback/build/wheels/boundary_contracts-*.whl "$DEPLOY_ROOT"/build/ctx/survey-service/build/wheels/openit_survey_schema-*.whl 2>&1 | tail -1
grep -E '^(GATEWAY|REGISTRY|UTIL)_IMAGE=' "$DEPLOY_ROOT/locks/images.lock" > "$DEPLOY_LOCK"
chk "레지스트리 기동(빈 포트 선택)" bash "$DEPLOY_ROOT/scripts/registry.sh" up
chk "publish: push + digest 잠금" bash "$DEPLOY_ROOT/scripts/publish-images.sh"
chk "compose가 digest로만 이미지를 참조" bash "$DEPLOY_ROOT/scripts/check-compose.sh"
abort_if_failed
source "$DEPLOY_LOCK"; source "$DEPLOY_REGISTRY_ENV"   # export 하지 않는다(compose 변수 우선순위)
bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" "$SECRETS_DIR" >/dev/null
export TEST_SURVEY_TESTS_DIR; TEST_SURVEY_TESTS_DIR=$(hostpath "$DEPLOY_ROOT/build/ctx/survey-service/tests")

echo; echo "== 단계 9 앞부분: Compose에서 이미지로 서비스가 뜬다"
chk "compose up --wait (digest 이미지, 읽기 전용 루트, cap_drop ALL)" bash "$DEPLOY_ROOT/scripts/up.sh" "$PROJECT"
abort_if_failed
port() { port_of "${PROJECT}-$1-1" 8080; }
PQA=$(port question-authoring); PGATE=$(port release-gate); POPS=$(port ops-feedback-ingest); PSURVEY=$(port survey-service); PGW=$(port gateway)
echo "  Docker가 배정한 호스트 포트: gateway=$PGW qa=$PQA gate=$PGATE ops=$POPS survey=$PSURVEY"
getj() { curl -fsS -m 5 "http://127.0.0.1:$1$2"; }
for pair in "gateway:$PGW" "question-authoring:$PQA" "release-gate:$PGATE" "ops-feedback-ingest:$POPS" "survey-service:$PSURVEY"; do
  n=${pair%%:*}; p=${pair##*:}
  chk "/healthz $n" getj "$p" /healthz
  chk "/readyz $n" getj "$p" /readyz
done
chk "gateway: 공개 API 경로 없음(O06 대기) /v1/turns -> 404" bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:$PGW/v1/turns)\" = 404 ]"
# 네트워크 분리: edge 만 호스트 포트가 있고 나머지 네트워크는 internal, 서비스 사이는 선언한 네트워크로만 닿는다
reach() { "$DOCKER" exec "${PROJECT}-$1-1" python -c "import urllib.request;urllib.request.urlopen('http://$2:8080/healthz',timeout=3)" >/dev/null 2>&1; }
chk "도달 가능: survey-service -> ops-feedback-ingest (serving)" reach survey-service ops-feedback-ingest
chk "도달 가능: survey-service -> release-gate (serving)" reach survey-service release-gate
chk "도달 가능: release-gate -> question-authoring (release, I1)" reach release-gate question-authoring
blocked() { ! reach "$@"; }
chk "차단: survey-service -> question-authoring" blocked survey-service question-authoring
chk "차단: question-authoring -> ops-feedback-ingest" blocked question-authoring ops-feedback-ingest
chk "차단: ops-feedback-ingest -> question-authoring" blocked ops-feedback-ingest question-authoring
noegress() { ! "$DOCKER" exec "${PROJECT}-release-gate-1" python -c "import urllib.request;urllib.request.urlopen('http://1.1.1.1',timeout=3)" >/dev/null 2>&1; }
chk "내부 네트워크 밖으로 나가지 못함(release-gate -> 외부 인터넷)" noegress
# 컨테이너 규칙: 비root, digest 참조, 라벨
nonroot() { [ "$("$DOCKER" exec "${PROJECT}-$1-1" id -u | tr -d '\r')" != 0 ]; }
bydigest() { "$DOCKER" inspect "${PROJECT}-$1-1" --format '{{.Config.Image}}' | tr -d '\r' | grep -E '@sha256:[0-9a-f]{64}$'; }
labels() { local L; L=$("$DOCKER" image inspect "$1" --format '{{json .Config.Labels}}' | tr -d '\r'); echo "$L" | grep -q 'org.opencontainers.image.revision' && echo "$L" | grep -Eq "$2" && echo "$L" | cut -c1-200; }
for s in survey-service question-authoring ops-feedback-ingest release-gate; do
  chk "비root 실행 $s" nonroot "$s"
  chk "컨테이너가 digest로 만들어짐 $s" bydigest "$s"
done
chk "이미지 라벨(커밋, 계약·turn-engine·model-runtime 버전) survey-service" labels "${DEPLOY_REGISTRY}/openit/survey-service@${SURVEY_SERVICE_DIGEST}" 'io.openit.contracts.boundary.*io.openit.turn-engine.*io.openit.model-runtime|io.openit.turn-engine'
chk "이미지 라벨(커밋, 계약 버전) question-authoring" labels "${DEPLOY_REGISTRY}/openit/question-authoring@${QUESTION_AUTHORING_DIGEST}" 'openit.contract.boundary-contracts'
chk "이미지 라벨(커밋, 계약 버전) ops-feedback" labels "${DEPLOY_REGISTRY}/openit/ops-feedback@${OPS_FEEDBACK_DIGEST}" 'io.openit.contracts.boundary'
chk "이미지 라벨(커밋, 계약 버전) release-gate" labels "${DEPLOY_REGISTRY}/openit/release-gate@${RELEASE_GATE_DIGEST}" 'org.openit.boundary-contract-version'

echo; echo "== 단계 1~8"
IMAGES="{\"survey-service\":\"$DEPLOY_REGISTRY/openit/survey-service@$SURVEY_SERVICE_DIGEST\",\"question-authoring\":\"$DEPLOY_REGISTRY/openit/question-authoring@$QUESTION_AUTHORING_DIGEST\"}"
PORTS="{\"qa\":$PQA,\"gate\":$PGATE,\"ops\":$POPS,\"survey\":$PSURVEY}"
WP=""; [ "$DOCKER" = docker.exe ] && WP=wslpath
"$VENV/bin/python" "$DEPLOY_ROOT/scripts/e2e_steps.py" --project "$PROJECT" --secrets "$SECRETS_DIR" --ports "$PORTS" --images "$IMAGES" --docker "$DOCKER" --hostpath-prefix "$WP" --root "$DEPLOY_ROOT" | tee "$W/steps.log"
STEPS_RC=${PIPESTATUS[0]}
[ "$STEPS_RC" = 0 ] && res "단계 1~8 (REAL/TEST-SUB 항목의 스키마·해시 검증)" PASS "BLOCKED 항목은 아래 요약과 docs/change-requests 참고" || res "단계 1~8" FAIL "e2e_steps.py 종료 코드 $STEPS_RC"

echo; echo "== 단계 9: 주기 잡 스케줄러 (D39)"
chk "잡 엔트리포인트가 Compose 안에서 이미지·볼륨·네트워크로 실행된다(ops_feedback.job --help)" bash "$DEPLOY_ROOT/scripts/run-job.sh" job-ops-feedback python -m ops_feedback.job --help
chk "잡 설정이 없으면 run-job 은 거부(종료 코드 2)" bash -c "OPS_JOB_CONFIG=/nonexistent/job.yaml bash $DEPLOY_ROOT/scripts/run-job.sh job-ops-feedback; [ \$? = 2 ]"
mkdir -p "$W/sched"
cat > "$W/sched/jobs.yaml" <<YAML
jobs:
  - {name: test-fast, where: serving, command: ["bash","-c","echo run >> $W/sched/ran.txt"], interval_seconds: 3}
  - {name: test-undecided, where: serving, command: ["bash","-c","echo SHOULD-NOT-RUN >> $W/sched/ran.txt"], interval_seconds: null}
  - {name: test-gpu, where: gpu-external, command: ["bash","-c","echo SHOULD-NOT-RUN >> $W/sched/ran.txt"], interval_seconds: 3}
YAML
SCHED="$VENV/bin/python $DEPLOY_ROOT/scripts/scheduler.py --config $W/sched/jobs.yaml --state $W/sched/st.json"
$SCHED tick >/dev/null; $SCHED tick >/dev/null; sleep 3.5; $SCHED tick >/dev/null
chk "스케줄러: 기한이 되면 실행하고 기한 전 tick은 아무것도 안 한다(3초 주기, 3번 tick -> 2번 실행), 주기 미정·GPU 밖 잡은 실행 안 함" bash -c "[ \"\$(cat $W/sched/ran.txt)\" = \"\$(printf 'run\nrun')\" ] && echo '실행 2회, SHOULD-NOT-RUN 없음'"
chk "config/jobs.yaml: GPU 잡 3개는 gpu-external(이 Compose에 없음)" bash -c "[ \$(grep -c 'where: gpu-external' $DEPLOY_ROOT/config/jobs.yaml) = 3 ] && ! grep -E 'synthetic-data|model-lab|worker' $DEPLOY_ROOT/compose.yaml"

echo; echo "== 단계 9: 백업과 복구 (O16 미정: 설정으로만)"
chk "설정 파일이 없으면 백업 거부(종료 코드 2)" bash -c "BACKUP_CONFIG=$W/none.env bash $DEPLOY_ROOT/scripts/backup.sh; [ \$? = 2 ]"
printf 'BACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=\n' "$W/backups" > "$W/backup-bad.env"
chk "보관 기간이 비어 있으면 백업 거부" bash -c "BACKUP_CONFIG=$W/backup-bad.env bash $DEPLOY_ROOT/scripts/backup.sh; [ \$? = 2 ]"
printf '# 시험 전용 값(사용자 결정이 아니다)\nBACKUP_DIR=%s\nBACKUP_RETENTION_DAYS=7\n' "$W/backups" > "$W/backup-test.env"
export BACKUP_CONFIG="$W/backup-test.env"
# 서비스를 멈춘 뒤 지문을 잰다(쓰기가 없으므로 복구 뒤와 같아야 한다)
dc "$PROJECT" stop >/dev/null 2>&1
STORES="survey-data qa-data ops-data gate-data"
for s in $STORES; do bash "$DEPLOY_ROOT/scripts/fingerprint.sh" $s > "$W/fp-before-$s.json"; done
# 오래된 스냅샷을 하나 만들어 보관 기간 삭제를 시험한다
mkdir -p "$W/backups/qa-data/20200101T000000Z"; touch -d '2020-01-01' "$W/backups/qa-data/20200101T000000Z"
chk "백업(4개 저장소, SQLite backup API + 해시 MANIFEST)" bash "$DEPLOY_ROOT/scripts/backup.sh"
chk "보관 기간(7일)이 지난 스냅샷만 삭제" bash -c "[ ! -d $W/backups/qa-data/20200101T000000Z ] && [ \$(ls $W/backups/qa-data | wc -l) = 1 ]"
# 실제로 지우고 복구한다
dc "$PROJECT" down >/dev/null 2>&1
chk "볼륨 삭제(데이터를 실제로 지운다)" bash -c "$DOCKER volume rm ${PROJECT}_survey-data ${PROJECT}_qa-data ${PROJECT}_ops-data ${PROJECT}_gate-data >/dev/null"
chk "지운 뒤 지문이 달라졌다(빈 볼륨)" bash -c "[ \"\$(bash $DEPLOY_ROOT/scripts/fingerprint.sh qa-data)\" != \"\$(cat $W/fp-before-qa-data.json)\" ]"
for s in $STORES; do chk "복구 $s" bash -c "SN=\$(ls -d $W/backups/$s/2* | tail -1); [ -n \"\$SN\" ] && bash $DEPLOY_ROOT/scripts/restore.sh $s \"\$SN\" --yes"; done
for s in $STORES; do chk "복구 후 지문 일치 $s" bash -c "[ \"\$(bash $DEPLOY_ROOT/scripts/fingerprint.sh $s)\" = \"\$(cat $W/fp-before-$s.json)\" ]"; done
chk "복구 후 서비스 기동" bash "$DEPLOY_ROOT/scripts/up.sh" "$PROJECT"
PQA=$(port question-authoring); POPS=$(port ops-feedback-ingest)
TRACEKEYS=$("$VENV/bin/python" - <<'PY'
import survey_schema, json
sc = survey_schema.load_schema("TurnTrace"); sc = sc["$defs"]["TurnTrace"] if "TurnTrace" in sc.get("$defs", {}) else sc
print(json.dumps(list(sc.get("required") or sc["properties"])))
PY
)
chk "복구한 ops-feedback 저장소: 같은 Trace 재전송 -> DUPLICATE(복구한 데이터를 기억)" "$VENV/bin/python" - <<PY
import json, urllib.request
keys = json.loads('$TRACEKEYS'); t = {k: None for k in keys}; t.update(session_id="s-e2e-test", turn_id="t-e2e-test-1", contract_version=1)
env = {"pipeline_schema_version": "1.1", "release_id": "rel-e2e-test", "runtime_contract_version": 1, "session_id": "s-e2e-test", "turn_id": "t-e2e-test-1", "sent_at": "2026-10-15T00:00:00Z", "trace": t}
req = urllib.request.Request("http://127.0.0.1:$POPS/v1/traces", data=json.dumps(env).encode(), method="POST", headers={"Authorization": "Bearer $(cat "$SECRETS_DIR/tokens/ops-ingest-survey-service")", "Content-Type": "application/json"})
r = json.load(urllib.request.urlopen(req)); assert r["status"] == "DUPLICATE", r; print("DUPLICATE")
PY
chk "복구한 문항 저장소: 두 버전이 읽기 전용 SDK로 읽히고 해시가 맞다" "$VENV/bin/python" - <<PY
import json, subprocess
code = '''
import json
from question_authoring.store import SqliteQuestionStore
from boundary_contracts import canonical as c
r = SqliteQuestionStore("/data/questions.sqlite3", read_only=True).reader()
vs = r.list_versions("qs-e2e-test")[0]
assert [v["version"] for v in vs] == ["1", "2"], vs
for v in vs: assert c.content_hash(r.get_question_bank(v)) == v["content_hash"]
print("OK", len(vs))
'''
out = subprocess.run(["$DOCKER", "run", "--rm", "-i", "-v", "${PROJECT}_qa-data:/data:ro", "$DEPLOY_REGISTRY/openit/question-authoring@$QUESTION_AUTHORING_DIGEST", "python", "-"], input=code, capture_output=True, text=True)
assert out.returncode == 0, out.stderr[-300:]; print(out.stdout.strip())
PY

echo; echo "== 단계 9: digest 잠금으로 코드 축 롤백"
OLD_REF=$("$DOCKER" inspect "${PROJECT}-survey-service-1" --format '{{.Config.Image}}' | tr -d '\r')
chk "새 버전 빌드(시험: COMMIT 라벨에 -test2)" env BUILD_SUFFIX=-test2 bash "$DEPLOY_ROOT/scripts/build-images.sh" survey-service
chk "새 버전 publish -> 잠금 갱신(이전 잠금은 history에 보관)" bash "$DEPLOY_ROOT/scripts/publish-images.sh" survey-service
chk "새 잠금으로 적용 -> survey-service가 새 digest 이미지로 교체" bash -c "bash $DEPLOY_ROOT/scripts/up.sh $PROJECT >/dev/null && [ \"\$($DOCKER inspect ${PROJECT}-survey-service-1 --format '{{.Config.Image}}' | tr -d '\r')\" != \"$OLD_REF\" ]"
chk "롤백: 잠금을 이전 것으로 되돌리고 적용 -> 이전 digest 이미지로 복귀" bash -c "bash $DEPLOY_ROOT/scripts/rollback.sh $PROJECT >/dev/null && [ \"\$($DOCKER inspect ${PROJECT}-survey-service-1 --format '{{.Config.Image}}' | tr -d '\r')\" = \"$OLD_REF\" ]"
SP=$(port survey-service)
chk "롤백 뒤 survey-service /readyz" getj "$SP" /readyz

echo; echo "============================ 요약 ============================"
if [ -f "$W/steps.log" ]; then sed -n '/== 요약 (단계 1~8)/,$p' "$W/steps.log"; fi
echo "-- 9단계 및 준비 검사 (PASS/FAIL 개수)"
printf '   PASS %s / FAIL %s\n' "$(printf '%s\n' "${RESULT[@]}" | grep -c '|PASS|')" "$FAILS"
for r in "${RESULT[@]}"; do case "$r" in *"|FAIL|"*) echo "   FAIL: ${r%%|*}";; esac; done
echo "대신한 것: 단계 3(모델: FakeBackend + test 어댑터), 단계 6의 봉투(e2e가 만든 시험 자료), survey-service의 I4/I6(시험 대역)"
echo "막힌 것: 단계 2, 4(판정·릴리스), 5, 6(FailureCase), 7, 8(APPLIED). docs/change-requests/ 참고"
[ "$FAILS" = 0 ] && echo "E2E 결과: 실행한 검사 전부 통과 (BLOCKED 단계가 남아 있어 시나리오 전체 합격은 아니다)" || echo "E2E 결과: 실패 있음"
exit $([ "$FAILS" = 0 ] && echo 0 || echo 1)
