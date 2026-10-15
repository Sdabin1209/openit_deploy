#!/usr/bin/env python3
"""영역 주기 잡 스케줄러(D39). 호스트에서 도는 가벼운 프로세스이고 docker 소켓을 컨테이너에 주지 않는다.

  scheduler.py --config config/jobs.yaml --state state/scheduler.json tick     기한이 된 잡을 한 번씩 실행하고 끝낸다(cron/systemd timer가 부른다)
  scheduler.py ... loop --every 30                                                tick을 30초마다 반복한다
  scheduler.py ... status                                                         잡별 마지막 실행과 다음 기한을 보인다

규칙: 같은 잡이 이미 실행 중이면 건너뛴다(잠금). 주기가 null이면 실행하지 않는다. where 가 serving 이 아닌 잡은 실행하지 않는다.
상태 파일은 잡마다 마지막 시작·종료·종료 코드를 가진다. 여러 번 불러도 기한 전에는 아무것도 하지 않는다(멱등).
"""
import argparse, fcntl, json, os, subprocess, sys, time
import yaml

ap = argparse.ArgumentParser()
ap.add_argument("--config", required=True); ap.add_argument("--state", required=True)
ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ap.add_argument("--timeout", type=int, default=3600, help="잡 하나의 제한 시간(초)")
sub = ap.add_subparsers(dest="cmd", required=True)
sub.add_parser("tick"); sub.add_parser("status")
lp = sub.add_parser("loop"); lp.add_argument("--every", type=int, required=True)
a = ap.parse_args()


def load():
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    jobs = cfg["jobs"]
    names = [j["name"] for j in jobs]
    if len(set(names)) != len(names): sys.exit("잡 이름이 겹친다")
    for j in jobs:
        if "interval_seconds" not in j: sys.exit(f"{j['name']}: interval_seconds 키가 없다(null이면 주기 미정)")
        if j["interval_seconds"] is not None and (not isinstance(j["interval_seconds"], int) or j["interval_seconds"] <= 0):
            sys.exit(f"{j['name']}: interval_seconds 는 양의 정수나 null")
    return jobs


def read_state():
    try: return json.load(open(a.state))
    except FileNotFoundError: return {}


def write_state(st):
    os.makedirs(os.path.dirname(os.path.abspath(a.state)), exist_ok=True)
    tmp = a.state + ".tmp"; json.dump(st, open(tmp, "w"), indent=1); os.replace(tmp, a.state)


def tick(now=None):
    jobs = load(); st = read_state(); lockdir = os.path.join(os.path.dirname(os.path.abspath(a.state)), "scheduler-locks")
    os.makedirs(lockdir, exist_ok=True)
    report = []
    for j in jobs:
        n = j["name"]
        if j.get("where") != "serving":
            report.append((n, "SKIP", f"실행 위치 {j.get('where')} (이 스케줄러·Compose 밖)")); continue
        if j["interval_seconds"] is None:
            report.append((n, "SKIP", "주기 미정(사용자 결정)")); continue
        last = st.get(n, {}).get("last_start", 0)
        t = now or time.time()
        if t - last < j["interval_seconds"]:
            report.append((n, "WAIT", f"다음 기한까지 {int(j['interval_seconds'] - (t - last))}초")); continue
        lf = open(os.path.join(lockdir, n + ".lock"), "w")
        try: fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            report.append((n, "BUSY", "이미 실행 중")); continue
        try:
            st = read_state(); st.setdefault(n, {})["last_start"] = t; write_state(st)
            try:
                r = subprocess.run(j["command"], cwd=a.root, timeout=a.timeout, capture_output=True, text=True)
                code, tail = r.returncode, (r.stdout + r.stderr).strip().splitlines()[-1:] 
            except subprocess.TimeoutExpired:
                code, tail = 124, ["제한 시간 초과"]
            st = read_state(); st[n].update(last_end=time.time(), last_exit=code, last_msg=(tail[0] if tail else "")); write_state(st)
            report.append((n, "OK" if code == 0 else "FAIL", f"종료 코드 {code} {tail[0] if tail else ''}"))
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN); lf.close()
    for n, s, d in report: print(f"{s:5} {n}: {d}", flush=True)
    return report


if a.cmd == "tick":
    rep = tick(); sys.exit(1 if any(s == "FAIL" for _, s, _ in rep) else 0)
elif a.cmd == "status":
    st = read_state()
    for j in load():
        s = st.get(j["name"], {})
        print(json.dumps({"job": j["name"], "where": j.get("where"), "interval_seconds": j["interval_seconds"], **s}, ensure_ascii=False))
else:
    while True:
        tick(); time.sleep(a.every)
