#!/usr/bin/env bash
# 비밀 노출 표준 검사(D84). 사용: check-secrets-hidden.sh [프로젝트 ...]  (기본: $DEPLOY_PROJECT 또는 deploy)
#   환경: SECRETS_DIR(기본 secrets/), COMPOSE_EXTRA(dc 와 같음), DOCKER
# 정적: compose 병합 결과(--profile jobs)에서 비밀 이름(…TOKEN/TOKENS/SALT/PASSWORD/SECRET/PRIVATE_KEY/API_KEY)에 값이 직접 들어 있으면 실패,
#       NAME_FILE=/run/secrets/<이름> 이 그 서비스의 secrets 마운트와 맞지 않으면 실패.
# 동적: 떠 있는 프로젝트의 컨테이너마다 `docker inspect`(Env, Cmd, Entrypoint)와 `docker exec env`(또는 /proc/1/environ)에
#       secrets 파일의 값이 하나라도 들어 있으면 실패.
# 값은 절대 출력하지 않는다: 출력은 컨테이너 이름, 변수 이름(또는 Cmd/Entrypoint), 개수뿐이다. 비교는 파일 내용을 읽어 포함 여부만 판정한다.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
SD=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}
PROJECTS=("$@"); [ ${#PROJECTS[@]} -gt 0 ] || PROJECTS=("${DEPLOY_PROJECT:-deploy}")
[ -d "$SD/tokens" ] || die "비밀 폴더가 없다: $SD/tokens (먼저 scripts/gen-secrets.sh)"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
rc=0
for P in "${PROJECTS[@]}"; do
  if [ "${CHECK_SECRETS_SKIP_STATIC:-0}" = 1 ]; then echo '{"services":{}}' > "$TMP/$P.json"   # 자기 점검용(compose 없이 동적 검사만)
  else dc "$P" --profile jobs config --format json > "$TMP/$P.json" 2>"$TMP/$P.err"; fi || { echo "오류: compose config 실패($P): $(tail -2 "$TMP/$P.err" | tr '\n' ' ' | cut -c1-200)" >&2; rc=1; continue; }
  "$DOCKER" ps --filter "label=com.docker.compose.project=$P" --format '{{.Names}}' | tr -d '\r' > "$TMP/$P.names"
  DOCKER_BIN="$DOCKER" python3 - "$P" "$SD/tokens" "$TMP/$P.json" "$TMP/$P.names" <<'PY' || rc=1
import json, os, pathlib, re, subprocess, sys
proj, tokdir, cfgf, namesf = sys.argv[1:5]
docker = os.environ["DOCKER_BIN"]
fails = []; unchecked = []

# 1) 비밀 값 모으기(파일 내용을 읽어 메모리에만 둔다. 목록 값은 조각도 따로: 역할=토큰, 토큰:actor:역할)
vals = {}; short = 0
for f in sorted(pathlib.Path(tokdir).iterdir()):
    if not f.is_file(): continue
    v = f.read_text(errors="ignore").strip()
    parts = {v}
    for item in v.split(","):   # 목록 값: 역할=토큰 -> 토큰, 토큰:actor:역할 -> 토큰 (역할·actor 이름은 비밀이 아니다)
        parts.add(item.split("=", 1)[1] if "=" in item else item.split(":", 1)[0])
    for p in parts:
        p = p.strip()
        if len(p) >= 16: vals[p] = f.name
        elif p == v and p: short += 1
print(f"[{proj}] 비밀 파일 {sum(1 for f in pathlib.Path(tokdir).iterdir() if f.is_file())}개에서 비교할 값 {len(vals)}개 (너무 짧아 비교하지 않은 값 {short}개)")
def leaks(text): return any(v in text for v in vals)

# 2) 정적: compose 병합 결과
cfg = json.load(open(cfgf))
NAMEPAT = re.compile(r"(TOKEN|TOKENS|SALT|PASSWORD|SECRET|PRIVATE_KEY|API_KEY)$")
for sname, svc in sorted(cfg.get("services", {}).items()):
    env = svc.get("environment") or {}
    if isinstance(env, list): env = dict(e.split("=", 1) if "=" in e else (e, "") for e in env)
    mounted = {(s if isinstance(s, str) else s.get("source")) for s in (svc.get("secrets") or [])}
    for k, v in env.items():
        if NAMEPAT.search(k) and v not in (None, ""):
            fails.append(f"정적 {sname}: 환경 변수 {k} 에 값이 직접 들어 있다(NAME_FILE 로 줄 것)")
        if k.endswith("_FILE") and isinstance(v, str) and v.startswith("/run/secrets/"):
            if v.rsplit("/", 1)[1] not in mounted:
                fails.append(f"정적 {sname}: {k} 가 가리키는 {v} 에 대응하는 secrets 마운트가 없다")
        if isinstance(v, str) and leaks(v):
            fails.append(f"정적 {sname}: 환경 변수 {k} 가 secrets 파일의 값을 담고 있다")
    for k in ("command", "entrypoint"):
        if leaks(json.dumps(svc.get(k) or "")): fails.append(f"정적 {sname}: {k} 에 secrets 파일의 값이 들어 있다")

# 3) 동적: 떠 있는 컨테이너
names = [n for n in pathlib.Path(namesf).read_text().split() if n]
def run(*a):
    r = subprocess.run([docker, *a], capture_output=True, text=True, errors="ignore")
    return r.returncode, r.stdout
for c in names:
    rcode, out = run("inspect", c, "--format", "{{json .Config.Env}}|{{json .Config.Cmd}}|{{json .Config.Entrypoint}}")
    if rcode != 0: unchecked.append(f"{c}: docker inspect 실패"); continue
    envj, cmdj, epj = out.strip().split("|", 2)
    for e in json.loads(envj) or []:
        k, _, v = e.partition("=")
        if leaks(v): fails.append(f"동적 {c}: docker inspect Env 의 {k} 에 secrets 파일의 값이 있다")
    for label, j in (("Cmd", cmdj), ("Entrypoint", epj)):
        if leaks(j): fails.append(f"동적 {c}: docker inspect {label} 에 secrets 파일의 값이 있다")
    seen = False
    rcode, out = run("exec", c, "env")
    if rcode == 0:
        seen = True
        for line in out.splitlines():
            k, _, v = line.partition("=")
            if leaks(v): fails.append(f"동적 {c}: docker exec env 의 {k} 에 secrets 파일의 값이 있다")
    rcode, out = run("exec", c, "cat", "/proc/1/environ")
    if rcode == 0:
        seen = True
        for item in out.split("\0"):
            k, _, v = item.partition("=")
            if leaks(v): fails.append(f"동적 {c}: /proc/1/environ 의 {k} 에 secrets 파일의 값이 있다")
    if not seen: unchecked.append(f"{c}: 컨테이너 안에서 env 도 /proc/1/environ 도 읽지 못했다(inspect 만 확인)")
print(f"[{proj}] 정적: 서비스 {len(cfg.get('services', {}))}개 / 동적: 실행 중인 컨테이너 {len(names)}개 검사")
for u in unchecked: print(f"  확인 못 함: {u}")
for f in fails: print("  실패:", f)
if fails: print(f"[{proj}] 실패 {len(fails)}건"); sys.exit(1)
print(f"[{proj}] 통과: 환경 변수에 비밀 값이 없다" + (f" (확인 못 한 컨테이너 {len(unchecked)}개)" if unchecked else ""))
PY
done
exit $rc
