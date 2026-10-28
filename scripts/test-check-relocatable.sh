#!/usr/bin/env bash
# check-relocatable.sh 정적 검사 자기 점검(--static-only, 임시 워크스페이스): (1) 윈도 드라이브 경로는 잡는다 (2) YAML 문자열의 `j:\n` 같은 개행 이스케이프는 오탐하지 않는다
# (3) 워크스페이스 이름·/home 경로는 계속 잡는다. 시험 자료의 위험한 문자열은 printf 로 조립한다(이 파일 자신이 정적 검사에 걸리지 않게).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/r"; git -C "$T/r" init -q
BS='\'; rc=0; N=0
chk() { # chk <설명> <기대 종료코드> <파일 내용(printf 서식)> [서식 인자...]
  local d=$1 want=$2 fmt=$3; shift 3; N=$((N+1))
  printf "$fmt" "$@" > "$T/r/f.txt"; git -C "$T/r" add f.txt
  out=$(CHECK_RELOCATABLE_WORKSPACE="$T" bash "$HERE/check-relocatable.sh" --static-only 2>&1); r=$?
  if [ "$r" = "$want" ]; then echo "  ok   $d"; else echo "  FAIL $d (rc=$r, 기대 $want)"; echo "$out" | tail -5; rc=1; fi
}
chk "드라이브 경로 C:<역슬래시>Users 를 잡는다" 1 'path = C:%sUsers%sme\n' "$BS" "$BS"
chk "이스케이프된 드라이브 경로 D:<역슬래시 둘>Data 를 잡는다" 1 '"D:%s%sData"\n' "$BS" "$BS"
chk "숫자로 시작하는 폴더 E:<역슬래시>2024 를 잡는다" 1 'E:%s2024\n' "$BS"
chk "YAML 문자열의 j:<개행 이스케이프> 는 오탐하지 않는다" 0 "printf 'services:%sn  j:%sn    image: x%sn'\n" "$BS" "$BS" "$BS"
chk "x:<개행 이스케이프>와 소문자 단어가 이어져도 오탐하지 않는다" 0 "a:%sn  b:%snfoo%sn\n" "$BS" "$BS" "$BS"
chk "경로가 아닌 평범한 파일은 통과" 0 'hello\n'
chk "/home/<이름> 경로는 계속 잡는다" 1 '%s/%s/%s\n' '' home someone
chk "워크스페이스 이름(healthKiosk)은 계속 잡는다" 1 'cd ~/%s%s\n' sda bin
[ $rc = 0 ] && echo "통과: check-relocatable 정적 검사 자체 시험 ${N}건" || exit 1
