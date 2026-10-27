#!/usr/bin/env bash
# check-health.sh 자체 시험(Docker 불필요): 가짜 스케줄러 상태, 가짜 디스크 한계, 로컬 HTTP 서버로 OK/WARN/CRIT/SKIP 과 종료 코드를 확인한다. 사용: bash scripts/test-check-health.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; T=$(mktemp -d); trap 'kill $SP 2>/dev/null; rm -rf "$T"' EXIT
N=0; F=0
t() { local name=$1 want_rc=$2 want_txt=$3; shift 3; local out rc; out=$(bash "$HERE/check-health.sh" "$@" 2>&1); rc=$?; N=$((N+1))
  if [ $rc = "$want_rc" ] && grep -qF -- "$want_txt" <<<"$out"; then echo "  PASS $name"; else echo "  FAIL $name (종료 $rc, 기대 $want_rc, '$want_txt')"; echo "$out" | sed 's/^/       /'; F=$((F+1)); fi; }
NOW=1000000
cat > $T/jobs.yaml <<'Y'
jobs:
  - {name: a, where: serving, command: ["x"], interval_seconds: 100}
  - {name: g, where: gpu-external, command: ["x"], interval_seconds: null}
  - {name: u, where: serving, command: ["x"], interval_seconds: null}
Y
cat > $T/mon.yaml <<'Y'
targets:
  - {name: none, url: null}
Y
base=(--jobs $T/jobs.yaml --monitor $T/mon.yaml --disk-path $T --now $NOW)
echo '{"a":{"last_start":999950,"last_end":999951,"last_exit":0}}' > $T/s.json
t "정상: 종료 코드 0, 위치 밖·주기 미정·url 미정은 SKIP 으로 따로 센다" 0 "SKIP(확인 못 함, 통과 아님) 3" "${base[@]}" --scheduler-state $T/s.json
echo '{"a":{"last_start":999950,"last_end":999951,"last_exit":3,"last_msg":"boom"}}' > $T/s.json
t "잡의 마지막 종료 코드가 0이 아니면 CRIT(2)" 2 "마지막 종료 코드 3" "${base[@]}" --scheduler-state $T/s.json
echo '{"a":{"last_start":999000,"last_end":999001,"last_exit":0}}' > $T/s.json
t "주기의 2배를 넘게 실행이 없으면 CRIT" 2 "주기 100초" "${base[@]}" --scheduler-state $T/s.json
echo '{"a":{"last_start":990000,"last_exit":0}}' > $T/s.json
t "시작했지만 상한을 넘겨 끝나지 않으면 CRIT" 2 "아직 끝나지 않았다" "${base[@]}" --scheduler-state $T/s.json --stuck-seconds 3600
echo '{}' > $T/s.json
t "실행 기록이 없으면 WARN(1)" 1 "실행 기록이 없다" "${base[@]}" --scheduler-state $T/s.json
t "상태 파일이 없으면 WARN" 1 "스케줄러 상태 파일" "${base[@]}" --scheduler-state $T/none.json
echo '{"a":{"last_start":999950,"last_end":999951,"last_exit":0}}' > $T/s.json
t "디스크 한계를 0%로 낮추면 CRIT" 2 "디스크" "${base[@]}" --scheduler-state $T/s.json --disk-crit 0 --disk-warn 0
t "없는 경로는 SKIP(확인 못 함)" 0 "경로가 없어" "${base[@]}" --scheduler-state $T/s.json --disk-path $T/nope
python3 -I - "$T" <<'PY' &
import http.server, sys, threading
import json, time
GATE = {"judging": "enabled", "judging_loop": {"last_run_at": 1000000 - 5, "consecutive_failures": 0, "last_error": None, "upstream_auth_failed": False}}
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(s):
        if s.path.startswith("/gate/"):
            mode = s.path.split("/")[2]; d = json.loads(json.dumps(GATE)); jl = d["judging_loop"]; code = 200
            if mode == "auth": jl["upstream_auth_failed"] = True
            if mode == "fail1": jl["consecutive_failures"] = 1; jl["last_error"] = {"code": "UNAVAILABLE"}
            if mode == "fail3": jl["consecutive_failures"] = 3; jl["last_error"] = {"code": "UNAVAILABLE"}
            if mode == "stale": jl["last_run_at"] = 1000000 - 5000
            if mode == "never": jl["last_run_at"] = None
            if mode == "nojl": del d["judging_loop"]
            if mode == "down": code = 503; d = {"status": "not ready", "reason": "x"}
            b = json.dumps(d).encode(); s.send_response(code); s.end_headers(); s.wfile.write(b); return
        if s.path.startswith("/ms/"): c = 200 if s.path.endswith("ok") else 503; s.send_response(c); s.end_headers(); s.wfile.write(b'{"status":"not-ready","reason":"engine stuck"}' if c == 503 else b'{"ready":true}'); return
        s.send_response(200 if s.path == "/healthz" else 503); s.end_headers(); s.wfile.write(b"x")
    def log_message(*a): pass
