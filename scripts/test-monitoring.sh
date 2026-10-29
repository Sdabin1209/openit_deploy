#!/usr/bin/env bash
# 감시 스택 시험(ADR 0037). 1) 정적: promtool check config/rules + test rules(경보 경계), 변이 시험(임계값을 바꾸면 test rules 가 실패해야 한다), amtool, blackbox --config.check
#                              2) 동적(Docker): 가짜 서비스와 스택을 임시 프로젝트로 띄워 탐침 성공, 판정 루프 지표, 디스크·textfile 지표, 실패 주입 시 경보 firing 을 Prometheus/Alertmanager API 로 확인한다.
# 사용: test-monitoring.sh [--static]   (--static: Docker 가 필요한 동적 시험을 건너뛴다. 건너뛴 사실을 SKIP 으로 낸다)
set -uo pipefail
DEPLOY_NO_DOCKER=1; source "$(dirname "$0")/lib.sh"; detect_docker
LOCK="$DEPLOY_ROOT/locks/images.lock"; img(){ sed -n "s/^$1=//p" "$LOCK"; }
PROM=$(img PROMETHEUS_IMAGE); AM=$(img ALERTMANAGER_IMAGE); BB=$(img BLACKBOX_IMAGE); JE=$(img JSON_EXPORTER_IMAGE); NE=$(img NODE_EXPORTER_IMAGE)
P="$DEPLOY_ROOT/config/prometheus"; rc=0; n=0
ok(){ echo "  ok   $*"; n=$((n+1)); }; no(){ echo "  FAIL $*"; rc=1; }
pt(){ "$DOCKER" run --rm -v "$P:/p:ro" --entrypoint promtool "$PROM" "$@"; }
# promtool 은 prometheus.yml 의 rule_files 경로(/etc/prometheus/...)를 컨테이너 안에서 본다: 같은 경로로 마운트해 점검한다
"$DOCKER" run --rm -v "$P/prometheus.yml:/etc/prometheus/prometheus.yml:ro" -v "$P/rules:/etc/prometheus/rules:ro" -v "$P/external-targets.yml:/etc/prometheus/external-targets.yml:ro" --entrypoint promtool "$PROM" check config /etc/prometheus/prometheus.yml >/dev/null 2>&1 && ok "promtool check config" || no "promtool check config"
pt check rules /p/rules/openit.yml >/dev/null 2>&1 && ok "promtool check rules" || no "promtool check rules"
out=$(pt test rules /p/rules/openit_test.yml 2>&1) && ok "promtool test rules(경보 경계: 디스크 80/90, 탐침, 판정 루프 1/3회·인증·900초, 잡 실패·2배+60초)" || { no "promtool test rules"; echo "$out" | tail -8; }
# 변이 시험: 임계값을 바꾼 규칙 사본은 같은 test 에 실패해야 한다(시험이 경계를 실제로 잡는다는 증거)
M=$(mktemp -d); trap 'rm -rf "$M"; [ -z "${PROJ:-}" ] || dc_mon down -v --remove-orphans >/dev/null 2>&1; [ -z "${FS:-}" ] || rm -rf "$FS"' EXIT
sed 's/>= 80 and/>= 85 and/; s/> 2 \* openit_job_interval_seconds + 60/> 3 * openit_job_interval_seconds + 60/; s/>= 3$/>= 4/' "$P/rules/openit.yml" > "$M/openit.yml"; cp "$P/rules/openit_test.yml" "$M/"
"$DOCKER" run --rm -v "$M:/m:ro" --entrypoint promtool "$PROM" test rules /m/openit_test.yml >/dev/null 2>&1 && no "변이한 규칙이 시험을 통과한다(시험이 경계를 못 잡는다)" || ok "변이 시험: 임계값을 바꾼 규칙은 test rules 가 거부한다"
"$DOCKER" run --rm -v "$P/alertmanager.yml:/a.yml:ro" --entrypoint amtool "$AM" check-config /a.yml >/dev/null 2>&1 && ok "amtool check-config" || no "amtool check-config"
"$DOCKER" run --rm -v "$P/blackbox.yml:/b.yml:ro" "$BB" --config.check --config.file=/b.yml >/dev/null 2>&1 && ok "blackbox --config.check" || no "blackbox --config.check"
if [ "${1:-}" = --static ]; then echo "  SKIP 동적 시험(--static): 통과로 세지 않는다"; [ $rc = 0 ] && echo "통과(정적만): 감시 스택 ${n}건" || echo "실패"; exit $rc; fi

