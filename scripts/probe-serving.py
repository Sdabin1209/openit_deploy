#!/usr/bin/env python3
"""떠 있는 model-serving 의 extract 와 respond 에 입력 묶음을 보내 결과를 집계한다(표준 라이브러리만 쓴다). docs/RUN.md '추론 서버 측정 도구'.
H1(24GB 실측)용 지연 표: extract·respond 각각의 호출 수, 성공률, 콜드 첫 호출(따로), 이후 p50/p95/max, X-Openit-Attempts>1 인 재시도 호출의 호출 수와 p50/p95/max(따로). 백분위는 최근접 순위(nearest-rank)이고 표본이 20 미만이면 p95 는 max 와 같다.
집계: 성공 / OUTPUT_INVALID / 그 밖의 실패 건수, details.violations 의 키워드별 빈도("경로:키워드" 의 키워드), 지연(첫 호출 대 이후 중앙값), X-Openit-Outcome 분포.
토큰은 파일에서 읽고 값을 출력하지 않는다. 입력·모델 원문·발화는 출력하지 않는다(경로와 키워드 이름만).

사용:
  scripts/probe-serving.py --demo [--token-file F] [--repeat N] [--inputs FILE]      데모 스택(기본 프로젝트 deploy-demo)의 model-serving. 토큰 기본은 state/demo/secrets/tokens/inference-survey-service
  scripts/probe-serving.py --url http://HOST:PORT --token-file F [--release-id ID] [--inputs FILE] [--repeat N] [--concurrency K]
입력 파일: ExtractRequest{input, flow, fields}(계약 3.0) 하나, 그 배열, 또는 {"inputs": [...]}. 없으면 boundary-contracts 예제 ExtractRequest.with-fields 의 발화를 내장 발화 목록으로 바꿔 넣는다.
종료 코드: 0 = 호출 전부 응답을 받아 집계함(OUTPUT_INVALID 가 있어도 0: 측정 도구이지 합격 판정이 아니다), 2 = 사용 오류, 3 = 서버에 닿지 못함·릴리스를 못 찾음.
"""
from __future__ import annotations
import argparse, collections, json, os, pathlib, statistics, subprocess, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
EXAMPLE = ROOT.parent / "boundary-contracts" / "examples" / "ExtractRequest.with-fields.json"
DEFAULT_UTTERANCES = [
    "십 년 전에 고혈압 진단을 받았어요.", "아니요 없어요.", "네 있어요.", "잘 모르겠어요.", "약은 안 먹어요.",
    "작년부터 먹고 있어요.", "아버지가 당뇨가 있으셨어요.", "하루에 한 갑 정도 피워요.", "술은 안 마셔요.", "일주일에 세 번이요.",
]


def build_inputs(path: str | None, repeat: int) -> list[dict]:
    if path:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        items = data["inputs"] if isinstance(data, dict) and "inputs" in data else (data if isinstance(data, list) else [data])
        if not items or not all(isinstance(x, dict) and {"input", "flow", "fields"} <= set(x) for x in items): raise SystemExit("입력 파일은 ExtractRequest{input, flow, fields} 객체(들)여야 한다(계약 3.0: flow·fields 필수)")
    else:
        base = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        items = [{**base, "input": {**base["input"], "user_utterance": u}} for u in DEFAULT_UTTERANCES]
    return [dict(x) for _ in range(repeat) for x in items]


def keyword_of(violation: str) -> str:
    """"/values/0/key:pattern" -> "pattern". 키워드가 없는 항목("json" 등)은 그대로."""
    return violation.rsplit(":", 1)[1] if ":" in violation else violation


