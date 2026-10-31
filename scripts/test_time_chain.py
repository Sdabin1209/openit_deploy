#!/usr/bin/env python3
"""시간 상한 사슬 정적 시험(ADR 0047): 바깥이 안쪽보다 길다. 값은 각자의 정본에서 읽는다: gateway = config/Caddyfile 의 환자 경로(@kioskapi) 연결 + 응답 헤더, survey = config/survey.env 의 SURVEY_*_SECONDS, 키오스크 대기 = e2e_steps.py 의 KIOSK_WAIT_S(deploy 에는 키오스크 설정 파일이 없고, 값은 kiosk-frontend 영역이 정한다).
사슬(사용자 결정 2026-10-30): 키오스크 12s > gateway 10.5s > survey 턴 마감 9s > 값 추출 3s + 응답 생성 5s. 사용법: python3 scripts/test_time_chain.py"""
import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CADDY = (ROOT / "config/Caddyfile").read_text(encoding="utf-8")
STEPS = (ROOT / "scripts/e2e_steps.py").read_text(encoding="utf-8")


def secs(v):
    return float(v[:-2]) / 1000 if v.endswith("ms") else float(v.rstrip("s"))


def env(name):
    m = re.search(rf"^{name}=([0-9.]+)\s*$", (ROOT / "config/survey.env").read_text(encoding="utf-8"), re.M)
    assert m, f"config/survey.env 에 {name} 가 없다"
    return float(m.group(1))


def const(name):
    m = re.search(rf"^{name}\s*=\s*([0-9.]+)", STEPS, re.M)
    assert m, f"e2e_steps.py 에 {name} 가 없다"
    return float(m.group(1))


class Chain(unittest.TestCase):
    def values(self):
        blk = CADDY[CADDY.index("@kioskapi path"):]
        gw = secs(re.search(r"dial_timeout\s+([0-9.]+m?s)", blk).group(1)) + secs(re.search(r"response_header_timeout\s+([0-9.]+m?s)", blk).group(1))
        return {"kiosk": const("KIOSK_WAIT_S"), "gateway": gw, "turn": env("SURVEY_TURN_DEADLINE_SECONDS"), "extract": env("SURVEY_INFERENCE_EXTRACT_TIMEOUT_SECONDS"), "respond": env("SURVEY_INFERENCE_RESPOND_TIMEOUT_SECONDS")}

    def test_outer_is_longer_than_inner(self):
        v = self.values()
        self.assertGreater(v["kiosk"], v["gateway"], v)
        self.assertGreater(v["gateway"], v["turn"], v)
        self.assertGreater(v["turn"], v["extract"] + v["respond"], v)   # 한 턴이 추출과 응답을 순서대로 부르므로 합보다 길어야 마감이 먼저 오지 않는다

    def test_model_serving_deadlines_match_contract_table_and_survey(self):
        """model-serving 서버 쪽 요청 상한(config/model-serving.env, compose.inference.yaml)이 계약 시간표(extract 3.0·respond 5.0)와 같고 survey.env 의 호출별 상한과도 같으며, 사슬 규칙(survey 턴 > 추출 + 응답)을 지킨다. 명시하지 않으면 서버 기본값(respond 2.0)이 쓰여 respond 가 잘린다."""
        ms = (ROOT / "config/model-serving.env").read_text(encoding="utf-8")
        g = lambda txt, k: float(re.search(rf"^\s*{k}[=:]\s*\"?([0-9.]+)\"?\s*(#.*)?$", txt, re.M).group(1))
        inf = (ROOT / "compose.inference.yaml").read_text(encoding="utf-8")
        for src, txt in (("config/model-serving.env", ms), ("compose.inference.yaml", inf)):
            self.assertEqual((g(txt, "MODEL_RUNTIME_EXTRACT_DEADLINE_S"), g(txt, "MODEL_RUNTIME_RESPOND_DEADLINE_S")), (3.0, 5.0), f"{src}: 계약 CONVENTIONS 시간표(D119)와 다르다")
        self.assertIn("model-serving.env", (ROOT / "compose.yaml").read_text(encoding="utf-8"), "compose.yaml 의 model-serving 이 이 env 파일을 읽는다")
        v = self.values()
        self.assertEqual((g(ms, "MODEL_RUNTIME_EXTRACT_DEADLINE_S"), g(ms, "MODEL_RUNTIME_RESPOND_DEADLINE_S")), (v["extract"], v["respond"]), "서버 상한과 survey.env 의 호출별 상한이 다르다")
        self.assertGreater(v["turn"], g(ms, "MODEL_RUNTIME_EXTRACT_DEADLINE_S") + g(ms, "MODEL_RUNTIME_RESPOND_DEADLINE_S"))

    def test_decided_values(self):
        v = self.values()
        self.assertEqual((v["extract"], v["respond"], v["turn"], v["gateway"], v["kiosk"]), (3.0, 5.0, 9.0, 10.5, 12.0), "사용자 결정(2026-10-30)과 다르다: 바꾸려면 ADR 0047 을 대체하는 새 ADR 이 먼저다")

    def test_e2e_derived_limits_stay_below_kiosk(self):
        self.assertLess(const("SURVEY_TURN_DEADLINE_S") + const("CLIENT_EXTRA_S"), const("KIOSK_WAIT_S") + const("CLIENT_EXTRA_S"))
        self.assertEqual(const("SURVEY_TURN_DEADLINE_S"), env("SURVEY_TURN_DEADLINE_SECONDS"), "E2E 상수와 설정이 다르다")


