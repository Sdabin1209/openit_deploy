#!/usr/bin/env python3
"""정적 점검(ADR 0049): config/Caddyfile 이 {file./run/secrets/<이름>} 으로 읽는 비밀은 모두 compose.yaml 의 gateway 서비스 secrets 에 마운트되어 있고,
최상위 secrets 에 정의되어 있으며, scripts/gen-secrets.sh 가 만든다(또는 조직이 주는 파일). 하나라도 빠지면 게이트웨이가 설정을 읽다 실패하거나 기동하지 않는다.
왜 이 점검인가: 새 비밀을 Caddyfile 에만 쓰고 compose 에 마운트를 빼먹으면 실행해야만 알 수 있다(읽어서 알 수 있는 것은 정적으로 먼저 본다).
사용: <deploy .venv>/bin/python scripts/test_caddy_secret_mounts.py"""
import pathlib, re, sys
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
caddy = (ROOT / "config/Caddyfile").read_text(encoding="utf-8")
compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
gen = (ROOT / "scripts/gen-secrets.sh").read_text(encoding="utf-8")
# 주석 줄은 제외하고 실제 설정만 본다
used = {m for l in "\n".join(f.read_text(encoding="utf-8") for f in (ROOT / "config/gateway-tls").glob("*.caddy")).splitlines() if not l.lstrip().startswith("#") for m in re.findall(r"/run/secrets/([A-Za-z0-9._-]+)", l)} | {m for l in caddy.splitlines() if not l.lstrip().startswith("#") for m in re.findall(r"\{file\./run/secrets/([A-Za-z0-9._-]+)\}", l)}
mounted = set(compose["services"]["gateway"].get("secrets", []))
defined = set(compose.get("secrets", {}))
def roles_made(name):   # gen-secrets.sh 의 roles() 가 "<서비스>-<read|write>-<역할>" 파일을 만든다(GATE_R=$(roles gate read 역할...) 줄)
    m = re.fullmatch(r"gate-(read|write)-([a-z-]+)", name)
    return bool(m) and any(l.startswith("GATE_" + m[1][0].upper() + "=$(roles gate ") and m[2] in l.replace(")", " ").split() for l in gen.splitlines())
bad = []
for n in sorted(used):
    if n not in mounted: bad.append(f"{n}: Caddyfile 이 읽는데 gateway 서비스 secrets 에 없다")
    if n not in defined: bad.append(f"{n}: 최상위 secrets 에 정의가 없다")
    if n not in gen and not roles_made(n) and n != "gateway-tls-key": bad.append(f"{n}: scripts/gen-secrets.sh 가 만들지 않는다")
for n in sorted(mounted - used):
    bad.append(f"{n}: gateway 에 마운트했지만 Caddyfile 이 읽지 않는다(쓰지 않는 비밀은 마운트하지 않는다)")
if "gateway-inference-token" not in used: bad.append("gateway-inference-token: 추론 서버 기계 토큰 경로(@inferencemachine)가 Caddyfile 에 없다")
if bad:
    print("실패:\n  " + "\n  ".join(bad)); sys.exit(1)
print(f"통과: Caddyfile 의 비밀 {len(used)}개가 gateway 마운트·정의·생성과 일치")
