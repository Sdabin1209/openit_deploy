#!/usr/bin/env bash
# 지금 떠 있는 것을 보여 준다. 읽기만 한다(아무것도 바꾸지 않는다).
#   scripts/status.sh [프로젝트...]     기본: deploy deploy-demo deploy-registry
# 프로젝트마다 컨테이너 상태표, gateway 주소(Docker가 배정한 실제 호스트 포트), /readyz 요약(활성 릴리스, 승인 대기 수)을 낸다.
# 호스트 포트가 열려 있지 않은 서비스(상시 구성의 내부 서비스)는 /readyz 요약을 건너뛴다. 표준 docker 만 쓴다.
set -uo pipefail
case "${1:-}" in -h|--help) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0;; esac
source "$(dirname "$0")/lib.sh"
PROJECTS=("$@"); [ ${#PROJECTS[@]} -gt 0 ] || PROJECTS=(deploy deploy-demo deploy-registry)
for p in "${PROJECTS[@]}"; do case "$p" in deploy|deploy-*) ;; *) die "프로젝트 이름은 deploy 로 시작해야 한다: $p";; esac; done

# 서비스 이름 -> 내부 포트(레지스트리는 5000, 나머지 8080)
probe() { # probe <프로젝트> : 호스트 포트가 열린 서비스의 /readyz 를 요약한다
  local p=$1 s json="{" first=1 hp
  for s in survey-service release-gate question-authoring ops-feedback-ingest model-registry model-serving gateway; do
    hp=$("$DOCKER" port "$p-$s-1" 8080/tcp 2>/dev/null | head -1 | tr -d '\r' | sed 's/.*://')
    [ -n "$hp" ] || continue
    [ $first = 1 ] || json+=","; first=0; json+="\"$s\":$hp"
  done
  json+="}"
  [ "$json" = "{}" ] && { echo "  (호스트 포트가 열린 서비스 없음: /readyz 요약 생략)"; return; }
  python3 -I - "$json" <<'PY'
import json, sys, urllib.request, urllib.error
ports = json.loads(sys.argv[1])
def get(name, path="/readyz"):
    """(코드, 본문 사전). 본문이 JSON이 아니면(gateway는 평문 ok) 빈 사전. 연결 실패는 (0, {'error':..})."""
    url = f"http://127.0.0.1:{ports[name]}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r: code, raw = r.status, r.read()
    except urllib.error.HTTPError as e: code, raw = e.code, e.read()
    except Exception as e: return 0, {"error": str(e)[:60]}
    try: d = json.loads(raw or b"{}")
    except ValueError: return code, {}
    return code, d if isinstance(d, dict) else {}
for name in ("survey-service", "release-gate", "question-authoring", "ops-feedback-ingest", "model-registry", "model-serving", "gateway"):
    if name not in ports: continue
    c, d = get(name, "/healthz" if name == "gateway" else "/readyz")   # gateway 평문 포트는 /healthz 만 답한다(/readyz 는 HTTPS)
    extra = ""
    if name == "survey-service": extra = f": ready={d.get('ready')} active_release={d.get('active_release')} problems={d.get('problems')}"
    if name == "release-gate": extra = f": judging={d.get('judging')} awaiting_approval={d.get('awaiting_approval')}"
    if name == "survey-service" and d.get("inference"): extra += f" inference={json.dumps(d.get('inference'), ensure_ascii=False)[:160]}"
    if name == "model-serving": extra = f": {d.get('status')} 사유={d.get('reason') or '-'} (not ready + 사유 '백엔드를 올리는 중' 이면 모델 내려받기·적재 중)" + (" -> 모델 캐시 쓰기 불가 가능성: HF 볼륨 소유자 확인(docs/RUN.md '모델 캐시가 쓰기 불가일 때'), scripts/demo.sh diag" if "OSError" in str(d.get('reason')) else "")
    if c == 0: extra = f" ({d.get('error')})"
    print(f"  {name:20} /readyz {c}{extra}")
PY
}

any=0
for p in "${PROJECTS[@]}"; do
  rows=$("$DOCKER" ps -a --filter "label=com.docker.compose.project=$p" --format '{{.Names}}\t{{.Status}}' 2>/dev/null | sort)
  [ -n "$rows" ] || continue
  any=1
  echo "== 프로젝트 $p"
  printf '%s\n' "$rows" | sed 's/^/  /'
  gw=$("$DOCKER" port "$p-gateway-1" 8080/tcp 2>/dev/null | head -1 | tr -d '\r' | sed 's/.*://')
  [ -n "$gw" ] && gws=$("$DOCKER" port "$p-gateway-1" 8443/tcp 2>/dev/null | head -1 | tr -d '\r' | sed 's/.*://'); echo "  gateway 주소: https://127.0.0.1:${gws:-?} (HTTPS, 내부 CA), 평문 http://127.0.0.1:$gw 는 /healthz 만 답하고 나머지는 308  (바인드 주소가 127.0.0.1 이 아니면 그 주소로)"
  rp=$("$DOCKER" port "$p" 5000/tcp 2>/dev/null | head -1 | tr -d '\r' | sed 's/.*://')
  [ -n "$rp" ] && echo "  레지스트리 주소: 127.0.0.1:$rp"
  probe "$p"
  vols=$("$DOCKER" volume ls -q --filter "label=com.docker.compose.project=$p" 2>/dev/null | wc -l)
  echo "  볼륨 $vols 개 (내리기: scripts/down.sh $p --stop|--remove|--purge)"
done
hf_cache_report
if [ $any = 0 ]; then
  echo "떠 있거나 멈춘 프로젝트가 없다 (${PROJECTS[*]})."
  echo "다음: scripts/registry.sh up  ->  scripts/up.sh deploy  (상시 구성)   또는   scripts/demo.sh up  (눈으로 보는 데모)"
fi
