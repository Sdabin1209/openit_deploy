"""컴포넌트 serving_probe: 추론 서버 호출 기록(ProbeRecord)을 집계해 보고서를 만든다. 입력 ServingProbeRequest, 출력 ServingProbeResult. 호출 자체는 link_serving_probe, 입력 파일 읽기·출력은 wiring.
H1(24GB 실측)용 지연 표: extract·respond 각각의 호출 수, 성공률, 콜드 첫 호출(따로), 이후 p50/p95/max, X-Openit-Attempts>1 인 재시도 호출(따로). 백분위는 최근접 순위(nearest-rank)다.
집계: 성공 / OUTPUT_INVALID / 그 밖의 실패 건수, details.violations 의 키워드별 빈도("경로:키워드" 의 키워드), 지연(첫 호출 대 이후 중앙값), X-Openit-Outcome 분포. 입력·모델 원문·발화는 기록에 없다(경로와 키워드 이름만).
기록의 status 는 성공이면 200, 실패면 BoundaryError 코드 문자열이다(계약 클라이언트가 HTTP 상태 대신 오류 코드를 낸다, ADR 0045)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import ServingProbeRequest, ServingProbeResult

import collections
import statistics


def keyword_of(violation: str) -> str:
    """"/values/0/key:pattern" -> "pattern". 키워드가 없는 항목("json" 등)은 그대로."""
    return violation.rsplit(":", 1)[1] if ":" in violation else violation


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


def run(request: "ServingProbeRequest") -> "ServingProbeResult":
    """endpoints: [{name, records}] 순서대로. extract 는 집계 보고서를 먼저 붙이고, 마지막에 지연 표."""
    parts, rows = [], []
    for ep in request["endpoints"]:
        recs = ep["records"]
        if ep["name"] == "extract":
            parts.append(f"-- extract 호출 {len(recs)}건\n" + render(summarize(recs)))
        else:
            parts.append(f"-- respond 호출 {len(recs)}건")
        rows.append(table_row(ep["name"], recs))
    return {"sections": parts, "table": render_table(rows)}
