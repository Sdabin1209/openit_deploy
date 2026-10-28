#!/usr/bin/env bash
# 주기 잡 systemd 유닛(config/systemd/openit-<잡>.service|timer)의 정적 시험(ADR 0036). 서비스를 띄우지 않는다.
#  - 잡마다 service+timer 한 쌍, 주기(OnUnitActiveSec)가 기대표와 같다, oneshot, 제한 시간이 있다
#  - ExecStart 의 스크립트가 리포에 있고, run-job.sh 의 compose 서비스 이름이 compose.yaml 에 있다
#  - systemd-analyze verify 가 통과한다(있을 때만. 없으면 SKIP 으로 알린다: 통과로 세지 않는다). 망가진 유닛은 거부하는지도 본다
#  - 옛 scheduler.py 를 부르는 곳이 없다
HERE="$(cd "$(dirname "$0")/.." && pwd)"; U="$HERE/config/systemd"; rc=0; n=0
fail(){ echo "  FAIL $*"; rc=1; }; ok(){ echo "  ok   $*"; n=$((n+1)); }
# 잡 이름 | 주기(초) | 서비스 인자(run-job.sh <compose 서비스> 또는 다른 스크립트)
TABLE='ops-feedback-job|3600|scripts/run-job.sh job-ops-feedback
survey-purge|86400|scripts/run-job.sh job-survey-purge
backup|86400|scripts/backup-all.sh
backup-restore-test|604800|scripts/backup-restore-test.sh
question-authoring-purge|86400|scripts/run-job.sh job-question-authoring-purge
release-gate-prune|86400|scripts/run-job.sh job-release-gate-prune
release-gate-collector|600|scripts/run-job.sh job-release-gate-collect'
while IFS='|' read -r name iv cmd; do
  s="$U/openit-$name.service"; t="$U/openit-$name.timer"
  [ -f "$s" ] && [ -f "$t" ] || { fail "$name: service/timer 쌍이 없다"; continue; }
  grep -q '^Type=oneshot' "$s" || fail "$name: Type=oneshot 이 아니다(겹침 방지가 이것에 기댄다)"
  grep -q '^TimeoutStartSec=' "$s" || fail "$name: TimeoutStartSec 이 없다"
  grep -qx "ExecStart=/srv/deploy/$cmd" "$s" || fail "$name: ExecStart 가 기대($cmd)와 다르다"
  grep -qx "OnUnitActiveSec=${iv}s" "$t" || fail "$name: 주기가 ${iv}s 가 아니다"
  [ -f "$HERE/${cmd%% *}" ] || fail "$name: 스크립트 ${cmd%% *} 가 없다"
  case "$cmd" in *run-job.sh*) svc=${cmd##* }; grep -q "^  $svc:" "$HERE/compose.yaml" || fail "$name: compose.yaml 에 서비스 $svc 가 없다";; esac
  ok "$name: 쌍, 주기 ${iv}s, oneshot, 스크립트"
done <<<"$TABLE"
bad=$(grep -rln 'scheduler\.py' "$HERE/config" "$HERE/scripts" "$HERE/compose.yaml" --include='*' 2>/dev/null | grep -v 'test-systemd-units.sh' || true)
[ -z "$bad" ] && ok "scheduler.py 를 부르는 곳이 없다" || fail "scheduler.py 참조: $bad"
if command -v systemd-analyze >/dev/null 2>&1; then
  T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; cp "$U"/openit-*.service "$U"/openit-*.timer "$T/"
  sed -i "s|/srv/deploy|$HERE|; /^User=/d" "$T"/openit-*.service   # 이 호스트에 없는 경로·사용자를 시험 사본에서만 바꾼다
  out=$(systemd-analyze verify "$T"/openit-*.timer "$T"/openit-*.service 2>&1) && [ -z "$out" ] && ok "systemd-analyze verify 통과(유닛 $(ls "$T" | wc -l)개)" || fail "systemd-analyze verify: $out"
  printf '[Unit]\n[Service]\nType=oneshot\nExecStart=relative/not-absolute\n' > "$T/bad.service"
  systemd-analyze verify "$T/bad.service" >/dev/null 2>&1 && fail "망가진 유닛을 통과시킨다(verify 가 시험으로 쓸모 없다)" || ok "망가진 유닛은 verify 가 거부한다"
else echo "  SKIP systemd-analyze 가 없어 verify 를 하지 못했다(통과 아님)"; fi
[ $rc = 0 ] && echo "통과: systemd 유닛 정적 시험 ${n}건" || echo "실패"; exit $rc
