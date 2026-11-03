#!/usr/bin/env bash
# Keycloak realm 가져오기 파일을 만든다(U82, head ADR 0014, deploy ADR 0057). 사용: gen-keycloak-realm.sh [출력 파일]   (기본 $SECRETS_DIR/keycloak-realm.json)
# 템플릿 config/keycloak/openit-realm.template.json 의 두 자리(허용 리다이렉트 URI 목록, 로그아웃 뒤 URI)를 GATEWAY_HOSTS 로 채운다.
#   리다이렉트: https://<호스트>[:포트]/oauth2/callback   로그아웃 뒤: https://<호스트>[:포트]/   (호스트마다 GATEWAY_HOSTS 에 적힌 포트와 밖에 보이는 포트 GATEWAY_PUBLIC_TLS_PORT 둘. 443 은 생략)
# 클라이언트 비밀(tokens/oauth2-proxy-client-secret)과 초기 admin 임시 비밀번호(tokens/openit-initial-admin-password)가 값으로 들어가므로 출력은 **비밀 파일**이다(모드 640 + 그룹 SECRETS_GID, compose secrets 로 마운트).
# 왜 환경 변수가 아닌가: 래퍼가 파일을 읽어 환경 변수로 넘기면 Keycloak 프로세스의 /proc/1/environ 에 값이 남는다(3차 E2E check-secrets-hidden 이 잡았다, D84).
# 왜 기동 때마다 만드는가: 호스트 목록이 바뀌면 파일이 바뀐다. 단, Keycloak 은 이미 있는 realm 은 다시 가져오지 않으므로 운영 중에 호스트를 바꾸면 관리 화면에서 클라이언트의 URI 를 직접 고친다(docs/RUN.md).
set -euo pipefail
DEPLOY_NO_DOCKER=1; source "$(dirname "$0")/lib.sh"
D=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}; OUT=${1:-$D/keycloak-realm.json}; mkdir -p "$(dirname "$OUT")"
[ -s "$D/tokens/oauth2-proxy-client-secret" ] && [ -s "$D/tokens/openit-initial-admin-password" ] || die "Keycloak 비밀이 없다: $D/tokens (먼저 scripts/gen-secrets.sh)"
( umask 027; python3 -I - "$DEPLOY_ROOT/config/keycloak/openit-realm.template.json" "$OUT" "${GATEWAY_HOSTS:-localhost:8443, 127.0.0.1:8443}" "${GATEWAY_PUBLIC_TLS_PORT:-8443}" "$D/tokens/oauth2-proxy-client-secret" "$D/tokens/openit-initial-admin-password" <<'PY'
import json, re, sys
tpl, out, hosts, pub, f_secret, f_pw = sys.argv[1:7]
origins = []
for h in re.split(r"\s*,\s*", hosts.strip()):
    if not re.fullmatch(r"[A-Za-z0-9.-]+(:[0-9]{2,5})?", h): sys.exit(f"GATEWAY_HOSTS 항목 형식 위반: {h!r}")
    name, _, port = h.partition(":")
    for p in (port, pub):
        o = f"https://{name}" + ("" if p in ("", "443") else f":{p}")
        if o not in origins: origins.append(o)
t = json.load(open(tpl, encoding="utf-8"))
c = t["clients"][0]
c["secret"] = open(f_secret).read().strip()
t["users"][0]["credentials"][0]["value"] = open(f_pw).read().strip()
c["redirectUris"] = [o + "/oauth2/callback" for o in origins]
c["attributes"]["post.logout.redirect.uris"] = "##".join(o + "/" for o in origins)
s = json.dumps(t, ensure_ascii=False, indent=2) + "\n"
assert "__" not in s and "${" not in s, "채우지 못한 자리표시가 남았다"
open(out, "w", encoding="utf-8").write(s)
PY
)
secret_fix "$OUT" keycloak-realm.json   # 640 + 그룹 SECRETS_GID (컨테이너는 group_add 로 읽는다, ADR 0054)
echo "$OUT"
