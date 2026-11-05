#!/usr/bin/env bash
# 게이트웨이(Caddy 내부 CA)의 루트 인증서를 꺼낸다. 다른 호스트의 추론 서버(compose.inference.yaml 의 INFERENCE_CA_FILE)와 키오스크·직원 PC 의 신뢰 저장소에 넣는 파일이다.
# 사용: export-gateway-ca.sh [--project <컴포즈 프로젝트>] [--retries N] <출력 파일>      (-h/--help)
#   --project  기본 $DEPLOY_PROJECT, 없으면 deploy. 컨테이너 이름 <프로젝트>-gateway-1
#   --retries  기본 15 (대기 상한 초, 1초 간격으로 확인). 왜: Caddy 는 첫 기동 직후 내부 CA 를 만들기 때문에 컨테이너가 떠 있어도 파일이 잠시 없을 수 있다.
# 출력 파일은 공개 인증서다(비밀키는 게이트웨이 볼륨에만 있고 이 스크립트는 읽지 않는다). 모드 644 로 쓴다. 공인 인증서(ACME)로 바꾼 뒤에는 필요 없다.
# 왜 출력 마운트를 읽나: 루트가 어느 경로에 있는지는 platform 이미지의 내부 구조라 deploy 가 알지 않는다(구조 규칙 1·6). 공개 입구는 계약 PublicIngressEnv.INGRESS_ROOT_EXPORT_DIR(3.4.16)에 root_ca.crt 를 쓰고, deploy 는 그 폴더에 연결한 자기 볼륨(<프로젝트>_gateway-root)을 읽을 뿐이다. 이미지 부명령(export-root)은 부르지 않는다.
set -uo pipefail
usage() { sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; }
OUT=""; PROJECT=${DEPLOY_PROJECT:-deploy}; RETRIES=15   # 초. 측정하지 않았다(D125의 측정 최악 값 없음): Caddy 는 첫 기동 때 내부 CA 를 만들며 e2e.sh 는 up --wait 직후 부른다. 판단 근거: 초 단위 작업이라 기존 15초 유지. 넘으면 이유와 함께 실패한다; OUT=""
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
C="$PROJECT-gateway-1"
"$DOCKER" inspect "$C" >/dev/null 2>&1 || die "컨테이너 $C 가 없다. 프로젝트 이름을 확인하라(--project). 목록: $DOCKER ps --filter name=gateway"
[ -d "$(dirname "$OUT")" ] || die "출력 폴더가 없다: $(dirname "$OUT")"
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$DEPLOY_ROOT/locks/images.lock"); [ -n "$UTIL" ] || die "UTIL_IMAGE 가 잠금에 없다"
VOL="${PROJECT}_gateway-root"; "$DOCKER" volume inspect "$VOL" >/dev/null 2>&1 || die "출력 마운트 볼륨 $VOL 이 없다(공개 입구 서비스가 이 볼륨을 INGRESS_ROOT_EXPORT_DIR 에 연결해 떠 있어야 한다)"
TMP=$(mktemp "$OUT.XXXXXX") || die "출력 파일을 만들 수 없다: $OUT"
trap 'rm -f "$TMP"' EXIT
# 준비 확인은 파일이 실제로 있고 인증서 형식인지다(컨테이너가 떠 있어도 공개 입구가 내부 CA 를 만들기 전에는 파일이 없다)
fetch_ca() { "$DOCKER" run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --user 65534:65534 -v "$VOL:/o:ro" "$UTIL" cat /o/root_ca.crt > "$TMP" 2>/dev/null && grep -q '^-----BEGIN CERTIFICATE-----' "$TMP"; }
wait_ready "게이트웨이 CA 루트 $C" "$RETRIES" fetch_ca || die "게이트웨이 CA 루트를 가져오지 못했다($C, ${RETRIES}초). 게이트웨이가 떠 있고 TLS 사이트가 'tls internal' 인지 확인하라(공인 인증서면 이 파일이 없다)"
chmod 644 "$TMP" && mv -f "$TMP" "$OUT" || die "출력 파일을 쓰지 못했다: $OUT"
trap - EXIT
echo "게이트웨이 CA 루트 인증서를 썼다: $OUT (공개 인증서)"