srv = http.server.HTTPServer(("127.0.0.1", 0), H); open(sys.argv[1] + "/port", "w").write(str(srv.server_port)); srv.serve_forever()
PY
SP=$!; for i in $(seq 1 50); do [ -s $T/port ] && break; sleep 0.1; done; P=$(cat $T/port)
printf 'targets:\n  - {name: h, url: "http://127.0.0.1:%s/healthz", expect_status: 200}\n' $P > $T/mon.yaml
t "외부 감시 대상이 기대 코드면 OK" 0 "감시 h: http://127.0.0.1:$P/healthz -> 200" "${base[@]}" --scheduler-state $T/s.json
printf 'targets:\n  - {name: r, url: "http://127.0.0.1:%s/readyz", expect_status: 200}\n' $P > $T/mon.yaml
t "외부 감시 대상이 다른 코드면 CRIT" 2 "-> 503 (기대 200)" "${base[@]}" --scheduler-state $T/s.json
printf 'targets:\n  - {name: d, url: "http://127.0.0.1:1/healthz"}\n' > $T/mon.yaml
t "닿지 못하면 CRIT" 2 "닿지 못했다" "${base[@]}" --scheduler-state $T/s.json
mon0=(--monitor $T/mon.yaml); printf 'targets: []\n' > $T/mon.yaml
rz() { echo "--readyz release-gate=http://127.0.0.1:$P/gate/$1"; }
t "release-gate 판정 루프 정상이면 OK" 0 "연속 실패 0" "${base[@]}" --scheduler-state $T/s.json $(rz ok)
t "연속 실패 1회는 WARN(1)" 1 "연속 실패 1회" "${base[@]}" --scheduler-state $T/s.json $(rz fail1)
t "연속 실패 3회는 CRIT(2)" 2 "연속 실패 3회" "${base[@]}" --scheduler-state $T/s.json $(rz fail3)
t "upstream_auth_failed 는 CRIT" 2 "upstream_auth_failed" "${base[@]}" --scheduler-state $T/s.json $(rz auth)
t "last_run_at 이 오래되면 WARN" 1 "초 전이다" "${base[@]}" --scheduler-state $T/s.json $(rz stale)
t "last_run_at 이 없으면 WARN" 1 "한 번도 돌지 않았다" "${base[@]}" --scheduler-state $T/s.json $(rz never)
t "judging_loop 가 없으면 SKIP(통과 아님)" 0 "judging_loop 가 없다" "${base[@]}" --scheduler-state $T/s.json $(rz nojl)
t "release-gate /readyz 503 은 CRIT" 2 "-> 503" "${base[@]}" --scheduler-state $T/s.json $(rz down)
t "model-serving /readyz 200 은 OK" 0 "엔진 정상" "${base[@]}" --scheduler-state $T/s.json --readyz model-serving=http://127.0.0.1:$P/ms/ok
t "model-serving /readyz 503(엔진 멈춤)은 CRIT" 2 "engine stuck" "${base[@]}" --scheduler-state $T/s.json --readyz model-serving=http://127.0.0.1:$P/ms/down
t "컨테이너가 없는 프로젝트는 SKIP" 0 "컨테이너가 없거나" "${base[@]}" --scheduler-state $T/s.json --project deploy-nonexistent-xyz
[ $F = 0 ] && echo "통과: check-health 자체 시험 $N건" || { echo "실패: $F/$N건"; exit 1; }
