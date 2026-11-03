#!/usr/bin/env python3
"""배치 정의(ansible 인벤토리) 검증과 서버별 산출물 계산. ADR 0060.

  placement.py validate <인벤토리> [--compose compose.yaml]
  placement.py render   <인벤토리> --host <서버> --out <폴더> [--compose compose.yaml]

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
PHASES = [["postgres"], ["step-ca"], ["keycloak"]]
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
                      "services": hv.get("placement_services")}
        servers[h] = {k: v for k, v in servers[h].items() if v is not None}
    p = {"servers": servers}
    for src, dst in (("placement_scheme", "scheme"), ("placement_publish_bind", "publish_bind"),
                     ("placement_ports", "ports"), ("placement_base_port", "base_port")):
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
    for e in sorted(Draft202012Validator(schema).iter_errors(p), key=lambda e: list(e.path)):
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
    # DB 접속 비밀을 쓰는 서비스는 postgres 와 같은 서버(DSN 호스트가 서비스 이름 postgres 이고 postgres 는 내부 네트워크에만 있어 밖에서 닿지 않는다)
    pg = owner.get("postgres")
    for s, srv in owner.items():
        if any(n.startswith("db-") and n.endswith("-dsn") for n in names(compose["services"][s].get("secrets"))) and pg and srv != pg:
            errs.append("서비스 '%s' 는 DB 접속 비밀을 쓰므로 postgres 와 같은 서버(%s)여야 한다(지금 %s)" % (s, pg, srv))
    for port in (p.get("ports") or {}):
        if port not in known:
            errs.append("ports: 서비스 '%s' 는 compose 서비스 목록에 없다" % port)
    return errs


def ports_for(p, compose):
    base = p.get("base_port", 19000)
    names = list(compose["services"])
    out = {n: base + i for i, n in enumerate(names)}
    out.update(p.get("ports") or {})
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


def render(p, compose, host, compose_dir):
    servers = p["servers"]
    if host not in servers:
        fail(["서버 '%s' 는 인벤토리에 없다" % host])
    owner = {s: srv for srv, d in servers.items() for s in d["services"]}
    local = list(servers[host]["services"])
    scheme = p.get("scheme", "https")
    bind = p.get("publish_bind", "0.0.0.0")
    ports = ports_for(p, compose)
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
    ov, called_remote, published = {}, set(), set()
    # (b) 상대 서비스 주소: 같은 서버면 그대로(서비스 이름), 다른 서버면 그 서버 주소와 게시 포트
    for n in local:
        env = env_of(compose["services"][n], compose_dir)
        new = {}
        for k, v in env.items():
            m = URL_RE.match(v)
            if m and m.group(2) in compose["services"] and m.group(2) in owner and owner[m.group(2)] != host:
                tgt = m.group(2)
                new[k] = "%s://%s:%d%s" % (scheme, servers[owner[tgt]]["address"], ports[tgt], m.group(4))
        if new:
            ov.setdefault(n, {})["environment"] = new
    # 이 서버의 서비스를 다른 서버가 부르면 호스트 포트를 연다(서버 사이 호출은 게시 포트로만)
    for srv, d in servers.items():
        if srv == host:
            continue
        for n in d["services"]:
            for k, v in env_of(compose["services"][n], compose_dir).items():
                m = URL_RE.match(v)
                if m and m.group(2) in localset and m.group(2) in owner and owner[m.group(2)] == host:
                    published.add(m.group(2))
    # depends_on 은 이 서버에 있는 것만 남긴다(다른 서버의 준비는 기동 순서가 아니라 서버 사이 재시도가 맡는다)
    for n in local:
        dep = compose["services"][n].get("depends_on")
        if dep:
            dd = dep if isinstance(dep, dict) else {k: {"condition": "service_started"} for k in dep}
            kept = {k: c for k, c in dd.items() if k in localset}
            if len(kept) != len(dd):   # 한 서버 배치는 바꾸지 않는다(기존 up.sh 와 같은 결과)
                ov.setdefault(n, {})["depends_on"] = kept
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
        if n in published and n != "gateway":
            lines.append("    ports:")
            lines.append("      - \"%s:%d:8080\"" % (bind, ports[n]))
    if len(lines) == 2:
        lines[1] = "services: {}"
    # 비밀: 이 서버의 서비스가 쓰는 것만(서버가 다른 서버의 비밀을 갖지 않는다)
    secrets = sorted({s for n in local for s in names(compose["services"][n].get("secrets"))})
    configs = sorted({c for n in local for c in names(compose["services"][n].get("configs"))})
    # 배포할 비밀 파일(SECRETS_DIR 아래 상대 경로): 이 서버의 서비스가 마운트하는 secrets·configs 의 file
    pre = "${SECRETS_DIR:-./secrets}/"
    files = []
    for kind, ns in (("secrets", secrets), ("configs", configs)):
        for nm in ns:
            f = (compose.get(kind) or {}).get(nm, {}).get("file", "")
            if f.startswith(pre):
                files.append(f[len(pre):])
    phases, used = [], set()
    for ph in PHASES:
        got = [s for s in ph if s in localset]
        if got:
            phases.append(got); used.update(got)
    rest = [s for s in local if s not in used]
    if rest:
        phases.append(rest)
    plan = {"host": host, "region": servers[host]["region"], "services": local, "phases": phases,
            "secrets": secrets, "configs": configs, "secret_files": sorted(set(files)), "published": {n: ports[n] for n in sorted(published)}}
    return "\n".join(lines) + "\n", plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["validate", "render"])
    ap.add_argument("inventory")
    ap.add_argument("--compose", default=os.path.join(ROOT, "compose.yaml"))
    ap.add_argument("--host")
    ap.add_argument("--out")
    a = ap.parse_args()
    compose = load_compose(a.compose)
    p = load_inventory(a.inventory)
    errs = check(p, compose)
    if errs:
        fail(errs)
    if a.cmd == "validate":
        print("OK: 서버 %d개, 서비스 %d개 배치" % (len(p["servers"]), sum(len(d["services"]) for d in p["servers"].values())))
        return
    if not a.host or not a.out:
        fail(["render 에는 --host 와 --out 이 필요하다"])
    text, plan = render(p, compose, a.host, os.path.dirname(os.path.abspath(a.compose)))
    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, "compose.placement.yaml"), "w", encoding="utf-8").write(text)
    json.dump(plan, open(os.path.join(a.out, "plan.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps(plan))


if __name__ == "__main__":
    main()
