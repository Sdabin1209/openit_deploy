#!/usr/bin/env python3
"""배치 정의(ansible 인벤토리) 검증과 서버별 산출물 계산. ADR 0060.

  placement.py validate <인벤토리> [--compose compose.yaml]
  placement.py render   <인벤토리> --host <서버> --out <폴더> [--compose compose.yaml] [--secrets-dir <폴더>]

render 가 폴더에 쓰는 것: compose.placement.yaml(그 서버의 compose override), plan.json(기동 단계, 필요한 비밀 이름, 게시 포트).
왜 파이썬: 인벤토리·compose 는 YAML 이고 스키마(Placement.schema.json) 검증이 필요하다. 셸로 YAML 을 파싱하지 않는다(lib.sh areas_list 와 같은 이유).
이 도구는 서비스 이름 밖의 것(이미지, 내부 구조)을 모른다: 입력은 배치 정의와 compose 의 서비스 목록·환경·비밀 이름뿐이다(구조 규칙 4).
"""
import argparse, json, os, re, sys
import yaml
from jsonschema import Draft202012Validator

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FOUNDATION = ["postgres", "step-ca", "keycloak", "gateway"]   # 기반 요소(명세 "배치" 행). compose 에 있는 것만 요구한다
# 기동 순서(명세): postgres -> step-ca -> keycloak -> 나머지. 각 단계는 그 서버에 있는 서비스만 올린다
# 서버를 넘나드는 기동 단계(ADR 0060): 앞 단계가 준비된 뒤에 다음 단계를 올린다. 목록에 없는 서비스는 3단계(저장소·서버 서비스)에 든다
STAGES = [["postgres"], ["step-ca"], ["keycloak"],
          ["release-gate", "question-authoring", "ops-feedback-migrate", "ops-feedback-ingest", "model-registry", "dataset-store"],
          ["survey-service", "model-serving"],
          ["oauth2-proxy", "kiosk-frontend", "admin-console", "gateway"]]
DEFAULT_STAGE = 3
CONTAINER_PORT = {"postgres": 5432}   # 나머지는 8080(이미지 규칙, HTTP.md)
PUBLISH_NET = "placement-publish"      # 내부 전용 네트워크에만 붙은 서비스가 호스트 포트를 열 수 있게 더하는 일반 네트워크
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
DSN_RE = re.compile(r"^db-.*-dsn$")
URL_RE = re.compile(r"^(https?)://([a-z0-9][a-z0-9-]*):(\d+)(.*)$")


def fail(msgs):
    for m in msgs:
        print("FAIL: " + m, file=sys.stderr)
    sys.exit(1)


