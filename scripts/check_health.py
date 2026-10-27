#!/usr/bin/env python3
"""상태 점검(읽기 전용): 스케줄러/잡 실패, 디스크 사용률, 외부 감시 대상(gateway)의 응답을 한 번에 읽어 OK/WARN/CRIT/SKIP 으로 낸다.
cron·systemd timer·서버 밖 감시가 부르고 종료 코드로 판단한다: 0 모두 OK, 1 WARN 있음, 2 CRIT 있음. SKIP(확인하지 못함)은 통과가 아니라 따로 센다.
읽는 것: 스케줄러 상태 파일(scheduler.py 가 쓴다), 잡 정의(config/jobs.yaml), 디스크(df), 외부 감시 설정의 대상(config/external-monitor.yaml, 없으면 .example.yaml)
한계값(디스크 80/90%, 잡 지연 2배)은 헤드가 정한 표준 관행의 시작값이고 사용자 결정이 아니다. 비밀 값은 읽지도 출력하지도 않는다.
"""
import argparse, json, os, shutil, sys, time, urllib.request, urllib.error
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser()
ap.add_argument("--scheduler-state", default=os.path.join(ROOT, "state/scheduler.json"))
ap.add_argument("--jobs", default=os.path.join(ROOT, "config/jobs.yaml"))
ap.add_argument("--monitor", default="", help="외부 감시 설정(기본 config/external-monitor.yaml, 없으면 .example.yaml)")
ap.add_argument("--disk-path", action="append", default=[], help="점검할 경로(여러 번). 기본: 이 리포의 state/, config/backup.env 의 BACKUP_DIR")
ap.add_argument("--disk-warn", type=int, default=80); ap.add_argument("--disk-crit", type=int, default=90)
ap.add_argument("--stale-factor", type=float, default=2.0, help="주기의 몇 배를 넘기면 CRIT")
ap.add_argument("--stuck-seconds", type=int, default=3600, help="시작했지만 끝나지 않은 채 이 시간이 지나면 CRIT")
ap.add_argument("--readyz", action="append", default=[], metavar="release-gate=URL|model-serving=URL", help="서비스 /readyz 를 읽어 판정한다(여러 번)")
ap.add_argument("--project", default="", help="compose 프로젝트 이름(예: deploy). 있으면 그 프로젝트의 release-gate·model-serving 컨테이너 호스트 포트를 docker port 로 찾아 --readyz 로 쓴다(컨테이너나 게시 포트가 없으면 SKIP)")
ap.add_argument("--judging-failures-warn", type=int, default=1); ap.add_argument("--judging-failures-crit", type=int, default=3)
ap.add_argument("--judging-stale-seconds", type=int, default=900, help="release-gate 판정 루프의 last_run_at 이 이보다 오래되면 WARN")
ap.add_argument("--now", type=float, default=None)
a = ap.parse_args()
NOW = a.now or time.time()
R = []   # (상태, 이름, 설명)
def add(s, n, d): R.append((s, n, d))

# 1) 스케줄러/잡
try: jobs = yaml.safe_load(open(a.jobs, encoding="utf-8"))["jobs"]
except Exception as e: jobs = None; add("CRIT", "스케줄러 잡 정의", f"{a.jobs} 를 읽지 못했다({type(e).__name__})")
if jobs is not None:
    try: st = json.load(open(a.scheduler_state))
    except FileNotFoundError: st = None; add("WARN", "스케줄러 상태 파일", f"{os.path.relpath(a.scheduler_state, ROOT)} 가 없다: 스케줄러(scheduler.py tick)가 한 번도 돌지 않았다")
    except Exception as e: st = None; add("CRIT", "스케줄러 상태 파일", f"읽지 못했다({type(e).__name__})")
    if st is not None:
        for j in jobs:
            n = j["name"]
            if j.get("where") != "serving": add("SKIP", f"잡 {n}", f"실행 위치 {j.get('where')}(이 서버 밖): 여기서 확인하지 않는다"); continue
            if j.get("interval_seconds") is None: add("SKIP", f"잡 {n}", "주기 미정"); continue
            s = st.get(n)
            if not s or "last_start" not in s: add("WARN", f"잡 {n}", "실행 기록이 없다"); continue
            ls, le, code, iv = s["last_start"], s.get("last_end"), s.get("last_exit"), j["interval_seconds"]
            if le is None or le < ls:
                add("CRIT" if NOW - ls > a.stuck_seconds else "OK", f"잡 {n}", f"시작 {int(NOW-ls)}초 전, 아직 끝나지 않았다" + (f"(상한 {a.stuck_seconds}초 초과)" if NOW - ls > a.stuck_seconds else "(실행 중으로 본다)"))
            elif code != 0: add("CRIT", f"잡 {n}", f"마지막 종료 코드 {code}: {str(s.get('last_msg',''))[:100]} ({int(NOW-le)}초 전)")
            elif NOW - ls > iv * a.stale_factor + 60: add("CRIT", f"잡 {n}", f"마지막 시작이 {int(NOW-ls)}초 전이라 주기 {iv}초의 {a.stale_factor:g}배를 넘었다(스케줄러가 멈췄나)")
            else: add("OK", f"잡 {n}", f"마지막 종료 코드 0, {int(NOW-le)}초 전")

# 2) 디스크
paths = list(a.disk_path)
if not paths:
    paths.append(os.path.join(ROOT, "state"))
    try:
        for ln in open(os.path.join(ROOT, "config/backup.env"), encoding="utf-8"):
            if ln.startswith("BACKUP_DIR=") and ln.strip().split("=", 1)[1]: paths.append(ln.strip().split("=", 1)[1])
    except OSError: pass
