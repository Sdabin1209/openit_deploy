#!/usr/bin/env python3
"""인증 없는 요청에 공개 입구가 주는 응답을 점검한다(같은 망의 클라이언트 컨테이너에서 실행). 기대 응답은 계약에서 만든다(손 표 없음, 공개 입구 이미지의 점검 명령에 기대지 않는다):
  영역 Exposure 선언(`--exposures` 폴더, 파일마다 Exposure 스키마 하나)의 routes[].auth.kind 와 RUNTIME R3.13·R3.23, CONVENTIONS 9절(401·403·404), PUBLIC_API F절.
  - device-token: 인증 없음 -> 401, `WWW-Authenticate: Bearer`(R3.13, RFC 6750 3).
  - account / authenticated, 경로가 /v1/ 아래: 401, `WWW-Authenticate: Bearer realm="openit"`, 본문 BoundaryError(code=PERMISSION_DENIED)(R3.23).
  - account / authenticated, /v1/ 밖(화면) GET: `Accept: text/html` 이면 302 + Location(로그인 화면), 아니면 401 + `Bearer realm="openit"`(R3.23).
  - 선언 없는 /v1/ 경로: 404, 본문 code=NOT_FOUND(닫힌 면, CONVENTIONS 9절의 NOT_FOUND -> 404).
  - none·denied·machine-token 경로는 행이 없다(R3.23: none 은 세션 없이 열린다, denied·machine-token 은 공개 입구가 내보내지 않는다).
사용: check_unauth.py <https://이름:포트> --exposures 폴더 [--cacert 파일]   종료 코드: 0 모두 일치, 1 어긋남(또는 점검할 행 없음), 2 입력 오류. 인증서 검증을 끄지 않는다(https 는 --cacert 필수)."""
import argparse, http.client, json, pathlib, ssl, sys, urllib.parse

def rows(exposures):
    """(설명, 메서드, 경로, 요청 머리글, 기대) 목록. 기대 = {status, www(접두), code, location}"""
    out = []
    for f in sorted(pathlib.Path(exposures).glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for r in d.get("routes", []):
            kind = (r.get("auth") or {}).get("kind")
            method = (r.get("methods") or ["GET"])[0]
            for p in r["paths"]:
                path = p.replace("*", "x")
                api = path.startswith("/v1/")
                if kind == "device-token":
                    out.append((f"{d['service']} {method} {p} (device-token)", method, path, {}, {"status": 401, "www": "Bearer"}))
                elif kind in ("account", "authenticated"):
                    if api:
                        out.append((f"{d['service']} {method} {p} ({kind}, API)", method, path, {}, {"status": 401, "www": 'Bearer realm="openit"', "code": "PERMISSION_DENIED"}))
                    elif method == "GET":
                        out.append((f"{d['service']} GET {p} ({kind}, 화면, html)", "GET", path, {"Accept": "text/html"}, {"status": 302, "location": True}))
                        out.append((f"{d['service']} GET {p} ({kind}, 화면, 비html)", "GET", path, {"Accept": "application/json"}, {"status": 401, "www": 'Bearer realm="openit"'}))
    if out:
        out.append(("선언 없는 /v1/ 경로", "GET", "/v1/__openit-undeclared__", {}, {"status": 404, "code": "NOT_FOUND"}))
    return out

def fetch(base, method, path, headers, cafile):
    u = urllib.parse.urlsplit(base)
    if u.scheme == "https":
        if not cafile: raise SystemExit(2)
        conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=10, context=ssl.create_default_context(cafile=cafile))
    else:
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=10)
    conn.request(method, path, headers={"Host": u.netloc, **headers})
    r = conn.getresponse(); body = r.read(65536).decode("utf-8", "replace")
    res = (r.status, r.getheader("WWW-Authenticate") or "", r.getheader("Location") or "", body); conn.close(); return res

def judge(exp, got):
    st, www, loc, body = got; bad = []
    if st != exp["status"]: bad.append(f"상태 {st} (기대 {exp['status']})")
    if "www" in exp and not www.startswith(exp["www"]): bad.append(f"WWW-Authenticate '{www}' (기대 {exp['www']} 로 시작)")
    if exp.get("location") and not loc: bad.append("Location 이 없다")
    if "code" in exp:
        try: code = json.loads(body).get("code")
        except ValueError: code = None
        if code != exp["code"]: bad.append(f"본문 code {code!r} (기대 {exp['code']})")
    return bad

def main(argv):
    ap = argparse.ArgumentParser(); ap.add_argument("base"); ap.add_argument("--exposures", required=True); ap.add_argument("--cacert")
    a = ap.parse_args(argv)
    if a.base.startswith("https://") and not a.cacert: print("https 는 --cacert 가 필요하다(검증을 끄지 않는다)", file=sys.stderr); return 2
    if not pathlib.Path(a.exposures).is_dir(): print(f"선언 폴더가 없다: {a.exposures}", file=sys.stderr); return 2
    rs = rows(a.exposures)
    if not rs: print("FAIL 점검할 행이 없다(선언 폴더가 비었거나 인증이 필요한 경로가 없다)"); return 1
    fails = 0
    for desc, m, path, hdr, exp in rs:
        try: got = fetch(a.base, m, path, hdr, a.cacert)
        except (OSError, http.client.HTTPException) as e:
            print(f"FAIL {desc}: 요청 실패 {type(e).__name__}"); fails += 1; continue
        bad = judge(exp, got)
        if bad: print(f"FAIL {desc}: " + "; ".join(bad)); fails += 1
        else: print(f"PASS {desc}")
    print(f"{len(rs) - fails}/{len(rs)} 일치"); return 1 if fails else 0

if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