def load_compose(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_inventory(path):
    """ansible YAML 인벤토리(all.vars, all.hosts, all.children.*.hosts)를 배치 정의로 읽는다."""
    with open(path, encoding="utf-8") as f:
        inv = yaml.safe_load(f)
    allg = (inv or {}).get("all")
    if not isinstance(allg, dict):
        fail(["인벤토리에 all: 이 없다"])
    hosts, gvars = {}, dict(allg.get("vars") or {})

    def walk(g, inherited):
        v = {**inherited, **(g.get("vars") or {})}
        for h, hv in (g.get("hosts") or {}).items():
            hosts[h] = {**v, **(hv or {})}
        for c in (g.get("children") or {}).values():
            walk(c or {}, v)
    walk(allg, {})
    servers = {}
    for h, hv in hosts.items():
        servers[h] = {"address": hv.get("ansible_host", h), "region": hv.get("placement_region"),
                      "services": hv.get("placement_services"), "bind": hv.get("placement_bind_address")}
        servers[h] = {k: v for k, v in servers[h].items() if v is not None}
    p = {"servers": servers}
    for src, dst in (("placement_scheme", "scheme"), ("placement_publish_bind", "publish_bind"),
                     ("placement_ports", "ports"), ("placement_db_sslmode", "db_sslmode"), ("placement_db_sslrootcert", "db_sslrootcert")):
        if src in gvars:
            p[dst] = gvars[src]
    return p


def names(items):
    """compose 의 secrets·configs 항목(짧은 형식 이름 또는 {source: 이름})을 이름 목록으로"""
    return [i["source"] if isinstance(i, dict) else i for i in (items or [])]


def oneshots(compose):
    """service_completed_successfully 로 매달린 일회성 서비스(예: 마이그레이션): 배치 대상이 아니라 의존하는 서비스를 따라간다"""
    out = set()
    for s in compose["services"].values():
        dep = s.get("depends_on") or {}
        if isinstance(dep, dict):
            for n, c in dep.items():
                if isinstance(c, dict) and c.get("condition") == "service_completed_successfully":
                    out.add(n)
    return out


def placeable(compose):
    """배치해야 하는 서비스: profiles 가 없고 일회성이 아닌 것(작업 job-* 는 profiles: jobs 라 제외, 스케줄러 몫)"""
    one = oneshots(compose)
    return [n for n, s in compose["services"].items() if not s.get("profiles") and n not in one]


def check(p, compose):
    errs = []
    schema = json.load(open(os.path.join(ROOT, "schemas", "Placement.schema.json"), encoding="utf-8"))
    for e in sorted(Draft202012Validator(schema).iter_errors({k: v for k, v in p.items() if not k.startswith("_")}), key=lambda e: list(e.path)):
        errs.append("형식: %s: %s" % ("/".join(map(str, e.path)) or "(최상위)", e.message))
    if errs:
        return errs
    known = set(compose["services"])
    owner = {}
    for srv, d in p["servers"].items():
        for s in d["services"]:
            if s not in known:
                errs.append("서버 %s: 서비스 '%s' 는 compose 서비스 목록에 없다" % (srv, s))
            elif s in owner:
                errs.append("서비스 '%s' 가 서버 %s 와 %s 두 곳에 있다(한 서비스는 한 서버에만)" % (s, owner[s], srv))
            else:
                owner[s] = srv
    for s in placeable(compose):
        if s not in owner:
            errs.append("서비스 '%s' 를 놓은 서버가 없다" % s)
    for s in FOUNDATION:
        if s in known and s not in owner:
            errs.append("기반 요소 '%s' 를 놓은 서버가 없다" % s)
    # 다른 서버에서 불리는 서비스는 게시 포트를 인벤토리에 명시해야 한다(순서로 계산하지 않는다)
    called = remote_called(p, compose)
    for n in sorted(called):
        if n not in (p.get("ports") or {}):
            errs.append("서비스 '%s' 는 다른 서버에서 불리는데 placement_ports 에 게시 포트가 없다" % n)
    used = {}
    for n, port in (p.get("ports") or {}).items():
        used.setdefault(port, []).append(n)
        if n in owner and n not in called:
            errs.append("placement_ports 의 '%s' 는 다른 서버에서 불리지 않는다(필요 없는 게시 포트)" % n)
    for port, ns in used.items():
        if len(ns) > 1 and len({owner.get(n) for n in ns}) == 1:
            errs.append("게시 포트 %d 를 같은 서버의 %s 가 함께 쓴다" % (port, ", ".join(ns)))
    for srv, d in p["servers"].items():
        if any(n in called for n in d["services"]) and not (d.get("bind") or IP_RE.match(d["address"])):
            errs.append("서버 %s: 게시 포트를 열 주소가 없다(address 가 IP 가 아니면 placement_bind_address 를 준다)" % srv)
    for port in (p.get("ports") or {}):
        if port not in known:
            errs.append("ports: 서비스 '%s' 는 compose 서비스 목록에 없다" % port)
    return errs


def remote_called(p, compose):
    """다른 서버의 서비스가 부르는 서비스 이름 집합: 환경의 URL(scheme://서비스:포트)과 DB 접속 비밀(db-*-dsn 은 postgres 를 부른다)"""
    owner = {s: srv for srv, d in p["servers"].items() for s in d["services"]}
    out = set()
    for n, srv in owner.items():
        svc = compose["services"].get(n)
        if not svc:
            continue
        for v in env_of(svc, p["_compose_dir"]).values():
            m = URL_RE.match(v)
            if m and m.group(2) in owner and owner[m.group(2)] != srv:
                out.add(m.group(2))
        if "postgres" in owner and owner["postgres"] != srv and any(DSN_RE.match(x) for x in names(svc.get("secrets"))):
            out.add("postgres")
    return out


def env_of(svc, compose_dir):
    """서비스에 주입되는 환경(env_file 과 environment). 비밀은 파일 경로뿐이라 값은 비밀이 아니다"""
    env = {}
    for f in svc.get("env_file") or []:
        f = f.replace("${CONFIG_DIR:-./config}", "config")
        path = os.path.join(compose_dir, f)
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k] = v.split(" #")[0].strip()
    e = svc.get("environment") or {}
    if isinstance(e, list):
        e = dict(x.split("=", 1) for x in e if "=" in x)
    env.update({k: str(v) for k, v in e.items()})
    return env