seen = set()
for p in paths:
    ap_ = p if os.path.isabs(p) else os.path.join(ROOT, p)
    if not os.path.exists(ap_): add("SKIP", f"디스크 {p}", "경로가 없어 확인하지 못했다"); continue
    u = shutil.disk_usage(ap_); pct = int(round(u.used * 100 / u.total)); key = (u.total, u.used)
    if key in seen: continue
    seen.add(key)
    add("CRIT" if pct >= a.disk_crit else "WARN" if pct >= a.disk_warn else "OK", f"디스크 {p}", f"사용 {pct}% (여유 {u.free//2**30}GiB, 경보 {a.disk_warn}%/{a.disk_crit}%)")

# 3) 외부 감시 대상(서버 밖 감시가 보는 주소를 같은 설정에서 읽어 직접 한 번 불러 본다)
mon = a.monitor or next((p for p in (os.path.join(ROOT, "config/external-monitor.yaml"), os.path.join(ROOT, "config/external-monitor.example.yaml")) if os.path.exists(p)), "")
if not mon: add("SKIP", "외부 감시 설정", "config/external-monitor(.example).yaml 이 없다")
else:
    try: targets = (yaml.safe_load(open(mon, encoding="utf-8")) or {}).get("targets") or []
    except Exception as e: targets = []; add("CRIT", "외부 감시 설정", f"{os.path.basename(mon)} 를 읽지 못했다({type(e).__name__})")
    for t in targets:
        n = t.get("name", "?"); u = t.get("url")
        if not u: add("SKIP", f"감시 {n}", f"url 미정({os.path.basename(mon)}): 공개 주소가 정해지면 채운다"); continue
        want = t.get("expect_status", 200)
        try:
            with urllib.request.urlopen(u, timeout=5) as r: code = r.status
        except urllib.error.HTTPError as e: code = e.code
        except Exception as e: add("CRIT", f"감시 {n}", f"{u} 에 닿지 못했다({type(e).__name__})"); continue
        add("OK" if code == want else "CRIT", f"감시 {n}", f"{u} -> {code} (기대 {want})")

# 4) 서비스 /readyz: release-gate 판정 루프(judging_loop), model-serving 엔진(멈춤·사망 시 503)
readyz = {}
for item in a.readyz:
    k, _, u = item.partition("="); readyz[k] = u
if a.project:
    import subprocess
    for svc in ("release-gate", "model-serving"):
        if svc in readyz: continue
        try:
            out = subprocess.run(["docker", "port", f"{a.project}-{svc}-1", "8080/tcp"], capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
        except Exception as e: out = []
        if out: readyz[svc] = f"http://127.0.0.1:{out[0].rsplit(':', 1)[1]}/readyz"
        else: add("SKIP", f"readyz {svc}", f"프로젝트 {a.project} 의 컨테이너가 없거나 호스트 포트가 게시되지 않았다")
def get_json(u):
    try:
        with urllib.request.urlopen(u, timeout=5) as r: code, raw = r.status, r.read()
    except urllib.error.HTTPError as e: code, raw = e.code, e.read()
    except Exception as e: return None, {"error": type(e).__name__}
    try: d = json.loads(raw or b"{}")
    except ValueError: d = {}
    return code, d if isinstance(d, dict) else {}
for svc, u in readyz.items():
    code, d = get_json(u)
    if code is None: add("CRIT", f"readyz {svc}", f"{u} 에 닿지 못했다({d.get('error')})"); continue
    reason = str(d.get("reason") or d.get("code") or d.get("status") or "")[:80]
    if code != 200: add("CRIT", f"readyz {svc}", f"{u} -> {code} {reason}"); continue
    if svc == "model-serving": add("OK", f"readyz {svc}", "200 (엔진 정상)"); continue
    if svc == "release-gate":
        jl = d.get("judging_loop")
        if jl is None: add("SKIP", "release-gate 판정 루프", "/readyz 에 judging_loop 가 없다(판정이 꺼져 있거나 옛 버전)"); continue
        if jl.get("upstream_auth_failed"): add("CRIT", "release-gate 판정 루프", "이웃 호출 인증 실패(upstream_auth_failed): 재시도로 풀리지 않는다. 토큰 확인"); continue
        f = jl.get("consecutive_failures") or 0; lr = jl.get("last_run_at")
        if f >= a.judging_failures_crit: add("CRIT", "release-gate 판정 루프", f"연속 실패 {f}회 (마지막 오류 {str((jl.get('last_error') or {}).get('code'))})")
        elif f >= a.judging_failures_warn: add("WARN", "release-gate 판정 루프", f"연속 실패 {f}회 (마지막 오류 {str((jl.get('last_error') or {}).get('code'))})")
        elif lr is None: add("WARN", "release-gate 판정 루프", "아직 한 번도 돌지 않았다(last_run_at 없음)")
        elif NOW - lr > a.judging_stale_seconds: add("WARN", "release-gate 판정 루프", f"마지막 실행이 {int(NOW-lr)}초 전이다(기준 {a.judging_stale_seconds}초)")
        else: add("OK", "release-gate 판정 루프", f"연속 실패 0, 마지막 실행 {int(NOW-lr)}초 전")

for s, n, d in R: print(f"{s:4} {n}: {d}")
c = {k: sum(1 for r in R if r[0] == k) for k in ("OK", "WARN", "CRIT", "SKIP")}
print(f"-- 결과: OK {c['OK']}, WARN {c['WARN']}, CRIT {c['CRIT']}, SKIP(확인 못 함, 통과 아님) {c['SKIP']} / 항목 {len(R)}개")
sys.exit(2 if c["CRIT"] else 1 if c["WARN"] else 0)
