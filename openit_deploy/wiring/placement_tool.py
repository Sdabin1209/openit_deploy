"""배치 정의(ansible 인벤토리) 검증과 서버별 산출물 계산. ADR 0061.

  scripts/placement.py validate <인벤토리> [--compose compose.yaml]
  scripts/placement.py render   <인벤토리> --host <서버> --out <폴더> [--compose compose.yaml] [--secrets-dir <폴더>]

render 가 폴더에 쓰는 것: compose.placement.yaml(그 서버의 compose override), plan.json(기동 단계, 필요한 비밀 이름, 게시 포트).
왜 파이썬: 인벤토리·compose 는 YAML 이고 스키마(Placement.schema.json) 검증이 필요하다. 셸로 YAML 을 파싱하지 않는다(lib.sh areas_list 와 같은 이유).
이 도구는 서비스 이름 밖의 것(이미지, 내부 구조)을 모른다: 입력은 배치 정의와 compose 의 서비스 목록·환경·비밀 이름뿐이다(구조 규칙 4).
"""
import argparse, json, os, re, sys
import yaml
from jsonschema import Draft202012Validator

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))   # 리포 루트(openit_deploy/wiring/ 의 두 단계 위)
FOUNDATION = ["postgres", "step-ca", "keycloak", "gateway"]   # 기반 요소(명세 "배치" 행). compose 에 있는 것만 요구한다
# 기동 순서(명세): postgres -> step-ca -> keycloak -> 나머지. 각 단계는 그 서버에 있는 서비스만 올린다
# 서버를 넘나드는 기동 단계(ADR 0061): 앞 단계가 준비된 뒤에 다음 단계를 올린다. 목록에 없는 서비스는 3단계(저장소·서버 서비스)에 든다
STAGES = [["step-ca"], ["postgres"], ["keycloak"],   # step-ca 가 먼저: 모든 서비스의 인증서(postgres-cert 포함)를 받으려면 CA 가 떠 있어야 한다(ADR 0060)
         
          ["release-gate", "question-authoring", "ops-feedback-migrate", "ops-feedback-ingest", "model-registry", "dataset-store"],
          ["survey-service", "model-serving"],
          ["oauth2-proxy", "kiosk-frontend", "admin-console", "gateway"]]
DEFAULT_STAGE = 3
CONTAINER_PORT = {"postgres": 5432}   # 나머지는 8080(이미지 규칙, HTTP.md)
STEP_CA_BOUND = ("pki-root", "pki-tokens")   # step-ca 서버에서만 돈다: pki-tokens 는 프로비저너 비밀(step-ca-password)을 읽고 pki-root 는 키가 든 pki-ca 볼륨을 읽는다. 둘 다 step-ca 서버 밖으로 나가지 않는다(ADR 0061)
PUBLISH_NET = "placement-publish"      # 내부 전용 네트워크에만 붙은 서비스가 호스트 포트를 열 수 있게 더하는 일반 네트워크
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
DSN_RE = re.compile(r"^db-.*-dsn$")
URL_RE = re.compile(r"^(https?)://([a-z0-9][a-z0-9-]*)(?::(\d+))?(.*)$")   # 포트 생략 = https 의 443(서비스 TLS 사이드카가 받는 포트, ADR 0060)


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


def leaders(compose):
    """따라가는 서비스 -> 그 서비스가 붙은 서비스. 서비스 TLS 사이드카(network_mode: service:<앱>, ADR 0060)는 앱과 같은 네트워크 네임스페이스라 반드시 같은 서버이고,
    postgres-cert·postgres-reload 는 postgres 의 인증서를 만들고 다시 읽게 하는 짝이다. 인벤토리에는 앱만 적고 이들은 자동으로 따라간다(손으로 적다가 어긋나는 것을 막는다)."""
    out = {}
    for n, s in compose["services"].items():
        nm = str(s.get("network_mode") or "")
        if not nm.startswith("service:"):
            continue
        holder = nm.split(":", 1)[1]
        base = holder[:-4] if holder.endswith("-net") and holder[:-4] in compose["services"] else holder
        if holder != base:
            out[holder] = base   # <서비스>-net(pause)은 서비스를 따라가 같은 서버에 선다(RUNTIME.md R3.2)
        if n != base:
            out[n] = base        # 사이드카·앱 자신 외에 그 네임스페이스를 쓰는 서비스는 서비스와 같은 서버
    for n in compose["services"]:   # <서비스>-cert 는 <서비스> 의 인증서를 받는 짝이다(ADR 0060): 같은 서버에서 앱보다 먼저 올라온다
        if n.endswith("-cert") and n[:-5] in compose["services"] and n not in out:
            out[n] = n[:-5]
    for n in STEP_CA_BOUND:
        if n in compose["services"]:
            out[n] = "step-ca"
    for n in ("postgres-cert", "postgres-reload"):
        if n in compose["services"]:
            out[n] = "postgres"
    return out


