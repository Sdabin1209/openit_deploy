#!/usr/bin/env bash
# OUT-FILE(RUNTIME R1.5) 단독 시험: 내보낸 파일 셋이 SHA256SUMS 로 대조되고, 어긋나면 대조가 실패하며, 잘못된 입력은 이전 완성본을 건드리지 않는다. Docker 불필요. 변이 확인: 파일을 바꾸면 sha256sum -c 실패.
set -euo pipefail
D=$(cd "$(dirname "$0")/.." && pwd); T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
ok() { echo "OK: $*"; }; bad() { echo "FAIL: $*" >&2; exit 1; }
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$T/k1" -out "$T/old.pem" -subj /CN=old -days 2 2>/dev/null
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$T/k2" -out "$T/new.pem" -subj /CN=new -days 2 2>/dev/null
mkdir "$T/o"
bash "$D/scripts/export-out-files.sh" --out "$T/o" --root "$T/old.pem" --host "10.0.0.5 survey-service" --host "10.0.0.6 release-gate" >/dev/null || bad "내보내기 실패"
(cd "$T/o" && sha256sum -c SHA256SUMS >/dev/null) && ok "SHA256SUMS 대조 통과"
[ "$(cat "$T/o/hosts")" = "$(printf '10.0.0.5 survey-service\n10.0.0.6 release-gate')" ] && ok "hosts 표는 '<주소> <서비스 이름>' 줄"
[ "$(ls -A "$T/o" | sort | tr '\n' ' ')" = "SHA256SUMS hosts root_ca.crt " ] && ok "폴더에 완성본 셋만 있다(임시 파일 없음)"
bash "$D/scripts/export-out-files.sh" --out "$T/o" --root "$T/old.pem" --root "$T/new.pem" --host "10.0.0.5 survey-service" >/dev/null
[ "$(grep -c BEGIN "$T/o/root_ca.crt")" = 2 ] && ok "병행 기간: 옛 루트와 새 루트를 함께 담는다(R1.7)"
(cd "$T/o" && sha256sum -c SHA256SUMS >/dev/null) || bad "병행본 대조 실패"
cp -r "$T/o" "$T/before"
bash "$D/scripts/export-out-files.sh" --out "$T/o" --root "$T/new.pem" --host "not a host line" >/dev/null 2>&1 && bad "잘못된 hosts 줄을 받았다"
diff -r "$T/o" "$T/before" >/dev/null && ok "잘못된 입력은 이전 완성본을 바꾸지 않는다(종료 코드 1)"
echo tamper >> "$T/o/hosts"; (cd "$T/o" && sha256sum -c SHA256SUMS >/dev/null 2>&1) && bad "변이: 바뀐 파일을 대조가 못 잡았다"; ok "변이 확인: 파일이 바뀌면 대조가 실패한다"
echo "PASS: OUT-FILE 시험"