# ---- 동적 ----
PROJ=deploy-montest-$$; FS=$(mktemp -d); chmod 755 "$FS"; echo ok > "$FS/mode"; chmod 644 "$FS/mode"
MET="$FS/metrics"; mkdir -p "$MET"; chmod 755 "$MET"
# 가짜 서비스 파일의 상대 경로(./test/monitoring/…)는 프로젝트 디렉터리(deploy 루트) 기준으로 쓰여 있어 사본 없이 그대로 쓴다(check-all 규칙 11 이 같은 기준으로 확인한다)
FAKE_COMPOSE="$DEPLOY_ROOT/test/monitoring/compose.fake.yaml"
dc_mon(){ FAKE_STATE_DIR="$FS" METRICS_DIR="$MET" "$DOCKER" compose -p "$PROJ" --project-directory "$DEPLOY_ROOT" -f "$DEPLOY_ROOT/compose.monitoring.yaml" -f "$FAKE_COMPOSE" --env-file "$LOCK" "$@"; }
SERVICE_RESULT=success METRICS_DIR="$MET" bash "$DEPLOY_ROOT/scripts/job-metrics.sh" demo 600
SERVICE_RESULT=exit-code EXIT_STATUS=1 METRICS_DIR="$MET" bash "$DEPLOY_ROOT/scripts/job-metrics.sh" brokenjob 600
dc_mon up -d >/dev/null 2>&1 || { no "스택을 띄우지 못했다"; dc_mon logs --tail 20 2>&1 | tail -20; exit 1; }
PP=$("$DOCKER" port "${PROJ}-prometheus-1" 9090/tcp | head -1 | sed 's/.*://'); AP=$("$DOCKER" port "${PROJ}-alertmanager-1" 9093/tcp | head -1 | sed 's/.*://')
q(){ curl -s --max-time 5 "http://127.0.0.1:$PP/api/v1/query" --data-urlencode "query=$1" | python3 -c 'import json,sys;d=json.load(sys.stdin);r=d["data"]["result"];print(r[0]["value"][1] if r else "")'; }
waitfor(){ local t=$1 what=$2; shift 2; local i; for i in $(seq 1 "$t"); do v=$("$@" 2>/dev/null) && [ -n "$v" ] && { echo "$v"; return 0; }; sleep 3; done; return 1; }
v=$(waitfor 40 probe curl -s "http://127.0.0.1:$PP/-/ready") && ok "Prometheus ready" || { no "Prometheus가 준비되지 않았다"; dc_mon logs --tail 15 prometheus | tail -15; exit 1; }
[ "$(curl -s --max-time 5 "http://127.0.0.1:$AP/-/healthy" -o /dev/null -w '%{http_code}')" = 200 ] && ok "Alertmanager healthy" || no "Alertmanager"
w(){ waitfor 50 x bash -c "$(declare -f q); PP=$PP; r=\$(q '$1'); [ \"\$r\" = '$2' ] && echo \$r"; }
w 'probe_success{instance="http://gateway:8080/healthz"}' 1 >/dev/null && ok "탐침: gateway /healthz 성공" || no "탐침 gateway /healthz"
w 'probe_success{instance="http://release-gate:8080/readyz"}' 1 >/dev/null && ok "탐침: release-gate /readyz 성공" || no "탐침 release-gate /readyz"
w 'probe_success{instance="http://model-serving:8080/readyz"}' 1 >/dev/null && ok "탐침: model-serving /readyz 성공" || no "탐침 model-serving /readyz"
w 'openit_gate_judging_consecutive_failures' 0 >/dev/null && ok "json_exporter: 판정 루프 연속 실패 0 을 지표로 읽는다" || no "json_exporter 지표"
w 'openit_gate_judging_upstream_auth_failed' 0 >/dev/null && ok "json_exporter: upstream_auth_failed(false)를 0 으로 읽는다" || no "json_exporter 불리언"
[ -n "$(waitfor 30 x bash -c "$(declare -f q); PP=$PP; q 'max(node_filesystem_size_bytes)'")" ] && ok "node_exporter: 디스크 지표" || no "node_exporter 디스크 지표"
w 'openit_job_last_exit_status{job_name="demo"}' 0 >/dev/null && ok "textfile: 주기 잡 demo 의 마지막 결과 0" || no "textfile 지표(성공 잡)"
w 'openit_job_last_exit_status{job_name="brokenjob"}' 1 >/dev/null && ok "textfile: 실패한 잡 brokenjob 의 결과 1" || no "textfile 지표(실패 잡)"
# 실패 주입: 가짜 release-gate 가 연속 실패 3회 + 503 을 낸다 -> GateJudgingFailuresCritical, ProbeDown(readyz) 가 firing 이어야 하고 JobFailed 도 (brokenjob)
echo fail3 > "$FS/mode"
firing(){ curl -s --max-time 5 "http://127.0.0.1:$PP/api/v1/alerts" | python3 -c 'import json,sys;print(" ".join(sorted(set(a["labels"]["alertname"] for a in json.load(sys.stdin)["data"]["alerts"] if a["state"]=="firing"))))'; }
for i in $(seq 1 60); do f=$(firing); case " $f " in *" GateJudgingFailuresCritical "*" JobFailed "*) break;; esac; sleep 5; done
case " $f " in *" GateJudgingFailuresCritical "*) ok "실패 주입: GateJudgingFailuresCritical firing";; *) no "GateJudgingFailuresCritical 이 울리지 않았다(firing: $f)";; esac
case " $f " in *" JobFailed "*) ok "실패한 잡: JobFailed firing";; *) no "JobFailed 이 울리지 않았다(firing: $f)";; esac
for i in $(seq 1 40); do c=$(curl -s --max-time 5 "http://127.0.0.1:$AP/api/v2/alerts" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))'); [ "${c:-0}" -ge 2 ] && break; sleep 5; done
[ "${c:-0}" -ge 2 ] && ok "Alertmanager 가 경보를 받았다(${c}건)" || no "Alertmanager 가 경보를 받지 못했다"
[ $rc = 0 ] && echo "통과: 감시 스택 시험 ${n}건" || echo "실패"; exit $rc
