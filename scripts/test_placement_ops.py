#!/usr/bin/env python3
"""R10.12·R1.5 정적 점검: (1) 배치는 인벤토리 호스트 키로 상대를 확인한다(ansible.cfg host_key_checking = True, 끄는 설정 없음) (2) 배치는 한 번에 하나(site.yml 의 잠금 폴더 mkdir, 풀기)
(3) compose 밖 호출자에게 내보내는 파일에 SHA256SUMS 가 붙고 sha256sum -c 로 대조된다(placement.py export), hosts 는 '<주소> <서비스 이름>' 형식."""
import os, re, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); fails = []
cfg = open(os.path.join(ROOT, "ansible", "ansible.cfg"), encoding="utf-8").read()
if not re.search(r"^host_key_checking\s*=\s*True\s*$", cfg, re.M): fails.append("ansible.cfg: host_key_checking = True 가 없다")
if re.search(r"StrictHostKeyChecking\s*=?\s*no|UserKnownHostsFile\s*=?\s*/dev/null", cfg + open(os.path.join(ROOT, "ansible", "site.yml"), encoding="utf-8").read()): fails.append("호스트 키 확인을 끄는 설정이 있다")
site = open(os.path.join(ROOT, "ansible", "site.yml"), encoding="utf-8").read()
if "placement.lock" not in site or site.count("placement.lock") < 2: fails.append("site.yml: 배치 잠금(만들기·풀기)이 없다")
d = tempfile.mkdtemp(); root = os.path.join(d, "r.pem"); open(root, "w").write("-----BEGIN CERTIFICATE-----\n")
py = sys.executable
r = subprocess.run([py, os.path.join(ROOT, "scripts", "placement.py"), "export", os.path.join(ROOT, "ansible", "inventory.multi.example.yml"), "--out", os.path.join(d, "o"), "--root-ca", root], capture_output=True, text=True)
if r.returncode: fails.append("export 실패: " + r.stderr[-200:])
else:
    o = os.path.join(d, "o")
    if subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=o, capture_output=True).returncode: fails.append("SHA256SUMS 대조 실패")
    open(os.path.join(o, "hosts"), "a").write("x\n")
    if subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=o, capture_output=True).returncode == 0: fails.append("변조한 파일이 SHA256SUMS 대조를 통과했다")
    for line in open(os.path.join(o, "hosts")).read().split("\n")[:-2]:
        if not re.match(r"^\d+\.\d+\.\d+\.\d+ [a-z0-9-]+$", line): fails.append("hosts 형식: " + line)
for f in fails: print("FAIL: " + f, file=sys.stderr)
if fails: sys.exit(1)
print("OK: R10.12 호스트 키 확인·배치 잠금, R1.5 내보내기 SHA256SUMS 대조(변조 탐지)")
