"""wiring/진입: check_exposure.py --inspect <JSON> [--caddyfile config/Caddyfile] [--known config/exposure-known-diffs.json] [--hosts config/exposure-hosts.json] [--roles ...]
  --inspect: {"<서비스>": {"labels": {...}, "exposed_ports": ["8080/tcp"], "user": "10001"}}  (check-exposure.sh 가 docker inspect 로 만든다)
종료 코드: 0 일치, 1 어긋남, 2 사용 오류, 3 검증하지 못함(라벨 없음 등: 통과가 아니다). 파일 읽기·출력은 여기서, 대조는 컴포넌트 exposure_check 가 한다."""
import argparse
import json
import pathlib
import sys

from openit_deploy.components import exposure_check
from openit_deploy.wiring.call import call

ROOT = pathlib.Path(__file__).resolve().parents[2]


def main(argv) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--inspect", required=True); ap.add_argument("--caddyfile", default=str(ROOT / "config/Caddyfile"))
    ap.add_argument("--known", default=str(ROOT / "config/exposure-known-diffs.json")); ap.add_argument("--hosts", default=str(ROOT / "config/exposure-hosts.json"))
    ap.add_argument("--roles", default="staff operator release-approver reviewer author clinical-reviewer")
    a = ap.parse_args(argv)
    from boundary_contracts import validator
    kp = pathlib.Path(a.known)
    known = json.loads(kp.read_text()) if kp.is_file() else {}
    insp = {s: {"labels": o.get("labels"), "exposed_ports": o.get("exposed_ports", []), "user": o.get("user")} for s, o in json.loads(pathlib.Path(a.inspect).read_text()).items()}
    r = call(exposure_check, "ExposureCheckRequest", "ExposureCheckResult",
             {"caddyfile": pathlib.Path(a.caddyfile).read_text(encoding="utf-8"), "roles": a.roles.split(), "hosts": json.loads(pathlib.Path(a.hosts).read_text()),
              "known": sorted(known), "inspect": insp},
             exposure_errors=lambda label: [e.message for e in validator("Exposure").iter_errors(label)])
    for n in r["notes"]: print(n)
    for d in r["new_diffs"]: print("어긋남:", d)
    for k in r["stale_known"]: print("낡은 예외(이제 어긋나지 않는다, config/exposure-known-diffs.json 에서 지운다):", k)
    for u in r["unverified"]: print("검증 못 함:", u)
    if r["held_count"]: print(f"알려진 어긋남 {r['held_count']}건(이유는 config/exposure-known-diffs.json): 통과로 세지 않고 남겨 둔다")
    if r["status"] == "DIFF": return 1
    if r["status"] == "UNVERIFIED": return 3
    print(f"일치: 서비스 {r['services']}개의 노출 선언이 Caddyfile 과 같다 (알려진 어긋남 {r['held_count']}건 제외)")
    return 0
