"""probe-serving.py 자체 시험: 집계 로직을 일부러 OUTPUT_INVALID 를 섞은 가짜 응답으로 확인하고, 가짜 HTTP 서버로 전체 경로(토큰 헤더, 첫 호출/이후 분리)를 돌린다.
실행: python3 scripts/test_probe_serving.py"""
import http.server, importlib.util, json, os, pathlib, sys, tempfile, threading, unittest

here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent))
from openit_deploy.components import serving_probe as P   # 집계(순수)
from openit_deploy.wiring import cli_probe_serving as W   # 연결(입력 읽기·호출·출력)

def classify(status, headers, body):
    """시험용: HTTP 응답 모양의 입력을 ProbeRecord 로 줄인다(실제 기록은 link_serving_probe 가 계약 클라이언트 결과로 만든다)."""
    h = {k.lower(): v for k, v in headers.items()}
    rec = {"status": status, "outcome": h.get("x-openit-outcome") or "-", "attempts": h.get("x-openit-attempts"), "reason": None, "violations": [], "latency_s": 0.0}
    if status == 200: rec["kind"] = "ok"
    else:
        det = (body.get("details") if isinstance(body, dict) else None) or {}
        rec["reason"] = det.get("reason")
        if status == 503 and rec["reason"] == "OUTPUT_INVALID": rec["kind"] = "output_invalid"; rec["violations"] = [str(v) for v in det.get("violations") or []]
        else: rec["kind"] = "other_error"
    return rec


EX = pathlib.Path(__file__).resolve().parents[2] / "boundary-contracts" / "examples"
INFO = {**json.loads((EX / "RuntimeInfo.loaded.json").read_text(encoding="utf-8")), "loaded": ["rel-x"]}   # 계약 예시(클라이언트가 RuntimeInfo 로 검증한다)
EXTRACT_OK = json.loads((EX / "ActionExtraction.next.json").read_text(encoding="utf-8"))
INV = lambda v: {"pipeline_schema_version": "3.0", "code": "UNAVAILABLE", "message": "x", "retryable": True, "details": {"reason": "OUTPUT_INVALID", "attempts": 3, "violations": v}}


