#!/usr/bin/env bash
# 기본값이 아닌 SECRETS_GID·STEP_CERT_GID 로 compose 를 병합해, 파일을 쓰는 쪽의 그룹과 읽는 쪽의 group_add 가 같은지 정적으로 본다(컨테이너를 띄우지 않는다. 비밀 값은 출력하지 않는다).
# 왜: 기본값(id -g, 10100)에서는 어긋나도 우연히 맞아 드러나지 않는다. 운영자가 다른 값을 주면 키 파일이 읽는 쪽 그룹과 달라져 서비스가 인증서·비밀을 못 읽는다(ADR 0054, 계약 StepCaEnv.STEP_CERT_GID).
set -uo pipefail
source "$(dirname "$0")/lib.sh"; source "$(dirname "$0")/testlib.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export DEPLOY_LOCK=$T/images.lock DEPLOY_REGISTRY_ENV=$T/registry.env SECRETS_DIR=$T/secrets
test_lock_copy "$DEPLOY_LOCK"; echo "DEPLOY_REGISTRY=127.0.0.1:5000" > "$DEPLOY_REGISTRY_ENV"
bash "$DEPLOY_ROOT/scripts/gen-secrets.sh" --test-fixtures "$SECRETS_DIR" >/dev/null 2>&1
export SECRETS_GID=4242 STEP_CERT_GID=4343
COMPOSE_EXTRA="" dc gid-wiring config > "$T/prod.yaml" 2>"$T/err" || { cat "$T/err" | tail -3; echo "FAIL compose 병합"; exit 1; }
"$DEPLOY_PY" -I - "$T/prod.yaml" <<'PY'
import sys, yaml
svc = yaml.safe_load(open(sys.argv[1]))["services"]
bad = []
gids = lambda s: {str(g) for g in (s.get("group_add") or [])}
env = lambda s: s.get("environment") or {}
certvols = {}
for n, s in svc.items():
    if env(s).get("STEP_ROLE") == "cert":
        if str(env(s).get("STEP_CERT_GID")) != "4343": bad.append(f"{n}: role=cert 인데 STEP_CERT_GID 가 4343 이 아니다({env(s).get('STEP_CERT_GID')!r}): 인증서 파일 그룹이 읽는 쪽 group_add 와 어긋난다")
        for v in s.get("volumes") or []:
            if isinstance(v, dict) and v.get("type") == "volume" and not v.get("read_only"): certvols[v["source"]] = n
for n, s in svc.items():
    if s.get("secrets") and "4242" not in gids(s): bad.append(f"{n}: 비밀 파일을 받는데 group_add 에 SECRETS_GID(4242)가 없다: {sorted(gids(s))}")
    for v in s.get("volumes") or []:
        if isinstance(v, dict) and v.get("type") == "volume" and v.get("source") in certvols and certvols[v["source"]] != n and env(s).get("STEP_ROLE") != "cert":
            if "4343" not in gids(s): bad.append(f"{n}: 인증서 볼륨 {v['source']}({certvols[v['source']]} 가 씀)을 읽는데 group_add 에 STEP_CERT_GID(4343)가 없다: {sorted(gids(s))}")
print("\n".join("  FAIL " + b for b in bad) if bad else "  PASS 기본값이 아닌 SECRETS_GID·STEP_CERT_GID 에서 쓰는 쪽 그룹과 읽는 쪽 group_add 가 같다")
sys.exit(1 if bad else 0)
PY
py_rc=$?
# 분리 배치(ansible)도 같은 값을 compose 에 넘긴다: 인벤토리의 placement_step_cert_gid 가 없으면 빈 값(compose 의 :-기본값이 적용된다)
if [ "$(grep -c 'STEP_CERT_GID="{{ placement_step_cert_gid' "$DEPLOY_ROOT/ansible/stage.yml")" -ge 2 ]; then echo "  PASS 분리 배치가 STEP_CERT_GID 를 compose 에 넘긴다(stage.yml 두 곳)"; else echo "  FAIL ansible/stage.yml 의 compose 호출이 STEP_CERT_GID 를 넘기지 않는다"; rc2=1; fi
rc=$py_rc; [ "${rc2:-0}" = 0 ] || rc=1; [ $rc = 0 ] && echo "test-gid-wiring: 전부 통과" || echo "test-gid-wiring: 실패"; exit $rc