def holder_of(compose, n):
    """서비스 n 의 망·게시 포트·extra_hosts 를 가진 서비스: network_mode: service:<X> 면 X(<서비스>-net), 아니면 자기 자신"""
    nm = str(compose["services"][n].get("network_mode") or "")
    return nm.split(":", 1)[1] if nm.startswith("service:") else n


def has_sidecar(compose):
    """TLS 사이드카가 있는 서비스(게시는 사이드카의 443). 앱과 같은 <서비스>-net 을 쓰는 다른 서비스가 있으면 사이드카가 있는 것"""
    out = set()
    for n in compose["services"]:
        h = holder_of(compose, n)
        base = h[:-4] if h.endswith("-net") and h[:-4] in compose["services"] else h
        if h != n and n != base:
            out.add(base)
    return out


def expand(p, compose):
    """각 서버의 서비스 목록에 그 서버 서비스를 따라가는 서비스(leaders)를 더한다."""
    lead = leaders(compose)
    for d in p["servers"].values():
        have = set(d["services"])
        d["services"] = list(d["services"]) + [n for n, l in lead.items() if l in have and n not in have]


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
        if any(n in called for n in d["services"]) and not IP_RE.match(d["address"]):
            errs.append("서버 %s: 다른 서버가 이름을 이 서버로 돌리는 extra_hosts 는 IP 만 받는다(address 는 IP 여야 한다)" % srv)
    for port in (p.get("ports") or {}):
        if port not in known:
            errs.append("ports: 서비스 '%s' 는 compose 서비스 목록에 없다" % port)
    return errs


def uses_step_ca(svc):
    """step-ca 에 닿아야 하는 서비스(인증서 발급·갱신: depends_on step-ca 이거나 명령에 https://step-ca 가 있다)"""
    dep = svc.get("depends_on") or {}
    return "step-ca" in dep or "https://step-ca" in (str(svc.get("entrypoint")) + str(svc.get("command")))


def call_targets(p, compose, n, srv, owner):
    """서비스 n(서버 srv)이 부르는 다른 서버의 서비스 이름 집합: 환경의 URL, DB 접속 비밀(postgres), 인증서 발급(step-ca)"""
    svc = compose["services"].get(n)
    out = set()
    if not svc:
        return out
    for v in env_of(svc, p["_compose_dir"]).values():
        m = URL_RE.match(v)
        if m and m.group(2) in owner and owner[m.group(2)] != srv:
            out.add(m.group(2))
    if "postgres" in owner and owner["postgres"] != srv and any(DSN_RE.match(x) for x in names(svc.get("secrets"))):
        out.add("postgres")
    if "step-ca" in owner and owner["step-ca"] != srv and n != "step-ca" and uses_step_ca(svc):
        out.add("step-ca")
    return out


