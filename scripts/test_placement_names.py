#!/usr/bin/env python3
"""R1.4 정적 점검(RUNTIME.md): 호출하는 쪽은 서비스가 어느 서버에 있는지 모른다. 배치 도구가 만든 서버별 override 에서 호출 설정의
이름(환경 변수 키)과 값의 서비스 이름 부분이 한 서버 배치(compose·config 의 기본값)와 같은지 본다. 달라도 되는 것은 포트(게시 포트)뿐이다.
검사: (1) override 의 환경 키는 한 서버 배치의 환경에도 있다 (2) 값은 <스킴>://<서비스 이름>:<포트><경로> 이고 서비스 이름·경로가 한 서버 배치의 값과 같다
      (3) 값에 IP·서버 주소가 없다 (서버 주소는 extra_hosts 로만 간다) (4) 다른 서버 postgres 의 DSN 호스트는 서비스 이름 postgres 다.
입력: 예시 인벤토리(서버 2개)와 단일 예시 인벤토리를 여러 방식으로 쪼갠 배치. Docker 불필요."""
import json, os, re, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from openit_deploy.wiring import placement_tool as pt  # noqa: E402

compose = pt.load_compose(os.path.join(ROOT, "compose.yaml")); CD = ROOT
base_inv = pt.load_inventory(os.path.join(ROOT, "ansible", "inventory.example.yml"))
ALL = base_inv["servers"][next(iter(base_inv["servers"]))]["services"]
LINE = re.compile(r'^\s{6}([A-Z][A-Z0-9_]*): "(https?://.*)"$')
STRICT = re.compile(r"^https?://([a-z0-9][a-z0-9-]*):(\d+)(.*)$")   # 서비스 이름(점 없음)만 허용: IP·도메인 이름이면 여기서 걸린다
IP = re.compile(r"\d+\.\d+\.\d+\.\d+")
fails, checked = [], 0

def build(groups):
    """groups: 서버 이름 -> 서비스 목록. 불리는 서비스에 빈 포트를 매긴다(점검이 요구하는 것만)."""
    p = {"scheme": "https", "servers": {}, "ports": {}, "_compose_dir": CD}
    for i, (name, svcs) in enumerate(groups.items()):
        p["servers"][name] = {"address": "10.9.0.%d" % (i + 1), "region": "r%d" % i, "services": list(svcs), "bind": "10.9.0.%d" % (i + 1)}
    pt.expand(p, compose)
    for k, n in enumerate(sorted(pt.remote_called(p, compose))):
        p["ports"][n] = 21000 + k
    return p

DBS = [s for s in ALL if s.endswith("-db") or s == "backup-store"]   # 영역 DB(<서비스>-db)와 백업 저장소(데이터 서버에 같이 둔다)   # 영역마다 자기 DB 컨테이너(<서비스>-db)
SPLITS = {
    "multi-example": None,
    "edge-vs-core": {"edge": ["gateway", "identity-proxy", "identity", "kiosk-frontend", "admin-console"],
                     "core": [s for s in ALL if s not in ("gateway", "identity-proxy", "identity", "kiosk-frontend", "admin-console")]},
    "db-alone": {"db": DBS + ["step-ca"], "rest": [s for s in ALL if s not in DBS + ["step-ca"]]},
    "three-way": {"a": DBS + ["step-ca", "identity", "identity-proxy"],
                  "b": ["release-gate", "question-authoring", "ops-feedback", "model-registry", "dataset-store"],
                  "c": ["survey-service", "model-serving", "gateway", "kiosk-frontend", "admin-console"]},
}
one = build({"only": ALL})
base_env = {n: pt.env_of(compose["services"][n], CD) for n in compose["services"]}

for label, groups in SPLITS.items():
    if groups is None:
        p = pt.load_inventory(os.path.join(ROOT, "ansible", "inventory.multi.example.yml")); p["_compose_dir"] = CD; pt.expand(p, compose)
    else:
        p = build(groups)
    errs = pt.check(p, compose)
    if errs:
        fails.append("%s: 배치 점검 실패(시험 입력이 잘못됐다): %s" % (label, errs[:2])); continue
    for host in p["servers"]:
        tmp = tempfile.mkdtemp()
        text, plan = pt.render(p, compose, host, CD, None, None)
        sd = os.path.join(tmp, "sec"); os.makedirs(sd)
        for f in plan["secret_files"]:   # DB 접속 URI 만 내용이 필요하다(파일 경로 .../db-urls/<DB 서비스>/...). 가짜 값(비밀 아님)
            m = re.match(r"^db-urls/([a-z0-9-]+)/", f)
            if m:
                os.makedirs(os.path.dirname(os.path.join(sd, f)), exist_ok=True)
                open(os.path.join(sd, f), "w").write("postgresql://u:x@%s:5432/d?sslmode=verify-full&sslrootcert=/etc/openit/pki/root_ca.crt\n" % m.group(1))
        text, plan = pt.render(p, compose, host, CD, sd, os.path.join(tmp, "out"))
        cur = None
        for n_ in plan["services"]:   # P3: <서비스>-net 은 앱과 같은 서버에 선다
            if n_ + "-net" in compose["services"] and n_ + "-net" not in plan["services"]:
                fails.append("%s/%s: %s-net 이 %s 와 같은 서버에 없다" % (label, host, n_, n_))
        for line in text.split("\n"):
            m = re.match(r"^  ([a-z0-9-]+):$", line)
            if m: cur = m.group(1); continue
            m = re.match(r"^    (ports|extra_hosts|networks):", line)
            if m and cur and compose["services"][cur].get("network_mode"):   # P3: 망·게시 포트·extra_hosts 는 <서비스>-net 에만 둔다(network_mode 서비스는 받지 못한다)
                fails.append("%s/%s: network_mode 서비스 %s 에 %s 를 두었다(<서비스>-net 에 둔다)" % (label, host, cur, m.group(1)))
            m = LINE.match(line)
            if not m or cur is None:
                continue
            key, val = m.groups(); checked += 1
            where = "%s/%s %s.%s" % (label, host, cur, key)
            sm = STRICT.match(val)
            if not sm:
                fails.append("%s: 값의 호스트가 서비스 이름이 아니다(IP·도메인 등): %s" % (where, val)); continue
            name, port, rest = sm.groups()
            if key not in base_env[cur]:
                fails.append("%s: 한 서버 배치에 없는 환경 키" % where); continue
            bm = pt.URL_RE.match(base_env[cur][key])
            if not bm or bm.group(2) != name or bm.group(4) != rest:
                fails.append("%s: 서비스 이름·경로가 한 서버 배치와 다르다 (%s -> %s)" % (where, base_env[cur][key], val))
            if IP.search(val.split("://", 1)[1].split("/", 1)[0].split(":")[0]):
                fails.append("%s: 값에 IP 가 있다: %s" % (where, val))
        for f in plan["generated_secret_files"]:
            checked += 1
            body = open(os.path.join(tmp, "out", "secrets", f)).read()
            hm = re.search(r"@([^:/]+):(\d+)/", body)
            if not hm or hm.group(1) != re.match(r"^db-urls/([a-z0-9-]+)/", f).group(1):
                fails.append("%s/%s: %s 의 DSN 호스트가 그 계정의 영역 DB 서비스 이름이 아니다" % (label, host, f))
for f in fails:
    print("FAIL: " + f, file=sys.stderr)
if fails or checked == 0:
    sys.exit(1)
print("OK: R1.4 서버별 override 의 호출 설정 %d곳이 한 서버 배치와 이름·경로가 같다 (주소는 서비스 이름, 서버 주소는 extra_hosts 로만)" % checked)
