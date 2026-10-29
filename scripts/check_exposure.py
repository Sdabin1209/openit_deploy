#!/usr/bin/env python3
"""config/Caddyfile 이 영역 이미지의 노출 선언(라벨 io.openit.exposure, 계약 Exposure)과 같은지 대조한다. 어긋나면 종료 1.
사용: check_exposure.py --inspect <JSON> [--caddyfile config/Caddyfile] [--known config/exposure-known-diffs.json]
  --inspect: {"<서비스>": {"labels": {...}, "exposed_ports": ["8080/tcp"], "user": "10001"}}  (check-exposure.sh 가 docker inspect 로 만든다)
종료 코드: 0 일치, 1 어긋남, 2 사용 오류, 3 검증하지 못함(라벨 없음 등: 통과가 아니다).
대조 방식(ADR 0043): Caddyfile 을 만들지 않고 대조한다. 비교하는 것은 서비스별로 (경로, 메서드, 인증 종류, 역할, 상류 토큰 이름, 사용자 헤더, 연결·응답헤더·읽기 시간 제한)과
  거부 경로(목록의 denied 는 Caddyfile 에서 상류로 가지 않아야 한다). 라벨에 없는 노출을 Caddyfile 이 내도 어긋남이다.
Caddyfile 읽기: 의도적으로 작은 구문 분석기다(블록 `{ }`, `(스니펫)` 와 `import 이름 인자`, `@이름` 매처, handle/handle_path, reverse_proxy). Caddy 자체로 JSON 변환(caddy adapt)하지 않는다:
  비밀 파일 치환 {file.*} 이 변환 때 파일을 읽고, 생성되는 계정·기기 조각이 필요하기 때문이다(ADR 0043)."""
import argparse, fnmatch, json, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
ANY = "*"


def tokens(line):
    out, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if c in " \t": i += 1; continue
        if c == "#": break
        if c in "\"`":
            j = i + 1
            while j < n and line[j] != c: j += 2 if (c == '"' and line[j] == "\\") else 1
            out.append(line[i + 1:j]); i = j + 1; continue
        j = i
        while j < n and line[j] not in " \t": j += 1
        out.append(line[i:j]); i = j
    return out


def parse(text):
    root = {"t": [], "c": []}; stack = [root]
    for raw in text.splitlines():
        t = tokens(raw)
        if not t: continue
        if t == ["}"]: stack.pop(); continue
        node = {"t": t, "c": []}
        if t[-1] == "{" and not raw.rstrip().endswith("`"):
            node["t"] = t[:-1]; stack[-1]["c"].append(node); stack.append(node)
        else:
            stack[-1]["c"].append(node)
    return root


def expand(children, snippets, args=()):
    """import 이름 인자... 를 스니펫 내용으로 펼친다({args[i]} 치환). 정의 없는 이름(authenticate, role_matchers...)은 표지로 남긴다."""
    out = []
    for n in children:
        t = n["t"]
        if t and t[0] == "import" and len(t) >= 2 and t[1] in snippets:
            out.extend(expand(snippets[t[1]], snippets, tuple(t[2:])))
            continue
        sub = lambda s: re.sub(r"\{args\[(\d+)\]\}", lambda m: args[int(m.group(1))] if int(m.group(1)) < len(args) else m.group(0), s)
        out.append({"t": [sub(x) for x in t], "c": expand(n["c"], snippets, args)})
    return out


def dur_ms(v):
    m = re.fullmatch(r"(\d+)(ms|s|m|h)", v)
    return int(m.group(1)) * {"ms": 1, "s": 1000, "m": 60000, "h": 3600000}[m.group(2)] if m else None


def role_of(matcher, roles):
    """@role_<이름> 매처 -> 계약 역할 이름. 이름 규칙은 gateway-lib.sh 가 만드는 것과 같다(release- 접두어를 뗀다)."""
    for r in roles:
        if matcher == "@role_" + r.replace("release-", ""): return r
    return None