def render(p, compose, host, compose_dir, secrets_dir=None, out=None):
    servers = p["servers"]
    if host not in servers:
        fail(["서버 '%s' 는 인벤토리에 없다" % host])
    owner = {s: srv for srv, d in servers.items() for s in d["services"]}
    local = list(servers[host]["services"])
    scheme = p.get("scheme", "https")
    ports = p.get("ports") or {}
    bind = servers[host].get("bind") or servers[host]["address"]
    # 따라오는 일회성 서비스(예: 마이그레이션)
    one = oneshots(compose)
    todo, seen = list(local), set(local)
    while todo:
        n = todo.pop()
        dep = compose["services"][n].get("depends_on") or {}
        for d in (dep if isinstance(dep, dict) else {k: {} for k in dep}):
            if d in one and d not in seen:
                seen.add(d); local.append(d); todo.append(d)
    localset = set(local)
    ov, published = {}, set()
    # (b) 상대 서비스 주소: 같은 서버면 그대로(서비스 이름), 다른 서버면 그 서버 주소와 게시 포트
    for n in local:
        new = {}
        for k, v in env_of(compose["services"][n], compose_dir).items():
            m = URL_RE.match(v)
            if m and m.group(2) in owner and owner[m.group(2)] != host:
                tgt = m.group(2)
                new[k] = "%s://%s:%d%s" % (scheme, servers[owner[tgt]]["address"], ports[tgt], m.group(4))
        if new:
            ov.setdefault(n, {})["environment"] = new
    # 이 서버의 서비스를 다른 서버가 부르면 호스트 포트를 연다(서버 사이 호출은 게시 포트로만, 바인드 주소는 인벤토리 값)
    published = remote_called(p, compose) & localset
    # depends_on 은 이 서버에 있는 것만 남긴다(다른 서버의 준비는 플레이북의 단계 순서와 /readyz 확인이 맡는다)
    for n in local:
        dep = compose["services"][n].get("depends_on")
        if dep:
            dd = dep if isinstance(dep, dict) else {k: {"condition": "service_started"} for k in dep}
            kept = {k: c for k, c in dd.items() if k in localset}
            if len(kept) != len(dd):   # 한 서버 배치는 바꾸지 않는다(기존 up.sh 와 같은 결과)
                ov.setdefault(n, {})["depends_on"] = kept
    # 내부 전용 네트워크에만 붙은 서비스가 게시되면 일반 네트워크를 더한다(internal 네트워크는 호스트 포트를 열지 못한다)
    nets = compose.get("networks") or {}
    addnet = set()
    for n in published:
        sn = compose["services"][n].get("networks") or []
        sn = list(sn) if not isinstance(sn, dict) else list(sn)
        if sn and all((nets.get(x) or {}).get("internal") for x in sn):
            addnet.add(n); ov.setdefault(n, {})["networks"] = sn + [PUBLISH_NET]
    lines = ["# 생성 파일(scripts/placement.py render): 서버 %s 의 배치 override. 손으로 고치지 않는다." % host, "services:"]
    for n in sorted(set(ov) | published):
        lines.append("  %s:" % n)
        if "environment" in ov.get(n, {}):
            lines.append("    environment:")
            for k, v in sorted(ov[n]["environment"].items()):
                lines.append("      %s: %s" % (k, json.dumps(v)))
        if "depends_on" in ov.get(n, {}):
            if ov[n]["depends_on"]:
                lines.append("    depends_on: !override")
                for k, c in ov[n]["depends_on"].items():
                    lines.append("      %s: %s" % (k, json.dumps(c if isinstance(c, dict) else {"condition": "service_started"})))
            else:
                lines.append("    depends_on: !reset []")
        if "networks" in ov.get(n, {}):
            lines.append("    networks: !override")
            for x in ov[n]["networks"]:
                lines.append("      - %s" % x)
        if n in published and not (compose["services"][n].get("ports")):
            lines.append("    ports:")
            lines.append("      - \"%s:%d:%d\"" % (bind, ports[n], CONTAINER_PORT.get(n, 8080)))
    if addnet:
        lines += ["networks:", "  %s: {}" % PUBLISH_NET]
    if len(lines) == 2:
        lines[1] = "services: {}"
    secrets = sorted({s for n in local for s in names(compose["services"][n].get("secrets"))})
    configs = sorted({c for n in local for c in names(compose["services"][n].get("configs"))})
    pre = "${SECRETS_DIR:-./secrets}/"
    files = []
    for kind, ns in (("secrets", secrets), ("configs", configs)):
        for nm in ns:
            f = (compose.get(kind) or {}).get(nm, {}).get("file", "")
            if f.startswith(pre):
                files.append(f[len(pre):])
    # DB 접속 비밀(db-*-dsn)의 호스트: postgres 가 다른 서버면 그 서버 주소와 게시 포트로 바꿔 이 서버용 파일을 새로 만든다(원본은 그대로)
    generated = []
    pg = owner.get("postgres")
    if pg and pg != host and out and secrets_dir:
        q = ""
        mode = p.get("db_sslmode", "verify-full" if scheme == "https" else "")
        if mode:
            q = "?sslmode=%s&sslrootcert=%s" % (mode, p.get("db_sslrootcert", "/run/secrets/postgres-ca.pem"))
        for f in files:
            if DSN_RE.match(os.path.basename(f)):
                src = open(os.path.join(secrets_dir, f), encoding="utf-8").read()
                dst = src.replace("@postgres:5432/", "@%s:%d/" % (servers[pg]["address"], ports["postgres"])).rstrip("\n") + q + "\n"
                path = os.path.join(out, "secrets", f)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(dst)
                generated.append(f)
    stages = []
    for i in range(len(STAGES)):
        stages.append([n for n in local if (STAGES[i].count(n) or (n not in sum(STAGES, []) and i == DEFAULT_STAGE))])
    plan = {"host": host, "region": servers[host]["region"], "services": local, "stages": stages,
            "secrets": secrets, "configs": configs, "secret_files": sorted(set(files)), "generated_secret_files": generated,
            "published": {n: ports[n] for n in sorted(published)}}
    return "\n".join(lines) + "\n", plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["validate", "render"])
    ap.add_argument("inventory")
    ap.add_argument("--compose", default=os.path.join(ROOT, "compose.yaml"))
    ap.add_argument("--host")
    ap.add_argument("--out")
    ap.add_argument("--secrets-dir")
    a = ap.parse_args()
    compose = load_compose(a.compose)
    p = load_inventory(a.inventory)
    p["_compose_dir"] = os.path.dirname(os.path.abspath(a.compose))
    errs = check(p, compose)
    if errs:
        fail(errs)
    if a.cmd == "validate":
        print("OK: 서버 %d개, 서비스 %d개 배치" % (len(p["servers"]), sum(len(d["services"]) for d in p["servers"].values())))
        return
    if not a.host or not a.out:
        fail(["render 에는 --host 와 --out 이 필요하다"])
    text, plan = render(p, compose, a.host, os.path.dirname(os.path.abspath(a.compose)), a.secrets_dir, a.out)
    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, "compose.placement.yaml"), "w", encoding="utf-8").write(text)
    json.dump(plan, open(os.path.join(a.out, "plan.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps(plan))


if __name__ == "__main__":
    main()
