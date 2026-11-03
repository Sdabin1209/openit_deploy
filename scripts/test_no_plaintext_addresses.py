#!/usr/bin/env python3
"""평문 주소 금지 자체 점검(U99, ADR 0060): deploy 의 설정·compose·스크립트에 서비스 사이 http://<이름>:<포트> 주소가 없다.
헤드의 cross-area-check 와 같은 정규식이지만 백트래킹 결함을 막았다(포트 숫자 뒤에 숫자가 이어지지 않아야 /healthz·/readyz 예외가 선다).
예외: 자기 자신의 루프백 프로브(127.0.0.1)와 /healthz·/readyz 프로브(게이트웨이 평문 포트 8080 의 정적 200). 사용: python3 scripts/test_no_plaintext_addresses.py"""
import pathlib, re, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
PLAIN = re.compile(r"http://[a-z][a-z0-9-]+:[0-9]+(?![0-9])(?!/(healthz|readyz))")
NOVERIFY = re.compile("|".join(["verify" + r"\s*=\s*False", "ssl" + r"\.CERT_NONE", "check_hostname" + r"\s*=\s*False", "NODE_TLS_REJECT" + "_UNAUTHORIZED", "reject" + r"Unauthorized\s*:\s*false", "insecure_skip" + "_verify"]))   # 이 파일 자체가 헤드 점검에 걸리지 않게 조각으로 만든다
ALLOW = {"scripts/e2e.sh": "백업 시험 대상(restic rest 서버)은 이 PR 범위 밖: 보고서의 남은 일"}
bad = []
for f in subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split():
    p = ROOT / f
    if f.startswith(("build/", "docs/", "test/")) or p.suffix not in {".py", ".env", ".yaml", ".yml", ".json", ".sh", ""} and p.name != "Caddyfile" or f == "scripts/test_no_plaintext_addresses.py" or not p.is_file():
        continue
    for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        if (PLAIN.search(line) and f not in ALLOW) or NOVERIFY.search(line):
            bad.append(f"{f}:{i}: {(PLAIN.search(line) or NOVERIFY.search(line)).group(0)}")
print("\n".join(bad) or "통과: 평문 주소·검증 끄기 없음")
sys.exit(1 if bad else 0)
