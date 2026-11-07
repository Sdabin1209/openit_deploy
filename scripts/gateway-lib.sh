#!/usr/bin/env bash
# 기기 인증(mTLS, 계약 PUBLIC_API F절, D136) 도구(gen-secrets.sh, kiosk-add-device.sh 가 source 한다). 키·비밀 값은 출력하지 않는다.
#  gw_allowlist_file         : 기기 허용 목록 파일 경로. 폴더 DEVICE_ALLOWLIST_DIR(기본 state/device-allowlist)에 이 파일 하나만 둔다: 공개 입구에 이 폴더를 읽기 전용으로 마운트한다(비밀이 없다)
#  gw_allowlist <인자...>    : scripts/device_allowlist.py(잠금 + 계약 검증 + 같은 폴더 rename)
#  gw_device_ca_init <비밀 폴더>      : 시험·데모용 일회용 기기 CA 를 만든다(키 device-ca.key 600 은 이 폴더에만 두고 어디에도 마운트하지 않는다, 공개 인증서 device-ca.pem 644 만 입구로 간다)
#  gw_issue_device_cert <비밀 폴더> <기기 ID> : 기기 인증서(device-certs/<ID>.crt, 키 .key 600)를 openssl 로 발급한다(주체 CN = 기기 ID, clientAuth). 표준 출력은 일련번호(소문자 16진수)
# 운영의 인증서 발급은 조직 PKI/MDM 몫이다(D113): 운영은 발급된 인증서의 일련번호를 kiosk-add-device.sh register 로 목록에 넣는다. 이 파일의 발급은 시험·데모 전용이다.
gw_allowlist_file() { printf '%s\n' "${DEVICE_ALLOWLIST_DIR:-$DEPLOY_ROOT/state/device-allowlist}/allowlist.json"; }
gw_allowlist() { "$DEPLOY_PY" -W ignore -I "$DEPLOY_ROOT/scripts/device_allowlist.py" "$(gw_allowlist_file)" "$@"; }
# 왜 -I: 현재 폴더의 모듈(json.py 등)을 읽지 않는다. boundary_contracts 는 .venv 에서 온다(-I 는 site-packages 를 막지 않는다)
gw_device_ca_init() {
  local D=$1
  [ -s "$D/device-ca.pem" ] && return 0
  ( umask 077; openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout "$D/device-ca.key" -out "$D/device-ca.pem" -subj "/CN=openit-test-device-ca" -days 30 \
      -addext "basicConstraints=critical,CA:TRUE,pathlen:0" -addext "keyUsage=critical,keyCertSign,cRLSign" >/dev/null 2>&1 ) || return 1
  chmod 600 "$D/device-ca.key"; chmod 644 "$D/device-ca.pem"
}
gw_issue_device_cert() {
  local D=$1 id=$2 t serial
  [ -s "$D/device-ca.key" ] && [ -s "$D/device-ca.pem" ] || { echo "오류: 개발용 기기 CA 가 없다($D/device-ca.key). 운영은 조직 PKI 가 발급한 인증서의 일련번호를 kiosk-add-device.sh register 로 등록한다" >&2; return 1; }
  mkdir -p "$D/device-certs"; chmod 700 "$D/device-certs"
  t=$(mktemp -d "$D/device-certs/.issue-XXXXXX")
  # 일련번호: 127비트 난수(최상위 비트는 1로 고정해 앞자리 0 이 없고 양수). RFC 5280 4.1.2.2: 양의 정수, 20옥텟 이하, CA 가 발급 인증서마다 유일하게
  serial=$(python3 -c 'import secrets;print(format((1<<126)|secrets.randbits(126),"x"))')
  printf 'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\n' > "$t/ext"
  ( umask 077; openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout "$t/k" -out "$t/csr" -subj "/CN=$id" >/dev/null 2>&1 \
    && openssl x509 -req -in "$t/csr" -CA "$D/device-ca.pem" -CAkey "$D/device-ca.key" -set_serial "0x$serial" -days 30 -extfile "$t/ext" -out "$t/c" >/dev/null 2>&1 ) \
    || { rm -rf "$t"; echo "오류: 기기 인증서 발급 실패: $id" >&2; return 1; }
  chmod 600 "$t/k"; chmod 644 "$t/c"
  mv -f "$t/k" "$D/device-certs/$id.key"; mv -f "$t/c" "$D/device-certs/$id.crt"; rm -rf "$t"
  openssl x509 -in "$D/device-certs/$id.crt" -noout -serial | sed 's/^serial=//' | tr 'A-F' 'a-f' | sed 's/^0*//'
}
