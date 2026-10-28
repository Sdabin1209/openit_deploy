#!/usr/bin/env python3
"""상태 점검(읽기 전용): 디스크 사용률, 외부 감시 대상(gateway)의 응답을 한 번에 읽어 OK/WARN/CRIT/SKIP 으로 낸다.
cron·systemd timer·서버 밖 감시가 부르고 종료 코드로 판단한다: 0 모두 OK, 1 WARN 있음, 2 CRIT 있음. SKIP(확인하지 못함)은 통과가 아니라 따로 센다.
읽는 것: 디스크(df), 외부 감시 설정의 대상(config/external-monitor.yaml, 없으면 .example.yaml)
한계값(디스크 80/90%)은 헤드가 정한 표준 관행의 시작값이고 사용자 결정이 아니다. 비밀 값은 읽지도 출력하지도 않는다.
"""
import argparse, json, os, shutil, ssl, sys, time, urllib.request, urllib.error
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser()
ap.add_argument("--monitor", default="", help="외부 감시 설정(기본 config/external-monitor.yaml, 없으면 .example.yaml)")
ap.add_argument("--disk-path", action="append", default=[], help="점검할 경로(여러 번). 기본: 이 리포의 state/, config/backup.env 의 BACKUP_DIR")
ap.add_argument("--disk-warn", type=int, default=80); ap.add_argument("--disk-crit", type=int, default=90)
ap.add_argument("--readyz", action="append", default=[], metavar="release-gate=URL|model-serving=URL", help="서비스 /readyz 를 읽어 판정한다(여러 번)")
ap.add_argument("--project", default="", help="compose 프로젝트 이름(예: deploy). 있으면 그 프로젝트의 release-gate·model-serving 컨테이너 호스트 포트를 docker port 로 찾아 --readyz 로 쓴다(컨테이너나 게시 포트가 없으면 SKIP)")
ap.add_argument("--judging-failures-warn", type=int, default=1); ap.add_argument("--judging-failures-crit", type=int, default=3)
ap.add_argument("--judging-stale-seconds", type=int, default=900, help="release-gate 판정 루프의 last_run_at 이 이보다 오래되면 WARN")
ap.add_argument("--backup-config", default=os.path.join(ROOT, "config/backup.env"), help="백업 설정(D88/U6: 필수). 없거나 BACKUP_DIR 이 비면 CRIT")
ap.add_argument("--skip-backup", action="store_true", help="백업 점검을 건너뛴다(시험·개발 구성 전용. 건너뛴 사실을 SKIP 으로 낸다)")
ap.add_argument("--backup-max-age-seconds", type=int, default=172800, help="가장 최근 백업이 이보다 오래되면 CRIT(일일 백업의 2배)")
ap.add_argument("--now", type=float, default=None)
a = ap.parse_args()
NOW = a.now or time.time()
R = []   # (상태, 이름, 설명)
def add(s, n, d): R.append((s, n, d))

# (잡 실행 결과는 systemd 가 journald 에 남기고 보는 도구가 따로 있다: ADR 0036. 이 점검은 잡 상태를 읽지 않는다)

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
            # https 대상은 ca_file(내부 CA 루트 인증서, D88/U5)이 있으면 그것으로 검증한다. 없으면 시스템 신뢰 저장소(공인 인증서나 이 서버에 신뢰시킨 CA)
            ctx = ssl.create_default_context(cafile=t["ca_file"]) if t.get("ca_file") else None
            with urllib.request.urlopen(u, timeout=5, context=ctx) as r: code = r.status
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

# 5) 백업(D88/U6): 설정 필수, 최신 백업의 나이, 암호화 설정
if a.skip_backup: add("SKIP", "백업", "--skip-backup: 점검하지 않았다(시험·개발 구성 전용)")
else:
    cfg = {}
    try:
        for ln in open(a.backup_config, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1); cfg[k.strip()] = v.strip().strip('"').strip("'")
    except OSError: pass
    if not cfg.get("BACKUP_DIR"): add("CRIT", "백업 설정", f"{os.path.relpath(a.backup_config, ROOT) if a.backup_config.startswith(ROOT) else a.backup_config} 가 없거나 BACKUP_DIR 이 비어 있다: 백업이 돌지 않는다(D88/U6: 서버 밖 대상 필수, config/backup.env.example)")
    else:
        bd = cfg["BACKUP_DIR"]; snaps = []
        for pat in ("pg-",):
            try:
                for d in os.listdir(bd):
                    if d.startswith(pat):
                        sub = [os.path.join(bd, d, x) for x in os.listdir(os.path.join(bd, d)) if x.startswith("2")]
                        if sub: snaps.append(max(os.path.getmtime(x) for x in sub))
            except OSError: pass
        if not snaps: add("CRIT", "백업", f"{bd} 에 PostgreSQL 백업이 하나도 없다")
        else:
            age = NOW - min(snaps)
            add("CRIT" if age > a.backup_max_age_seconds else "OK", "백업", f"가장 오래된 데이터베이스의 최신 백업이 {int(age)}초 전 (기준 {a.backup_max_age_seconds}초, 데이터베이스 {len(snaps)}개)")
        if cfg.get("BACKUP_ALLOW_PLAINTEXT", "0") == "1" or not cfg.get("BACKUP_ENCRYPT_RECIPIENTS"): add("WARN", "백업 암호화", "수신자 공개키(BACKUP_ENCRYPT_RECIPIENTS)가 없거나 BACKUP_ALLOW_PLAINTEXT=1: 개인정보가 든 덤프가 평문이다(D88/U6: age 또는 gpg 공개키 암호화)")
        else: add("OK", "백업 암호화", "수신자 공개키 암호화 (공개키만 서버에 둔다)")

for s, n, d in R: print(f"{s:4} {n}: {d}")
c = {k: sum(1 for r in R if r[0] == k) for k in ("OK", "WARN", "CRIT", "SKIP")}
print(f"-- 결과: OK {c['OK']}, WARN {c['WARN']}, CRIT {c['CRIT']}, SKIP(확인 못 함, 통과 아님) {c['SKIP']} / 항목 {len(R)}개")
sys.exit(2 if c["CRIT"] else 1 if c["WARN"] else 0)