def remote_called(p, compose):
    """다른 서버의 서비스가 부르는 서비스 이름 집합: 환경의 URL(scheme://서비스:포트)과 DB 접속 비밀(db-*-dsn 은 postgres 를 부른다)"""
    owner = {s: srv for srv, d in p["servers"].items() for s in d["services"]}
    out = set()
    for n, srv in owner.items():
        out |= call_targets(p, compose, n, srv, owner)
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
    sidecared = has_sidecar(compose)   # step-ca 는 pki-root·pki-tokens 의 짝일 뿐 TLS 사이드카가 없다(자기 포트 9000)
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
    localset0 = set(local)   # 이 서버에 인벤토리가 놓은 서비스(따라가는 일회성 서비스를 더하기 전)
    todo, seen = list(local), set(local)
    while todo:
        n = todo.pop()
        dep = compose["services"][n].get("depends_on") or {}
        for d in (dep if isinstance(dep, dict) else {k: {} for k in dep}):
            if d in one and d not in seen and not (d in STEP_CA_BOUND and "step-ca" not in localset0):
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
                # 호출자는 언제나 <스킴>://<서비스 이름>:<게시 포트> 로 부른다(인증서 이름 = 서비스 이름, ADR 0060). 이름은 extra_hosts 가 그 서버 주소로 돌린다
                new[k] = "%s://%s:%d%s" % (scheme, tgt, ports[tgt], m.group(4))
        if new:
            ov.setdefault(n, {})["environment"] = new
        hosts_ = sorted(call_targets(p, compose, n, host, owner))
        if hosts_:   # 이름을 서버 주소로 돌리는 extra_hosts 는 망을 가진 서비스(<서비스>-net)에 둔다
            hh = ov.setdefault(holder_of(compose, n), {}).setdefault("extra_hosts", [])
            for t in hosts_:
                e = "%s:%s" % (t, servers[owner[t]]["address"])
                if e not in hh:
                    hh.append(e)
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
    # 다른 서버를 부르는 서비스도 같다: internal 네트워크에만 붙어 있으면 호스트 밖으로 나가지 못한다(예: pki 망의 <서비스>-cert 가 다른 서버의 step-ca 에 닿으려면)
    callers = {n for n in local if call_targets(p, compose, n, host, owner)}
    for n in sorted(published | callers):
        h = holder_of(compose, n)
        sn = compose["services"][h].get("networks") or []
        sm = {k: (v or {}) for k, v in sn.items()} if isinstance(sn, dict) else {k: {} for k in sn}
        if sm and all((nets.get(x) or {}).get("internal") for x in sm):
            sm[PUBLISH_NET] = {}
            addnet.add(h); ov.setdefault(h, {})["networks"] = sm
    # 게시 포트도 망을 가진 서비스에 둔다
    for n in sorted(published):
        h = holder_of(compose, n)
        if not compose["services"][h].get("ports"):
            ov.setdefault(h, {})["ports"] = "%s:%d:%d" % (bind, ports[n], 443 if n in sidecared else (ports[n] if n == "step-ca" else CONTAINER_PORT.get(n, 8080)))
    lines = ["# 생성 파일(scripts/placement.py render): 서버 %s 의 배치 override. 손으로 고치지 않는다." % host, "services:"]
    for n in sorted(ov):
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
        if "extra_hosts" in ov.get(n, {}):
            lines.append("    extra_hosts:")
            for h in ov[n]["extra_hosts"]:
                lines.append("      - %s" % json.dumps(h))
        if "networks" in ov.get(n, {}):
            lines.append("    networks: !override")
            for x, cfg in ov[n]["networks"].items():
                lines.append("      %s: %s" % (x, json.dumps(cfg)))
        if "ports" in ov.get(n, {}):
            lines.append("    ports:")
            lines.append("      - \"%s\"" % ov[n]["ports"])
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
            q = "?sslmode=%s&sslrootcert=%s" % (mode, p.get("db_sslrootcert", "/etc/openit/pki/root_ca.crt"))
        for f in files:
            if DSN_RE.match(os.path.basename(f)):
                src = open(os.path.join(secrets_dir, f), encoding="utf-8").read()
                dst = src.replace("@postgres:5432/", "@postgres:%d/" % ports["postgres"]).rstrip("\n")
                if "?" not in dst:   # gen-secrets 가 이미 sslmode=verify-full&sslrootcert 를 넣는다(TLS 작업). 없을 때만 더한다
                    dst += q
                dst += "\n"
                path = os.path.join(out, "secrets", f)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(dst)
                generated.append(f)
    stages = []
    lead = leaders(compose)   # 따라가는 서비스는 앞선 서비스와 같은 단계
    for i in range(len(STAGES)):
        stages.append([n for n in local if ((lambda k: STAGES[i].count(k) or (k not in sum(STAGES, []) and i == DEFAULT_STAGE))(lead.get(n, n)))])
    # 다른 서버의 step-ca 에서 받아 올 일회용 토큰: 이 서버의 <서비스>-cert 마다 <서비스>.ott (단계별. 수명 5분이라 그 단계 기동 직전에 받는다)
    ca_host = owner.get("step-ca")
    stage_tokens = []
    for st in stages:
        stage_tokens.append(sorted(n[:-5] for n in st if n.endswith("-cert") and ca_host and ca_host != host))
    plan = {"host": host, "oneshots": sorted(one & localset), "step_ca_host": ca_host, "step_ca_port": ports.get("step-ca"), "stage_tokens": stage_tokens, "region": servers[host]["region"], "services": local, "stages": stages,
            "secrets": secrets, "configs": configs, "secret_files": sorted(set(files)), "generated_secret_files": generated,
            "published": {n: ports[n] for n in sorted(published)}}
    return "\n".join(lines) + "\n", plan


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["validate", "render", "export"])
    ap.add_argument("inventory")
    ap.add_argument("--compose", default=os.path.join(ROOT, "compose.yaml"))
    ap.add_argument("--host")
    ap.add_argument("--out")
    ap.add_argument("--secrets-dir")
    ap.add_argument("--root-ca", help="export: 내보낼 루트 인증서 파일(공개). 교체 병행 기간에는 옛·새 루트를 이어 붙인 파일")
    a = ap.parse_args(argv)
    compose = load_compose(a.compose)
    p = load_inventory(a.inventory)
    p["_compose_dir"] = os.path.dirname(os.path.abspath(a.compose))
    expand(p, compose)
    errs = check(p, compose)
    if errs:
        fail(errs)
    if a.cmd == "validate":
        print("OK: 서버 %d개, 서비스 %d개 배치" % (len(p["servers"]), sum(len(d["services"]) for d in p["servers"].values())))
        return
    if a.cmd == "export":
        # R1.5·R1.7·R10.12: compose 밖 호출자에게 루트 인증서와 서비스 이름->주소 표(hosts 형식)와 게시 포트 표를 내보내고 SHA-256 목록을 붙인다
        import hashlib, shutil
        if not a.out or not a.root_ca:
            fail(["export 에는 --out 과 --root-ca 가 필요하다"])
        os.makedirs(a.out, exist_ok=True)
        owner = {s_: srv for srv, d in p["servers"].items() for s_ in d["services"]}
        called = sorted(remote_called(p, compose) | {n for n in (p.get("ports") or {}) if n in owner})
        shutil.copyfile(a.root_ca, os.path.join(a.out, "root_ca.crt"))
        with open(os.path.join(a.out, "hosts"), "w", encoding="utf-8") as f:
            for n in called:
                f.write("%s %s\n" % (p["servers"][owner[n]]["address"], n))
        with open(os.path.join(a.out, "ports.tsv"), "w", encoding="utf-8") as f:
            for n in called:
                f.write("%s\t%d\n" % (n, (p.get("ports") or {})[n]))
        with open(os.path.join(a.out, "SHA256SUMS"), "w", encoding="utf-8") as f:
            for fn in ("root_ca.crt", "hosts", "ports.tsv"):
                f.write("%s  %s\n" % (hashlib.sha256(open(os.path.join(a.out, fn), "rb").read()).hexdigest(), fn))
        print("OK: %s 에 root_ca.crt, hosts, ports.tsv, SHA256SUMS" % a.out)
        return
    if not a.host or not a.out:
        fail(["render 에는 --host 와 --out 이 필요하다"])
    text, plan = render(p, compose, a.host, os.path.dirname(os.path.abspath(a.compose)), a.secrets_dir, a.out)
    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, "compose.placement.yaml"), "w", encoding="utf-8").write(text)
    json.dump(plan, open(os.path.join(a.out, "plan.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps(plan))