class T(unittest.TestCase):
    def test_keyword(self):
        self.assertEqual(P.keyword_of("/values/0/key:pattern"), "pattern"); self.assertEqual(P.keyword_of("json"), "json"); self.assertEqual(P.keyword_of(":required"), "required")

    def test_classify_and_summarize(self):
        recs = [classify(200, {"X-Openit-Outcome": "ok"}, {}),
                classify(503, {}, INV(["/values/0/key:pattern", "/next_item:enum"])),
                classify(503, {}, INV(["/values/1/key:pattern"])),
                classify(503, {}, {"code": "UNAVAILABLE", "details": {"reason": "OTHER"}}),
                classify(404, {}, "x"),
                classify(200, {"x-openit-outcome": "ok"}, {})]
        for r, t in zip(recs, (1.0, 0.2, 0.4, 0.1, 0.3, 0.2)): r["latency_s"] = t
        s = P.summarize(recs)
        self.assertEqual((s["calls"], s["ok"], s["output_invalid"], s["other_error"]), (6, 2, 2, 2))
        self.assertEqual(s["keywords"], {"pattern": 2, "enum": 1}); self.assertEqual(s["violations"]["/values/0/key:pattern"], 1)
        self.assertEqual(s["outcomes"], {"ok": 2, "-": 4}); self.assertEqual(s["other_status"], {503: 1, 404: 1})
        self.assertEqual(s["latency"]["first_s"], 1.0); self.assertAlmostEqual(s["latency"]["rest_median_s"], 0.2)
        out = P.render(s); self.assertIn("pattern", out); self.assertIn("OUTPUT_INVALID 2", out)

    def test_empty_and_single(self):
        self.assertEqual(P.summarize([])["calls"], 0); P.render(P.summarize([]))
        r = classify(200, {}, {}); r["latency_s"] = 0.5; s = P.summarize([r]); self.assertIsNone(s["latency"]["rest_median_s"]); P.render(s)

    def test_inputs(self):
        self.assertEqual(len(W.build_inputs(None, 2)), 2 * len(W.DEFAULT_UTTERANCES))
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "i.json"; f.write_text(json.dumps({"inputs": [{"input": {}, "flow": {}, "fields": {}}]})); self.assertEqual(W.build_inputs(str(f), 3), [{"input": {}, "flow": {}, "fields": {}}] * 3)
            f.write_text("[]")
            with self.assertRaises(SystemExit): W.build_inputs(str(f), 1)

    def test_end_to_end_fake_server(self):
        seen = {"auth": set(), "n": 0}
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _send(self, code, obj, hdr=None):
                b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
                for k, v in (hdr or {}).items(): self.send_header(k, v)
                self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
            def do_GET(self): seen["auth"].add(self.headers.get("Authorization")); self._send(200, INFO)
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"])); seen["auth"].add(self.headers.get("Authorization")); seen["n"] += 1
                if seen["n"] % 3 == 0: self._send(503, INV(["/values/0/key:pattern"]))
                else: self._send(200, EXTRACT_OK, {"X-Openit-Outcome": "ok"})
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as d:
            tf = pathlib.Path(d) / "tok"; tf.write_text("SECRET-TOKEN-VALUE\n")
            import io, contextlib
            for conc in (1, 3):
                seen["n"] = 0; buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = W.main(["--url", f"http://127.0.0.1:{srv.server_address[1]}", "--token-file", str(tf), "--repeat", "1", "--concurrency", str(conc), "--endpoints", "extract"])
                out = buf.getvalue(); self.assertEqual(rc, 0, out)
                self.assertNotIn("SECRET-TOKEN-VALUE", out); self.assertIn("호출 10건: 성공 7", out); self.assertIn("OUTPUT_INVALID 3", out); self.assertIn("pattern", out)
        srv.shutdown(); self.assertEqual(seen["auth"], {"Bearer SECRET-TOKEN-VALUE"})

    def test_percentile_and_table(self):
        self.assertEqual(P.pctl([], 50), None); self.assertEqual(P.pctl([3, 1, 2], 50), 2); self.assertEqual(P.pctl(list(range(1, 101)), 95), 95); self.assertEqual(P.pctl([5], 95), 5)
        mk = lambda st, lat, att=None, out="ok": {"status": st, "latency_s": lat, "attempts": att, "outcome": out}
        rows = [mk(200, 9.0)] + [mk(200, 1.0 + i / 10) for i in range(8)] + [mk(200, 3.0, "2"), mk(503, 4.0, "3", "-"), mk(200, 0.5, "1", "fallback")]
        t = P.table_row("extract", rows)
        self.assertEqual((t["calls"], t["ok"], t["fallback"], t["cold_s"]), (12, 11, 1, 9.0))
        self.assertEqual(t["warm"]["n"], 11); self.assertEqual(t["warm"]["max"], 4.0)
        self.assertEqual((t["retried"]["calls"], t["retried"]["p50"], t["retried"]["max"]), (2, 3.0, 4.0))
        out = P.render_table([t, P.table_row("respond", [mk(200, 0.2)])])
        self.assertIn("extract", out); self.assertIn("respond", out); self.assertIn("9.000", out)   # 콜드 첫 호출이 따로 나온다
        self.assertEqual(P.table_row("x", [])["calls"], 0); P.render_table([P.table_row("x", [])])

    def test_respond_endpoint_and_table_end_to_end(self):
        paths = []
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                b = json.dumps(INFO).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"])); paths.append(self.path)
                if self.path.endswith("/respond"): b = "응답 문장".encode(); hd = {"Content-Type": "text/plain", "X-Openit-Outcome": "ok", "X-Openit-Attempts": "2" if len(paths) % 4 == 0 else "1"}
                else: b = json.dumps(EXTRACT_OK).encode(); hd = {"Content-Type": "application/json", "X-Openit-Outcome": "ok"}
                self.send_response(200); [self.send_header(k, v) for k, v in hd.items()]; self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as d:
            tf = pathlib.Path(d) / "tok"; tf.write_text("tok\n"); import io, contextlib; buf = io.StringIO()
            with contextlib.redirect_stdout(buf): rc = W.main(["--url", f"http://127.0.0.1:{srv.server_address[1]}", "--token-file", str(tf), "--repeat", "1"])
        srv.shutdown(); out = buf.getvalue(); self.assertEqual(rc, 0, out)
        self.assertIn("== 지연 표", out); self.assertTrue(any(p.endswith("/extract") for p in paths) and any(p.endswith("/respond") for p in paths))
        line = [l for l in out.splitlines() if l.strip().startswith("respond") and "%" in l][0]; self.assertIn("100.0%", line)
        self.assertEqual(W.main(["--url", "http://127.0.0.1:1", "--token-file", str(tf), "--endpoints", "bogus"]) in (2, 3), True)

    def test_usage_errors(self):
        self.assertEqual(W.main([]), 2); self.assertEqual(W.main(["--url", "http://127.0.0.1:1"]), 2)
        self.assertEqual(W.main(["--url", "http://127.0.0.1:1", "--token-file", "/nonexistent"]), 2)
        with tempfile.TemporaryDirectory() as d:
            tf = pathlib.Path(d) / "t"; tf.write_text("x"); self.assertEqual(W.main(["--url", "http://127.0.0.1:1", "--token-file", str(tf)]), 3)


if __name__ == "__main__": unittest.main()
