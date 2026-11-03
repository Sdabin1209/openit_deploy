#!/usr/bin/env python3
"""평문 주소 금지 자체 점검(U99, ADR 0060): deploy 의 설정·compose·스크립트에 서비스 사이 http://<이름>:<포트> 주소가 없다.
헤드의 cross-area-check 와 같은 정규식이지만 백트래킹 결함을 막았다(포트 숫자 뒤에 숫자가 이어지지 않아야 /healthz·/readyz 예외가 선다).
예외: loopback(127.0.0.1, localhost) 뿐이다(경로 예외 없음). 사용: python3 scripts/test_no_plaintext_addresses.py"""
import pathlib, re, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
PLAIN = re.compile(r"http://(?!(?:127\.0\.0\.1|localhost|\[::1\])(?![A-Za-z0-9.-]))[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]+)?(?=[/\s\"\'\)]|$)")   # 헤드 cross-area-check 와 같은 규칙: loopback 만 예외, 경로 예외 없음, 점 든 호스트·IP 포함
NOVERIFY = re.compile("|".join(["verify" + r"\s*=\s*False", "ssl" + r"\.CERT_NONE", "check_hostname" + r"\s*=\s*False", "NODE_TLS_REJECT" + "_UNAUTHORIZED", "reject" + r"Unauthorized\s*:\s*false", "insecure_skip" + "_verify"]))   # 이 파일 자체가 헤드 점검에 걸리지 않게 조각으로 만든다
ALLOW = {}
bad = []
for f in subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split():
    p = ROOT / f
    if f.startswith(("build/", "docs/", "test/")) or p.suffix not in {".py", ".env", ".yaml", ".yml", ".json", ".sh", ""} and p.name != "Caddyfile" or f == "scripts/test_no_plaintext_addresses.py" or not p.is_file():
        continue
    for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        if (PLAIN.search(line) and f not in ALLOW and "noegress" not in line) or NOVERIFY.search(line):   # noegress: 바깥으로 못 나가는지 보는 음성 시험(일부러 외부 평문 주소)
            bad.append(f"{f}:{i}: {(PLAIN.search(line) or NOVERIFY.search(line)).group(0)}")
# 게이트웨이 Caddyfile 과 import 되는 조각의 모든 상류 지시자는 https:// 로 시작해야 한다. 스킴 없는 `이름:포트`는 Caddy 가 평문으로 해석한다(forward_auth 가 그렇게 남아 인증이 503 이 된 결함, ADR 0060)
UPSTREAM = re.compile(r"^\s*(reverse_proxy|forward_auth|php_fastcgi)\s+(?!\{)(\S+)")
for f in ["config/Caddyfile", *sorted(str(x.relative_to(ROOT)) for x in (ROOT / "config").glob("*.caddy")), *sorted(str(x.relative_to(ROOT)) for x in (ROOT / "config/gateway-tls").glob("*.caddy"))]:
    for i, line in enumerate((ROOT / f).read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        m = UPSTREAM.match(line)
        if m and not m.group(2).startswith("https://"):
            bad.append(f"{f}:{i}: {m.group(1)} {m.group(2)} (상류는 https:// 로 쓴다)")
print("\n".join(bad) or "통과: 평문 주소·검증 끄기 없음")
sys.exit(1 if bad else 0)
