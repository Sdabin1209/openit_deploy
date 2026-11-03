#!/usr/bin/env python3
"""E2E 단계 9(복구 뒤): Keycloak 데이터(직원 계정·역할)가 백업에서 되살아났는지 실제 입구로 본다. keycloak 은 PG_DBS(백업·복구 대상)에 들어 있고,
지문은 DB 내용이 같음을 보일 뿐이다. 이 도구는 OIDC 로그인(E2E 단계 5u·test-idp-smoke.sh 와 같은 도우미 e2e_sandbox.oidc_login)으로 시험 사용자 trainer-e2e 가 로그인되고,
oauth2-proxy 의 /oauth2/userinfo 가 보여 주는 그룹에 역할(release-approver)이 그대로 있음을 단언한다. 환경: GATEWAY_PUBLIC_URL(lib.sh 를 source 한 셸). 비밀 값은 출력하지 않는다.
사용: e2e_verify_keycloak.py --secrets D --project P --docker docker --root R --gw-ca FILE [--account trainer-e2e --role release-approver]"""
import argparse, json, pathlib, ssl, sys, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e2e_sandbox as SB  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--secrets", required=True); ap.add_argument("--project", required=True); ap.add_argument("--docker", default="docker")
ap.add_argument("--root", default=str(HERE.parent)); ap.add_argument("--gw-ca", required=True)
ap.add_argument("--account", default="trainer-e2e"); ap.add_argument("--role", default="release-approver")
a = ap.parse_args()
SB.init(project=a.project, secrets=pathlib.Path(a.secrets), gw_ca=a.gw_ca, docker=a.docker, root=a.root)
base = SB.gw_url(refresh=True, human=True)
jar = SB.oidc_login(base, a.account, SB._test_password(a.account), ca=a.gw_ca)
cookie = "; ".join(f"{k}={v}" for k, v in jar.items() if k.startswith("_openit_session"))
assert cookie, f"{a.account}: 로그인했지만 세션 쿠키가 없다"
req = urllib.request.Request(base + "/oauth2/userinfo", headers={"Cookie": cookie})
with urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context(cafile=a.gw_ca)) as r:
    body = json.loads(r.read().decode())
groups = body.get("groups") or []
assert a.role in groups, f"{a.account} 의 역할(그룹)에 {a.role} 가 없다: {groups}"
print(f"복구 뒤 Keycloak: {a.account} 로그인 성공, 역할 {a.role} 유지(그룹 {len(groups)}개)")