def classify(status: int, headers: dict, body) -> dict:
    """한 호출의 결과를 집계용 레코드로 줄인다. body 는 파싱된 JSON(또는 문자열). 발화·값은 담지 않는다."""
    h = {k.lower(): v for k, v in headers.items()}
    rec = {"status": status, "outcome": h.get("x-openit-outcome") or "-", "attempts": h.get("x-openit-attempts"), "reason": None, "violations": []}
    if status == 200: rec["kind"] = "ok"
    else:
        det = (body.get("details") if isinstance(body, dict) else None) or {}
        rec["reason"] = det.get("reason")
        if status == 503 and rec["reason"] == "OUTPUT_INVALID":
            rec["kind"] = "output_invalid"; rec["violations"] = [str(v) for v in det.get("violations") or []]
        else: rec["kind"] = "other_error"
    return rec


def summarize(results: list[dict]) -> dict:
    """results: [{kind, outcome, latency_s, violations, status, ...}] (호출 순서대로; 첫 항목이 첫 호출). 순수 함수(단위 시험 대상)."""
    n = len(results)
    kinds = collections.Counter(r["kind"] for r in results)
    outcomes = collections.Counter(r["outcome"] for r in results)
    kw = collections.Counter(keyword_of(v) for r in results for v in r["violations"])
    paths = collections.Counter(v for r in results for v in r["violations"])
    lat = [r["latency_s"] for r in results]
    rest = lat[1:]
    return {"calls": n, "ok": kinds.get("ok", 0), "output_invalid": kinds.get("output_invalid", 0), "other_error": kinds.get("other_error", 0),
            "other_status": dict(collections.Counter(r["status"] for r in results if r["kind"] == "other_error")),
            "outcomes": dict(outcomes), "keywords": dict(kw), "violations": dict(paths),
            "latency": {"first_s": lat[0] if lat else None, "rest_median_s": statistics.median(rest) if rest else None,
                        "rest_min_s": min(rest) if rest else None, "rest_max_s": max(rest) if rest else None}}


def render(s: dict) -> str:
    n = s["calls"]; pct = lambda x: f"{(100.0 * x / n):.1f}%" if n else "-"
    f = lambda v: "-" if v is None else f"{v:.3f}s"
    L = ["", "== 집계", f"  호출 {n}건: 성공 {s['ok']} ({pct(s['ok'])}), OUTPUT_INVALID {s['output_invalid']} ({pct(s['output_invalid'])}), 그 밖의 실패 {s['other_error']} ({pct(s['other_error'])})"]
    if s["other_status"]: L.append("  그 밖의 실패 HTTP 상태: " + ", ".join(f"{k}={v}" for k, v in sorted(s["other_status"].items())))
    L += ["", "-- X-Openit-Outcome 분포 (헤더가 없으면 '-')"] + [f"  {k:10} {v:5}" for k, v in sorted(s["outcomes"].items())]
    L += ["", "-- details.violations 키워드별 빈도 ('경로:키워드' 의 키워드)"]
    L += [f"  {k:24} {v:5}" for k, v in sorted(s["keywords"].items(), key=lambda kv: (-kv[1], kv[0]))] or ["  (없음)"]
    if s["violations"]:
        L += ["", "-- 경로:키워드 상위 10"] + [f"  {k:48} {v:5}" for k, v in sorted(s["violations"].items(), key=lambda kv: (-kv[1], kv[0]))[:10]]
    la = s["latency"]
    L += ["", "-- 지연", f"  첫 호출          {f(la['first_s'])}", f"  이후 중앙값     {f(la['rest_median_s'])}  (최소 {f(la['rest_min_s'])}, 최대 {f(la['rest_max_s'])}, 이후 {max(n - 1, 0)}건)"]
    return "\n".join(L)