def collect(caddy_text, roles):
    root = parse(caddy_text)
    snippets = {n["t"][0].strip("()"): n["c"] for n in root["c"] if n["t"] and re.fullmatch(r"\(.+\)", n["t"][0])}
    site = next(n for n in root["c"] if n["t"] and n["t"][0].startswith("{$GATEWAY_HOSTS"))
    body = expand(site["c"], snippets)
    matchers = {}
    for n in body:
        if n["t"] and n["t"][0].startswith("@"):
            m = {"paths": [], "methods": []}
            lines = n["c"] if n["c"] else [{"t": n["t"][1:], "c": []}]
            for l in lines:
                if l["t"] and l["t"][0] == "path": m["paths"] += l["t"][1:]
                if l["t"] and l["t"][0] == "method": m["methods"] += l["t"][1:]
            matchers[n["t"][0]] = m
    proxies, locals_, denied = [], [], []
    order = [0]

    def lookup(t):
        if not t: return {"paths": ["/*"], "methods": []}
        if t[0].startswith("@"): return matchers.get(t[0], {"paths": [], "methods": []})
        return {"paths": [t[0]], "methods": []}

    def walk(children, ctx):
        for n in children:
            t = n["t"]
            if not t: continue
            k = t[0]
            if k == "import" and t[1] == "authenticate": ctx = dict(ctx, auth="account")
        for n in children:
            t = n["t"]
            if not t: continue
            k = t[0]
            if k in ("handle", "handle_path"):
                a = t[1:]
                if a and a[0] in ("@device_cert", "@device_ok"):
                    walk(n["c"], dict(ctx, auth="device-token")); continue
                if a and a[0].startswith("@role_"):
                    r = role_of(a[0], roles)
                    walk(n["c"], dict(ctx, roles=ctx["roles"] + ([r] if r else []))); continue
                if ctx["paths"] is not None and not a:   # 매처 없는 안쪽 handle: 403 거절 자리
                    walk(n["c"], ctx); continue
                m = lookup(a)
                walk(n["c"], dict(ctx, paths=m["paths"], methods=m["methods"], auth=ctx["auth"], roles=[]))
            elif k == "reverse_proxy":
                host = t[1].split(":")[0]; port = t[1].split(":")[1] if ":" in t[1] else ""
                e = {"host": host, "port": port, "paths": ctx["paths"] or ["/*"], "methods": ctx["methods"], "auth": ctx["auth"] or "none", "roles": sorted(set(ctx["roles"])),
                     "upstream_token": None, "user_header": None, "timeouts": {}, "order": order[0]}
                order[0] += 1
                def scan(cs):
                    for c in cs:
                        ct = c["t"]
                        if ct[:1] == ["header_up"]:
                            if ct[1] == "Authorization" and len(ct) > 2:
                                m = re.search(r"\{file\./run/secrets/([^}]+)\}", ct[2]); e["upstream_token"] = m.group(1) if m else None
                            if ct[1] == "X-Openit-User": e["user_header"] = "set"
                            if ct[1] == "-X-Openit-User": e["user_header"] = "strip"
                        if ct[:1] == ["dial_timeout"]: e["timeouts"]["dial"] = dur_ms(ct[1])
                        if ct[:1] == ["response_header_timeout"]: e["timeouts"]["response_header"] = dur_ms(ct[1])
                        if ct[:1] == ["read_timeout"]: e["timeouts"]["read"] = dur_ms(ct[1])
                        if ct[:1] == ["flush_interval"]: e["streaming"] = True
                        scan(c["c"])
                scan(n["c"])
                if e["auth"] == "account" and not e["roles"]: e["roles"] = []
                proxies.append(e)
            elif k == "respond":
                code = t[-1]
                loc = {"paths": ctx["paths"] or [], "methods": ctx["methods"], "order": order[0], "code": code}
                order[0] += 1
                if ctx["paths"] and not ctx["auth"] and not ctx["roles"]:
                    (denied if code == "404" else locals_).append(loc)
            elif k in ("redir",):
                pass
            else:
                if n["c"] and k not in ("reverse_proxy", "request_body", "header", "log", "tls", "transport"):
                    pass

    # 사이트 바로 아래의 handle 들만 최상위 노출로 본다(handle_errors 는 제외)
    for n in body:
        t = n["t"]
        if t and t[0] in ("handle", "handle_path", "redir") and not (t[1:2] and t[1].startswith("@csrf")):
            walk([n], {"paths": None, "methods": [], "auth": None, "roles": []})
    hs = [dict(e, kind="proxy") for e in merge(proxies)] + [dict(x, kind="respond") for x in locals_ + denied]
    hs.sort(key=lambda h: h["order"])
    return hs


