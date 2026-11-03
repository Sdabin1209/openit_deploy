#!/usr/bin/env python3
"""deploy 스크립트의 https /healthz·/readyz 확인은 상태 코드만이 아니라 본문(HealthStatus 의 status, 게이트웨이는 ok)까지 읽는다.
왜: TLS 사이드카에 맞지 않는 Host 로 부르면 Caddy 가 본문 없는 200 을 돌려줘, 코드만 보는 점검이 헛통과했다(4차 E2E, 호스트 쪽 추론 서버 /healthz).
규칙: 줄에 https URL 과 /healthz|/readyz 가 있고 curl `-o /dev/null` 이거나 urlopen 인데 본문을 읽지 않으면(read(, json.load, grep, -w 로 본문+코드) 실패한다.
포트가 열렸는지만 기다리는 줄은 `# port-wait`, 상태 코드가 계약인 줄(TLS 신뢰 점검, 게이트웨이 /readyz)은 `# status-code-ok: 이유` 로 면제한다. 사용: python3 scripts/test_health_checks_read_body.py"""
import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL = re.compile(r"https://[^\s\"']*/(healthz|readyz)")
READS = re.compile(r"\.read\(|json\.load|grep|awk|\| *tr |-w '\\n|\$\(curl[^)]*\) *\|")


def offenders(text, name):
    bad = []
    for i, l in enumerate(text.splitlines(), 1):
        if l.lstrip().startswith("#") or "port-wait" in l or "status-code-ok" in l or not URL.search(l):
            continue
        discards = "-o /dev/null" in l or ("urlopen" in l and not READS.search(l))
        if discards and not READS.search(l):
            bad.append(f"{name}:{i}")
    return bad


class T(unittest.TestCase):
    def test_scripts_read_the_body(self):
        bad = []
        for f in sorted((ROOT / "scripts").glob("*.sh")) + sorted((ROOT / "scripts").glob("*.py")):
            if f.name == pathlib.Path(__file__).name:
                continue
            bad += offenders(f.read_text(encoding="utf-8"), f.name)
        self.assertEqual(bad, [], "https 건강 확인이 본문을 읽지 않는다(상태 코드만): 본문의 status 를 보거나, 포트 대기면 줄에 `# port-wait` 를 단다")

    def test_detects_status_only_checks(self):
        self.assertTrue(offenders("curl -s -o /dev/null -w '%{http_code}' https://h/healthz", "x"))
        self.assertTrue(offenders("python -c \"urllib.request.urlopen('https://h/healthz',timeout=3)\"", "x"))
        self.assertFalse(offenders("python -c \"urllib.request.urlopen('https://h/healthz').read()\"", "x"))
        self.assertFalse(offenders("curl -s -o /dev/null https://h/healthz  # port-wait: 포트 열림만", "x"))


if __name__ == "__main__":
    unittest.main()