def pctl(vals, q):
    """최근접 순위 백분위(q 는 0~100). 빈 목록은 None."""
    if not vals: return None
    v = sorted(vals); k = max(1, -(-len(v) * q // 100)); return v[int(k) - 1]


def lat_stats(vals):
    return {"n": len(vals), "p50": pctl(vals, 50), "p95": pctl(vals, 95), "max": max(vals) if vals else None}


def table_row(name, results):
    """엔드포인트 하나의 지연 표 행. results 는 호출 순서(첫 항목 = 콜드 첫 호출). 순수 함수(단위 시험 대상)."""
    n = len(results); ok = [r for r in results if r["status"] == 200]
    warm = [r for r in results[1:]]
    att = lambda r: int(r["attempts"]) if str(r.get("attempts") or "").isdigit() else 1
    retried = [r for r in results if att(r) > 1]
    return {"name": name, "calls": n, "ok": len(ok), "fallback": sum(1 for r in results if r["outcome"] == "fallback"),
            "cold_s": results[0]["latency_s"] if results else None,
            "warm": lat_stats([r["latency_s"] for r in warm]), "retried": {"calls": len(retried), **lat_stats([r["latency_s"] for r in retried])}}


def render_table(rows):
    f = lambda v: "-" if v is None else f"{v:.3f}"
    L = ["", "== 지연 표 (초). 콜드 = 첫 호출 1건, 이후 = 나머지. 재시도 = X-Openit-Attempts > 1 인 호출(전체에서 따로 집계). 표본 20 미만이면 p95 = max",
         f"  {'엔드포인트':8} {'호출':>5} {'성공':>5} {'성공률':>7} {'fallback':>8} {'콜드첫호출':>10} {'이후n':>6} {'p50':>7} {'p95':>7} {'max':>7} | {'재시도n':>7} {'p50':>7} {'p95':>7} {'max':>7}"]
    for r in rows:
        w, t = r["warm"], r["retried"]
        L.append(f"  {r['name']:8} {r['calls']:5} {r['ok']:5} {(100.0 * r['ok'] / r['calls'] if r['calls'] else 0):6.1f}% {r['fallback']:8} {f(r['cold_s']):>10} {w['n']:6} {f(w['p50']):>7} {f(w['p95']):>7} {f(w['max']):>7} | {t['calls']:7} {f(t['p50']):>7} {f(t['p95']):>7} {f(t['max']):>7}")
    return "\n".join(L)


def call_respond(url: str, token: str, release: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(f"{url}/v1/releases/{release}/respond", data=json.dumps(body, ensure_ascii=False).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {token}"); req.add_header("Content-Type", "application/json")
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: st, hd, raw = r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e: st, hd, raw = e.code, dict(e.headers), e.read()
    dt = time.perf_counter() - t
    try: parsed = json.loads(raw)
    except ValueError: parsed = None
    rec = classify(st, hd, parsed); rec["latency_s"] = dt
    return rec


def respond_inputs(repeat: int) -> list[dict]:
    files = sorted((ROOT.parent / "boundary-contracts" / "examples").glob("ResponseRequest*.json"))
    items = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    if not items: raise SystemExit("boundary-contracts/examples 에 ResponseRequest 예제가 없다")
    return [dict(x) for _ in range(repeat) for x in items]


def call_extract(url: str, token: str, release: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(f"{url}/v1/releases/{release}/extract", data=json.dumps(body, ensure_ascii=False).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {token}"); req.add_header("Content-Type", "application/json")
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: st, hd, raw = r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e: st, hd, raw = e.code, dict(e.headers), e.read()
    dt = time.perf_counter() - t
    try: parsed = json.loads(raw)
    except ValueError: parsed = None
    rec = classify(st, hd, parsed); rec["latency_s"] = dt
    return rec


def get_json(url: str, token: str, path: str, timeout: float = 15):
    req = urllib.request.Request(url + path); req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read())


def demo_url(project: str, docker: str) -> str:
    """데모 스택의 model-serving 호스트 포트(Docker 배정)를 묻는다. compose 프로젝트 라벨로 컨테이너를 찾고 docker port 로 읽는다."""
    r = subprocess.run([docker, "compose", "-p", project, "port", "model-serving", "8080"], capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    if r.returncode != 0 or not out:
        r = subprocess.run([docker, "port", f"{project}-model-serving-1", "8080/tcp"], capture_output=True, text=True); out = r.stdout.strip().splitlines()
    if not out: raise SystemExit(f"model-serving 의 포트를 찾지 못했다(프로젝트 {project} 가 떠 있나? scripts/demo.sh status)")
    return "http://127.0.0.1:" + out[0].rsplit(":", 1)[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--demo", action="store_true", help="데모 스택의 model-serving(포트는 Docker 배정)")
    ap.add_argument("--project", default=os.environ.get("DEMO_PROJECT", "deploy-demo")); ap.add_argument("--docker", default="docker")
    ap.add_argument("--url", default=""); ap.add_argument("--token-file", default="")
    ap.add_argument("--release-id", default=""); ap.add_argument("--inputs", default="")
    ap.add_argument("--repeat", type=int, default=3, help="입력 묶음을 몇 번 반복할지(기본 3)")
    ap.add_argument("--concurrency", type=int, default=1, help="첫 호출은 혼자 보내고, 나머지를 이 수만큼 동시에 보낸다")
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--endpoints", default="extract,respond", help="측정할 엔드포인트(쉼표): extract, respond. 기본 둘 다. respond 입력은 boundary-contracts 의 ResponseRequest 예제")
    a = ap.parse_args(argv)
    if bool(a.demo) == bool(a.url): print("--demo 또는 --url 중 하나를 준다", file=sys.stderr); return 2
    if a.repeat < 1 or a.concurrency < 1: print("--repeat, --concurrency 는 1 이상", file=sys.stderr); return 2
    tf = a.token_file or (str(ROOT / "state/demo/secrets/tokens/inference-survey-service") if a.demo else "")
    if not tf: print("--url 에는 --token-file 이 필요하다(토큰 값 하나가 든 파일)", file=sys.stderr); return 2
    try: token = pathlib.Path(tf).read_text().strip()
    except OSError as e: print(f"토큰 파일을 읽지 못했다: {tf} ({type(e).__name__})", file=sys.stderr); return 2
    if not token or token.startswith("EXTERNAL_INFERENCE_TOKEN="): print("토큰 파일은 토큰 값 하나만 담아야 한다", file=sys.stderr); return 2
    try: inputs = build_inputs(a.inputs or None, a.repeat)
    except (OSError, ValueError, SystemExit) as e: print(f"입력을 읽지 못했다: {e}", file=sys.stderr); return 2
    url = (demo_url(a.project, a.docker) if a.demo else a.url).rstrip("/")
    try:
        rel = a.release_id
        if not rel:
            loaded = get_json(url, token, "/v1/info").get("loaded") or []
            if not loaded: print("적재된 릴리스가 없다(--release-id 로 지정하거나 적재를 기다린다)", file=sys.stderr); return 3
            rel = loaded[-1]
        eps = [e for e in a.endpoints.split(",") if e]
        if not eps or any(e not in ("extract", "respond") for e in eps): print("--endpoints 는 extract, respond 중에서 쉼표로 준다", file=sys.stderr); return 2
        rows = []; print(f"== probe-serving: {url} 릴리스 {rel}, 엔드포인트 {','.join(eps)} (동시 {a.concurrency})")
        for ep in eps:
            ins = inputs if ep == "extract" else respond_inputs(a.repeat); fn = call_extract if ep == "extract" else call_respond
            res = [fn(url, token, rel, ins[0], a.timeout)]
            if a.concurrency == 1: res += [fn(url, token, rel, x, a.timeout) for x in ins[1:]]
            else:
                with ThreadPoolExecutor(a.concurrency) as ex: res += list(ex.map(lambda x: fn(url, token, rel, x, a.timeout), ins[1:]))
            if ep == "extract": print(f"-- extract 호출 {len(ins)}건"); print(render(summarize(res)))
            else: print(f"-- respond 호출 {len(ins)}건")
            rows.append(table_row(ep, res))
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"서버에 닿지 못했다: {type(e).__name__}", file=sys.stderr); return 3
    print(render_table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
