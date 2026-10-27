#!/usr/bin/env python3
"""떠 있는 model-serving 의 extract 에 입력 묶음을 보내 결과를 집계한다(표준 라이브러리만 쓴다). docs/RUN.md '추론 서버 측정 도구'.
집계: 성공 / OUTPUT_INVALID / 그 밖의 실패 건수, details.violations 의 키워드별 빈도("경로:키워드" 의 키워드), 지연(첫 호출 대 이후 중앙값), X-Openit-Outcome 분포.
토큰은 파일에서 읽고 값을 출력하지 않는다. 입력·모델 원문·발화는 출력하지 않는다(경로와 키워드 이름만).

사용:
  scripts/probe-serving.py --demo [--token-file F] [--repeat N] [--inputs FILE]      데모 스택(기본 프로젝트 deploy-demo)의 model-serving. 토큰 기본은 state/demo/secrets/tokens/inference-survey-service
  scripts/probe-serving.py --url http://HOST:PORT --token-file F [--release-id ID] [--inputs FILE] [--repeat N] [--concurrency K]
입력 파일: ActionExtractionInput 하나, 그 배열, 또는 {"inputs": [...]}. 없으면 boundary-contracts 예제 입력에 내장 발화 목록을 바꿔 넣는다.
종료 코드: 0 = 호출 전부 응답을 받아 집계함(OUTPUT_INVALID 가 있어도 0: 측정 도구이지 합격 판정이 아니다), 2 = 사용 오류, 3 = 서버에 닿지 못함·릴리스를 못 찾음.
"""
from __future__ import annotations
import argparse, collections, json, os, pathlib, statistics, subprocess, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
EXAMPLE = ROOT.parent / "boundary-contracts" / "examples" / "ActionExtractionInput.json"
DEFAULT_UTTERANCES = [
    "십 년 전에 고혈압 진단을 받았어요.", "아니요 없어요.", "네 있어요.", "잘 모르겠어요.", "약은 안 먹어요.",
    "작년부터 먹고 있어요.", "아버지가 당뇨가 있으셨어요.", "하루에 한 갑 정도 피워요.", "술은 안 마셔요.", "일주일에 세 번이요.",
]


def build_inputs(path: str | None, repeat: int) -> list[dict]:
    if path:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        items = data["inputs"] if isinstance(data, dict) and "inputs" in data else (data if isinstance(data, list) else [data])
        if not items or not all(isinstance(x, dict) for x in items): raise SystemExit("입력 파일은 ActionExtractionInput 객체(들)여야 한다")
    else:
        base = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        items = [{**base, "user_utterance": u} for u in DEFAULT_UTTERANCES]
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
        print(f"== probe-serving: {url} 릴리스 {rel}, 호출 {len(inputs)}건 (동시 {a.concurrency})")
        res = [call_extract(url, token, rel, inputs[0], a.timeout)]
        if a.concurrency == 1: res += [call_extract(url, token, rel, x, a.timeout) for x in inputs[1:]]
        else:
            with ThreadPoolExecutor(a.concurrency) as ex: res += list(ex.map(lambda x: call_extract(url, token, rel, x, a.timeout), inputs[1:]))
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"서버에 닿지 못했다: {type(e).__name__}", file=sys.stderr); return 3
    print(render(summarize(res)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