def proxy_blocks():
    """config/Caddyfile 의 모든 `reverse_proxy <호스트>:8080 {` 블록 -> [(호스트, 본문, 연결 초, 응답 헤더 초)]. `import proxy_limits N` 은 스니펫의 연결 상한을 쓴다."""
    snippet_dial = secs(re.search(r"\(proxy_limits\)\s*\{.*?dial_timeout\s+([0-9.]+m?s)", CADDY, re.S).group(1))
    out = []
    for m in re.finditer(r"reverse_proxy ([a-z-]+):8080 \{", CADDY):
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(CADDY[i], 0); i += 1
        body = CADDY[m.end():i - 1]
        imp = re.search(r"import proxy_limits ([0-9.]+m?s)", body)
        if imp: dial, hdr = snippet_dial, secs(imp.group(1))
        else:
            d, h = re.search(r"dial_timeout\s+([0-9.]+m?s)", body), re.search(r"response_header_timeout\s+([0-9.]+m?s)", body)
            assert d and h, f"{m.group(1)} 블록에 연결·응답 헤더 상한이 없다"
            dial, hdr = secs(d.group(1)), secs(h.group(1))
        out.append((m.group(1), body, dial, hdr))
    return out


class ProxyChain(unittest.TestCase):
    """gateway 의 모든 상류 프록시 상한(연결 + 응답 헤더)이 사슬 규칙을 지킨다(ADR 0048, CONVENTIONS 시간표 D119): 바깥(클라이언트 대기)이 안쪽(gateway 상한)보다, gateway 상한이 서버 마감보다 길다."""

    def test_every_proxy_is_covered_and_follows_the_chain(self):
        turn, kiosk, staff, admin = env("SURVEY_TURN_DEADLINE_SECONDS"), const("KIOSK_WAIT_S"), const("STAFF_SCREEN_WAIT_S"), const("ADMIN_CONSOLE_WAIT_S")
        seen, bad = {}, []
        for host, body, dial, hdr in proxy_blocks():
            total = dial + hdr
            if host == "survey-service":
                if "read_timeout" in body: kind, lo, hi = "직원 API(@staffapi)", turn, staff
                elif hdr <= 2.0: kind, lo, hi = "/readyz", None, None    # 점검용 짧은 상한(연결 1s + 헤더 2s)은 사슬 밖
                else: kind, lo, hi = "키오스크 API(@kioskapi)", turn, kiosk
                if lo is not None and not (lo < total < hi): bad.append(f"{kind}: 연결 {dial}s + 헤더 {hdr}s = {total}s 는 ({lo}s, {hi}s) 사이여야 한다")
            elif host in ("release-gate", "ops-feedback-ingest", "question-authoring", "admin-console"):
                kind = host
                if not total < admin: bad.append(f"{host}: 연결 {dial}s + 헤더 {hdr}s = {total}s 는 관리 화면 대기 {admin}s 보다 짧아야 한다")
            else: kind = host   # kiosk-frontend 정적 화면 등: 사람이 쓰는 브라우저 화면, 대기 상한이 deploy 에 기록된 클라이언트가 없다
            seen[kind] = seen.get(kind, 0) + 1
        self.assertEqual(bad, [])
        for need in ("직원 API(@staffapi)", "키오스크 API(@kioskapi)", "release-gate", "ops-feedback-ingest", "question-authoring", "admin-console"):
            self.assertIn(need, seen, f"Caddyfile 에서 {need} 프록시를 찾지 못했다: 시험이 껍데기가 아닌지 본다")


if __name__ == "__main__":
    unittest.main()
