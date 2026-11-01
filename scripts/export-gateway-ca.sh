#!/usr/bin/env bash
# 게이트웨이(Caddy 내부 CA)의 루트 인증서를 꺼낸다. 다른 호스트의 추론 서버(compose.inference.yaml 의 INFERENCE_CA_FILE)와 키오스크·직원 PC 의 신뢰 저장소에 넣는 파일이다.
# 사용: export-gateway-ca.sh [--project <컴포즈 프로젝트>] [--retries N] <출력 파일>      (-h/--help)
#   --project  기본 $DEPLOY_PROJECT, 없으면 deploy. 컨테이너 이름 <프로젝트>-gateway-1
#   --retries  기본 15 (1초 간격). 왜: Caddy 는 첫 기동 직후 내부 CA 를 만들기 때문에 컨테이너가 떠 있어도 파일이 잠시 없을 수 있다.
# 출력 파일은 공개 인증서다(비밀키는 게이트웨이 볼륨에만 있고 이 스크립트는 읽지 않는다). 모드 644 로 쓴다. 공인 인증서(ACME)로 바꾼 뒤에는 필요 없다.
# 왜 docker cp: 루트 인증서는 Caddy 데이터 볼륨(/data/caddy/pki/authorities/local/root.crt)에만 있고 HTTP 로 내지 않는다(runbook 9절).
set -uo pipefail
usage() { sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; }
PROJECT=${DEPLOY_PROJECT:-deploy}; RETRIES=15; OUT=""
while [ $# -gt 0 ]; do case "$1" in
  -h|--help) usage; exit 0;;
  --project) [ $# -ge 2 ] || { echo "오류: --project 에는 값이 필요하다" >&2; exit 2; }; PROJECT=$2; shift 2;;
  --retries) [ $# -ge 2 ] || { echo "오류: --retries 에는 값이 필요하다" >&2; exit 2; }; RETRIES=$2; shift 2;;
  -*) usage >&2; echo "오류: 알 수 없는 인자: $1" >&2; exit 2;;
  *) [ -z "$OUT" ] || { echo "오류: 출력 파일은 하나만 준다" >&2; exit 2; }; OUT=$1; shift;; esac; done
[ -n "$OUT" ] || { usage >&2; echo "오류: 출력 파일 경로가 필요하다" >&2; exit 2; }
case "$RETRIES" in ''|*[!0-9]*) echo "오류: --retries 는 0 이상의 정수다: '$RETRIES'" >&2; exit 2;; esac
case "$PROJECT" in *[!A-Za-z0-9_.-]*|'') echo "오류: 프로젝트 이름 형식이 아니다: '$PROJECT'" >&2; exit 2;; esac
DEPLOY_NO_DOCKER=1; source "$(dirname "$0")/lib.sh"; detect_docker
C="$PROJECT-gateway-1"; SRC="$C:/data/caddy/pki/authorities/local/root.crt"
"$DOCKER" inspect "$C" >/dev/null 2>&1 || die "컨테이너 $C 가 없다. 프로젝트 이름을 확인하라(--project). 목록: $DOCKER ps --filter name=gateway"
[ -d "$(dirname "$OUT")" ] || die "출력 폴더가 없다: $(dirname "$OUT")"
TMP=$(mktemp "$OUT.XXXXXX") || die "출력 파일을 만들 수 없다: $OUT"
trap 'rm -f "$TMP"' EXIT
ok=0
for i in $(seq 0 "$RETRIES"); do
  if "$DOCKER" cp "$SRC" "$TMP" >/dev/null 2>&1 && grep -q '^-----BEGIN CERTIFICATE-----' "$TMP"; then ok=1; break; fi
  [ "$i" -lt "$RETRIES" ] && sleep 1
done
[ $ok = 1 ] || die "게이트웨이 CA 루트를 가져오지 못했다($C, 시도 $((RETRIES+1))회). 게이트웨이가 떠 있고 TLS 사이트가 'tls internal' 인지 확인하라(공인 인증서면 이 파일이 없다)"
chmod 644 "$TMP" && mv -f "$TMP" "$OUT" || die "출력 파일을 쓰지 못했다: $OUT"
trap - EXIT
echo "게이트웨이 CA 루트 인증서를 썼다: $OUT (공개 인증서)"
