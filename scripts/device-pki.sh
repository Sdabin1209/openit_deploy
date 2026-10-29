#!/usr/bin/env bash
# !! 시험·데모 전용 !! 키오스크 기기 인증서용 일회용 CA 와 기기 인증서를 만든다(openssl). 운영에는 쓰지 않는다: 운영의 인증서 발급·갱신·폐기는 조직 PKI/MDM 몫이다(D113, ADR 0040).
# 사용: device-pki.sh init                  state/device-pki/ca.key(600), ca.crt 를 만든다(이미 있으면 거부)
#       device-pki.sh issue <기기 ID>       state/device-pki/<ID>.key(600), <ID>.crt 를 만든다. 기기 ID 는 주체 CN 이 되고 ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$ 이어야 한다(계약 PUBLIC_API F절)
#       device-pki.sh gateway-config        게이트웨이가 쓸 파일 두 개(state/device-pki/device-tls.caddy, device-ca.pem)를 만들고 DEVICE_TLS_CONF·DEVICE_CA_FILE 로 가리키는 법을 안내한다
# 환경: DEVICE_PKI_DIR(기본 state/device-pki). 키 파일은 권한 600이고 폴더는 700이다. state/ 는 .gitignore 라 리포에 들어가지 않는다. 키 값은 출력하지 않는다.
set -euo pipefail
DEPLOY_NO_DOCKER=1; source "$(dirname "$0")/lib.sh"
D=${DEVICE_PKI_DIR:-$DEPLOY_ROOT/state/device-pki}
command -v openssl >/dev/null || die "openssl 이 필요하다"
banner() { echo "!! 시험·데모 전용 일회용 CA 입니다. 운영 키오스크 인증서는 조직 PKI/MDM 이 발급합니다(ADR 0040). 운영 서버에 이 CA 를 신뢰시키지 마십시오. !!" >&2; }
case "${1:-}" in
  init)
    banner; [ ! -e "$D/ca.key" ] || die "이미 있다: $D/ca.key (지우고 다시 만들려면 폴더를 먼저 치운다)"
    ( umask 077; mkdir -p "$D"; chmod 700 "$D"
      openssl req -x509 -newkey rsa:2048 -nodes -keyout "$D/ca.key" -out "$D/ca.crt" -days 30 -subj "/O=openit TEST ONLY/CN=openit-test-device-ca" -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null )
    chmod 600 "$D/ca.key"; echo "일회용 CA 를 만들었다(유효 30일): $D/ca.crt";;
  issue)
    ID=${2:?기기 ID}; [[ "$ID" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$ ]] || die "기기 ID 형식 위반: $ID"
    [ -f "$D/ca.key" ] || die "먼저 init: $0 init"; banner
    ( umask 077
      openssl req -newkey rsa:2048 -nodes -keyout "$D/$ID.key" -out "$D/$ID.csr" -subj "/O=openit TEST ONLY/CN=$ID" 2>/dev/null
      printf 'basicConstraints=CA:FALSE\nkeyUsage=digitalSignature\nextendedKeyUsage=clientAuth\n' > "$D/$ID.ext"
      openssl x509 -req -in "$D/$ID.csr" -CA "$D/ca.crt" -CAkey "$D/ca.key" -CAcreateserial -out "$D/$ID.crt" -days 7 -extfile "$D/$ID.ext" 2>/dev/null
      rm -f "$D/$ID.csr" "$D/$ID.ext" )
    chmod 600 "$D/$ID.key"; echo "기기 인증서를 만들었다(유효 7일, CN=$ID): $D/$ID.crt, 키 $D/$ID.key";;
  gateway-config)
    [ -f "$D/ca.crt" ] || die "먼저 init"; banner
    cp "$D/ca.crt" "$D/device-ca.pem"; cp "$DEPLOY_ROOT/config/device-tls.mtls.caddy.example" "$D/device-tls.caddy"; chmod 644 "$D/device-ca.pem" "$D/device-tls.caddy"
    echo "게이트웨이에 켜려면: export DEVICE_TLS_CONF=$D/device-tls.caddy DEVICE_CA_FILE=$D/device-ca.pem  (그 뒤 gateway 를 다시 만든다: up.sh)";;
  *) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 2;;
esac
