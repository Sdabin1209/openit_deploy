#!/usr/bin/env bash
# 정적 시험(Docker 불필요): DB 접속에 sslrootcert=<경로> 를 쓰는 모든 서비스가 그 경로의 루트 인증서 파일을 실제로 마운트하는지 compose.yaml 에서 읽어 확인한다. 빠지면 실패.
# 근거: verify-full 연결은 루트 파일이 없으면 기동 때가 아니라 첫 접속 때 실패한다(분리 배치 시험에서 DSN 의 sslrootcert 경로를 쓰게 됐다, ADR 0061).
# 대상: (1) db-*-dsn 비밀을 마운트하는 서비스: 경로는 db_secrets 컴포넌트가 접속 URI 에 넣는 값  (2) 환경·명령 문자열에 sslrootcert=<경로> 가 직접 있는 서비스(keycloak, postgres-reload 등)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${DEPLOY_PY:-}; [ -n "$PY" ] || for c in "$PWD/.venv/bin/python" "$PWD/../../.venv/bin/python" python3; do command -v "$c" >/dev/null 2>&1 && PY=$c && break; done
"$PY" - <<'PYEOF'
import re, sys, yaml
c = yaml.safe_load(open("compose.yaml", encoding="utf-8"))
gen = open("openit_deploy/components/db_secrets.py", encoding="utf-8").read()   # 접속 URI 의 sslrootcert 경로는 컴포넌트 db_secrets 가 정한다(계약 3.4.12)
dsn_paths = set(re.findall(r"DEFAULT_ROOT_CA = \"(/[^\"]+)\"", gen))
if len(dsn_paths) != 1:
    sys.exit("FAIL: db_secrets 의 DEFAULT_ROOT_CA 경로가 하나가 아니다: %s" % sorted(dsn_paths))
dsn_path = dsn_paths.pop()
def mounts(s):
    out = []
    for v in s.get("volumes") or []:
        if isinstance(v, str):
            parts = v.split(":"); out.append((parts[0], parts[1] if len(parts) > 1 else ""))
        else:
            out.append((v.get("source", ""), v.get("target", "")))
    return out
def has(s, path):
    d = path.rsplit("/", 1)[0]
    return any(src == "pki-root" and tgt == d for src, tgt in mounts(s))
fails, checked = [], 0
for n, s in c["services"].items():
    sec = [x if isinstance(x, str) else x["source"] for x in (s.get("secrets") or [])]
    need = set()
    if any(re.match(r"^db-.*-dsn$", x) for x in sec):
        need.add(dsn_path)
    blob = " ".join([str(s.get("environment")), str(s.get("entrypoint")), str(s.get("command"))])
    need |= set(re.findall(r"sslrootcert=(/[^\s\"';&]+)", blob))
    for p in sorted(need):
        checked += 1
        if not has(s, p):
            fails.append("%s: sslrootcert=%s 인데 pki-root 를 %s 에 마운트하지 않는다" % (n, p, p.rsplit("/", 1)[0]))
for f in fails:
    print("FAIL: " + f, file=sys.stderr)
if fails or checked == 0:
    sys.exit(1)
print("OK: sslrootcert 를 쓰는 서비스 %d곳이 모두 루트 파일을 마운트한다" % checked)
PYEOF
