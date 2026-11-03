#!/usr/bin/env bash
# Keycloak realm 가져오기 파일을 만든다(U82, head ADR 0014, deploy ADR 0057). 사용: gen-keycloak-realm.sh [출력 파일]   (기본 state/keycloak/openit-realm.json)
# 템플릿 config/keycloak/openit-realm.template.json 의 두 자리(허용 리다이렉트 URI 목록, 로그아웃 뒤 URI)를 GATEWAY_HOSTS 로 채운다.
#   리다이렉트: https://<호스트>[:포트]/oauth2/callback   로그아웃 뒤: https://<호스트>[:포트]/   (호스트마다 GATEWAY_HOSTS 에 적힌 포트와 밖에 보이는 포트 GATEWAY_PUBLIC_TLS_PORT 둘. 443 은 생략)
# 클라이언트 비밀과 초기 admin 비밀번호는 이 파일에 쓰지 않는다: 가져오기 파일의 ${OPENIT_GATEWAY_CLIENT_SECRET}, ${OPENIT_INITIAL_ADMIN_PASSWORD} 자리는 Keycloak 이 기동할 때 환경 변수로 채운다(엔트리포인트 래퍼가 비밀 파일에서 넘긴다, D84).
# 왜 기동 때마다 만드는가: 호스트 목록이 바뀌면 파일이 바뀐다. 단, Keycloak 은 이미 있는 realm 은 다시 가져오지 않으므로 운영 중에 호스트를 바꾸면 관리 화면에서 클라이언트의 URI 를 직접 고친다(docs/RUN.md).
set -euo pipefail
DEPLOY_NO_DOCKER=1; source "$(dirname "$0")/lib.sh"
OUT=${1:-$DEPLOY_ROOT/state/keycloak/openit-realm.json}; mkdir -p "$(dirname "$OUT")"
python3 -I - "$DEPLOY_ROOT/config/keycloak/openit-realm.template.json" "$OUT" "${GATEWAY_HOSTS:-localhost:8443, 127.0.0.1:8443}" "${GATEWAY_PUBLIC_TLS_PORT:-8443}" <<'PY'
import json, re, sys
tpl, out, hosts, pub = sys.argv[1:5]
origins = []
for h in re.split(r"\s*,\s*", hosts.strip()):
    if not re.fullmatch(r"[A-Za-z0-9.-]+(:[0-9]{2,5})?", h): sys.exit(f"GATEWAY_HOSTS 항목 형식 위반: {h!r}")
    name, _, port = h.partition(":")
    for p in (port, pub):
        o = f"https://{name}" + ("" if p in ("", "443") else f":{p}")
        if o not in origins: origins.append(o)
t = json.load(open(tpl, encoding="utf-8"))
c = t["clients"][0]
c["redirectUris"] = [o + "/oauth2/callback" for o in origins]
c["attributes"]["post.logout.redirect.uris"] = "##".join(o + "/" for o in origins)
s = json.dumps(t, ensure_ascii=False, indent=2) + "\n"
assert "__" not in s, "채우지 못한 자리표시가 남았다"
open(out, "w", encoding="utf-8").write(s)
PY
chmod 644 "$OUT"   # 비밀이 없다(자리표시만): Keycloak 컨테이너(uid 1000)가 읽는다
echo "$OUT"
