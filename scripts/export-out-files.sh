#!/usr/bin/env bash
# compose 밖 호출자(다른 서버의 잡, 학습 서버의 파이프라인)에게 줄 OUT-FILE 을 쓴다(RUNTIME R1.5): 루트 인증서 PEM(root_ca.crt), `<주소> <서비스 이름>` 줄의 hosts 표(hosts), 두 파일의 SHA-256 목록(SHA256SUMS).
# 사용: export-out-files.sh --out <폴더> --root <PEM> [--root <PEM> ...] (--host "<주소> <서비스 이름>")... [--hosts-file <파일>]
#   --root 를 두 번 주면 옛 루트와 새 루트를 함께 담는다(병행 기간, R1.7). 주소·이름은 공개 정보다. 비밀은 읽지도 쓰지도 않는다.
# 왜 같은 폴더에 쓰고 rename: 호출자가 쓰는 도중의 부분 파일을 읽지 않게 한다(POSIX rename(2), RUNTIME R1.5). 순서는 파일 둘 먼저, SHA256SUMS 맨 나중이다: 호출자는 SHA256SUMS 로 대조하므로 새 SHA256SUMS 가 보이면 두 파일은 이미 완성본이다.
# 왜 SHA256SUMS 형식: coreutils `sha256sum -c` 가 읽는 표준 형식이라 받는 쪽이 다른 도구 없이 대조한다. 새 파일을 쓰지 못하면(검사 실패, 디스크 가득) 이전 완성본을 건드리지 않고 종료 코드 1.
set -euo pipefail
OUT=""; ROOTS=(); HOSTS=()
while [ $# -gt 0 ]; do case "$1" in
  --out) OUT=${2:?}; shift 2;; --root) ROOTS+=("${2:?}"); shift 2;; --host) HOSTS+=("${2:?}"); shift 2;;
  --hosts-file) while IFS= read -r l; do [ -n "$l" ] && HOSTS+=("$l"); done < "${2:?}"; shift 2;;
  -h|--help) sed -n '2,4p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  *) echo "오류: 알 수 없는 인자: $1" >&2; exit 2;; esac; done
[ -n "$OUT" ] && [ -d "$OUT" ] || { echo "오류: --out 폴더가 없다: $OUT" >&2; exit 2; }
[ ${#ROOTS[@]} -ge 1 ] || { echo "오류: --root 가 하나 이상 필요하다" >&2; exit 2; }
[ ${#HOSTS[@]} -ge 1 ] || { echo "오류: --host 가 하나 이상 필요하다" >&2; exit 2; }
T=$(mktemp -d "$OUT/.out-file.XXXXXX"); trap 'rm -rf "$T"' EXIT   # 같은 파일시스템(rename 이 원자적이려면 같은 폴더)
for r in "${ROOTS[@]}"; do grep -q '^-----BEGIN CERTIFICATE-----' "$r" || { echo "오류: PEM 인증서가 아니다: $r" >&2; exit 1; }; cat "$r" >> "$T/root_ca.crt"; done
for h in "${HOSTS[@]}"; do
  [[ "$h" =~ ^[0-9a-fA-F:.]+\ [a-z][a-z0-9-]*$ ]] || { echo "오류: hosts 줄 형식이 '<주소> <서비스 이름>' 이 아니다: $h" >&2; exit 1; }
  printf '%s\n' "$h" >> "$T/hosts"
done
(cd "$T" && sha256sum root_ca.crt hosts > SHA256SUMS)
chmod 644 "$T/root_ca.crt" "$T/hosts" "$T/SHA256SUMS"
mv -f "$T/root_ca.crt" "$OUT/root_ca.crt"; mv -f "$T/hosts" "$OUT/hosts"; mv -f "$T/SHA256SUMS" "$OUT/SHA256SUMS"
echo "$OUT"