def covers(q, p):
    return q == p or fnmatch.fnmatchcase(p, q)


def first_match(handlers, p, m):
    """Caddy 의 handle 은 소스 순서대로 처음 맞는 하나만 실행한다. m == ANY 는 메서드 제한이 없는 핸들러만 모든 메서드를 덮는다."""
    for h in handlers:
        if not any(covers(q, p) for q in h["paths"]): continue
        if h["methods"] and (m == ANY or m not in h["methods"]): continue
        return h
    return None


def merge(proxies):
    """같은 (호스트, 경로, 메서드, 상류 토큰, 사용자 헤더)인 핸들러(예: 두 역할이 같은 스니펫을 쓴다)는 역할을 합쳐 하나로 본다."""
    out = {}
    for e in proxies:
        k = (e["host"], tuple(e["paths"]), tuple(e["methods"]), e["upstream_token"], e["user_header"], e["auth"])
        if k in out: out[k]["roles"] = sorted(set(out[k]["roles"]) | set(e["roles"]))
        else: out[k] = dict(e)
    return list(out.values())


def compare(svc, label, handlers, hosts, oci):
    diffs, used = [], set()
    mine_hosts = {h for h, s in hosts.items() if s == svc}
    for r in label["routes"]:
        kind = r["auth"]["kind"]
        ms = r.get("methods") or ([ "GET", "POST", "PUT", "PATCH", "DELETE" ] if kind == "denied" else [ANY])   # 거부는 어느 메서드로든 상류에 닿으면 어긋남
        for p in r["paths"]:
            for m in ms:
                h = first_match(handlers, p, m)
                tag = f"{svc} {m if m != ANY else '*'} {p}"
                is_mine = h is not None and h["kind"] == "proxy" and h["host"] in mine_hosts
                if kind == "denied":
                    if is_mine: diffs.append(f"{tag}: 라벨은 거부(denied)인데 Caddyfile 이 {h['host']} 로 프록시한다({','.join(h['paths'])})")
                    continue
                if not is_mine:
                    what = "처리하는 핸들러가 없다" if h is None else (f"{h['host']} 로 간다" if h["kind"] == "proxy" else f"게이트웨이가 직접 응답한다({h['code']})")
                    diffs.append(f"{tag}: 라벨은 노출한다고 선언했는데 Caddyfile 은 {what}"); continue
                used.add(id(h))
                if h["auth"] != kind: diffs.append(f"{tag}: 인증 종류 라벨 {kind} / Caddyfile {h['auth']}")
                lr = sorted(r["auth"].get("roles", []))
                if kind == "account" and lr != h["roles"]: diffs.append(f"{tag}: 역할 라벨 {lr} / Caddyfile {h['roles']}")
                if r.get("upstream_token") != h["upstream_token"]: diffs.append(f"{tag}: 상류 토큰 라벨 {r.get('upstream_token')} / Caddyfile {h['upstream_token']}")
                if r.get("user_header") != h["user_header"]: diffs.append(f"{tag}: 사용자 헤더 라벨 {r.get('user_header')} / Caddyfile {h['user_header']}")
                for tk, tv in r.get("timeouts_ms", {}).items():
                    if h["timeouts"].get(tk) != tv: diffs.append(f"{tag}: 시간 제한 {tk} 라벨 {tv}ms / Caddyfile {h['timeouts'].get(tk)}")
                if bool(r.get("streaming")) != bool(h.get("streaming")): diffs.append(f"{tag}: streaming 라벨 {bool(r.get('streaming'))} / Caddyfile {bool(h.get('streaming'))}")
    for h in handlers:
        if h["kind"] == "proxy" and h["host"] in mine_hosts and id(h) not in used:
            diffs.append(f"{svc} {','.join(h['methods']) or '*'} {','.join(h['paths'])}: Caddyfile 은 노출하는데 라벨 선언이 이 핸들러에 닿는 경로가 없다")
    # 포트·사용자: 이미지 OCI 설정에서 읽는다(StaticImageInterface 대신)
    ports = {x.split("/")[0] for x in oci.get("exposed_ports", [])}
    for h in handlers:
        if h["kind"] == "proxy" and h["host"] in mine_hosts and h["port"] and h["port"] not in ports:
            diffs.append(f"{svc}: Caddyfile 상류 포트 {h['port']} 가 이미지 ExposedPorts {sorted(ports)} 에 없다")
    if oci.get("user") in ("", "0", "root", None): diffs.append(f"{svc}: 이미지 Config.User 가 root 이거나 비어 있다({oci.get('user')!r})")
    return sorted(set(diffs))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--inspect", required=True); ap.add_argument("--caddyfile", default=str(ROOT / "config/Caddyfile"))
    ap.add_argument("--known", default=str(ROOT / "config/exposure-known-diffs.json")); ap.add_argument("--hosts", default=str(ROOT / "config/exposure-hosts.json"))
    ap.add_argument("--roles", default="staff operator release-approver reviewer author clinical-reviewer")
    a = ap.parse_args()
    insp = json.loads(pathlib.Path(a.inspect).read_text()); hosts = json.loads(pathlib.Path(a.hosts).read_text())
    known = json.loads(pathlib.Path(a.known).read_text()) if pathlib.Path(a.known).is_file() else {}
    from boundary_contracts import validator
    handlers = collect(pathlib.Path(a.caddyfile).read_text(encoding="utf-8"), a.roles.split())
    allp, unverified = [], []
    for svc, o in sorted(insp.items()):
        raw = (o.get("labels") or {}).get("io.openit.exposure")
        if not raw:
            # 게이트웨이가 프록시하는 서비스(config/exposure-hosts.json)의 라벨이 없으면 대조할 수 없다. 프록시하지 않는 서비스는 노출이 없으므로 알리기만 한다
            if svc in hosts.values(): unverified.append(f"{svc}: 라벨 io.openit.exposure 가 없다")
            else: print(f"참고: {svc} 는 라벨 io.openit.exposure 가 없지만 게이트웨이가 프록시하지 않는다")
            continue
        label = json.loads(raw)
        errs = [e.message[:100] for e in validator("Exposure").iter_errors(label)]
        if errs: allp.append(f"{svc}: 라벨이 계약 Exposure 를 어긴다: {errs[0]}"); continue
        for d in compare(svc, label, handlers, hosts, o): allp.append(d)
    new = [d for d in allp if d not in known]; stale = [k for k in known if k not in allp and any(k.startswith(s + " ") or k.startswith(s + ":") for s in insp)]
    for d in new: print("어긋남:", d)
    for k in stale: print("낡은 예외(이제 어긋나지 않는다, config/exposure-known-diffs.json 에서 지운다):", k)
    for u in unverified: print("검증 못 함:", u)
    held = [d for d in allp if d in known]
    if held: print(f"알려진 어긋남 {len(held)}건(이유는 config/exposure-known-diffs.json): 통과로 세지 않고 남겨 둔다")
    if new or stale: return 1
    if unverified: return 3
    print(f"일치: 서비스 {len(insp)}개의 노출 선언이 Caddyfile 과 같다 (알려진 어긋남 {len(held)}건 제외)"); return 0


if __name__ == "__main__":
    sys.exit(main())
