#!/usr/bin/env bash
# 인증 없는(쿠키·토큰 없음) 요청에 게이트웨이가 주는 응답이 기대표와 같은지 본다. 사용: check-unauth-expectations.sh <https://호스트:포트> [--cacert 파일] [--insecure]
# 기대표는 test/gateway-oidc/unauth-expectations.txt 한 곳이다: E2E(scripts/e2e.sh, 진짜 게이트웨이)와 자체 시험(scripts/test-gateway-auth.sh, 가짜 oauth2-proxy)이 이 스크립트를 같이 써서 기대값이 어긋나지 않는다(U82, 3차 E2E 에서 basic_auth 시절 기대값이 남아 FAIL).
# 종료 코드 0 같다, 1 어긋남(어긋난 줄을 출력). Docker 가 필요 없다(curl 만).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; BASE=${1:?사용: check-unauth-expectations.sh <https://호스트:포트> [--cacert 파일] [--insecure]}; shift
TLS=("$@"); [ ${#TLS[@]} -gt 0 ] || TLS=(--insecure)
H=$(mktemp); trap 'rm -f "$H"' EXIT; bad=0; n=0
while read -r m p want loc; do case "$m" in ""|\#*) continue;; esac
  n=$((n+1)); extra=(); [ "$m" = GET ] || extra=(-d '{}')
  acc=(); [ -z "$loc" ] || acc=(-H 'Accept: text/html')   # 화면 이동(302)은 Accept 에 text/html 이 있는 브라우저 요청에만 한다(RUNTIME R3.23)
  code=$(curl -s -m 10 -o /dev/null -D "$H" -w '%{http_code}' -X "$m" "${extra[@]}" "${acc[@]}" "${TLS[@]}" "$BASE$p")
  l=$(grep -i '^location:' "$H" | tr -d '\r' | head -1 | sed 's/^[Ll]ocation: *//')
  [ "$code" = "$want" ] || { echo "어긋남: $m $p -> $code (기대 $want)"; bad=$((bad+1)); }
  [ -z "$loc" ] || case "$l" in "$loc"*) ;; *) echo "어긋남: $m $p -> Location '$l' (기대 $loc…)"; bad=$((bad+1));; esac
  if [ -n "$loc" ]; then   # 같은 경로를 html 이 아닌 요청으로 부르면 302 가 아니라 401 + WWW-Authenticate(R3.23)
    c2=$(curl -s -m 10 -o /dev/null -D "$H" -w '%{http_code}' -X "$m" "${extra[@]}" "${TLS[@]}" "$BASE$p"); w2=$(grep -ci '^www-authenticate: *Bearer realm="openit"' "$H")
    [ "$c2" = 401 ] && [ "$w2" -ge 1 ] || { echo "어긋남: $m $p (Accept 없음) -> $c2, WWW-Authenticate ${w2}개 (기대 401 + Bearer realm=\"openit\")"; bad=$((bad+1)); }
  fi
done < "$HERE/../test/gateway-oidc/unauth-expectations.txt"
[ $n -gt 0 ] || { echo "기대표가 비었다"; exit 1; }
[ $bad = 0 ] && { echo "일치: 인증 없는 요청 ${n}건의 응답이 기대표와 같다"; exit 0; } || exit 1
