#!/usr/bin/env bash
# 시험용 공통(source 해서 쓴다). 시험이 커밋된 운영 잠금(locks/images.lock)의 완전성에 기대지 않게 한다.
# test_lock_copy <대상 파일>: 운영 잠금을 임시 사본으로 복사하고, compose 가 요구하는(${X_DIGEST:?...}) 변수 중 사본에 없는 것을 자리표시자로 채운다.
# 왜: 영역/서비스가 compose 에 추가되면(예: dataset-store, ADR 0032) 커밋된 잠금이 그 digest 를 받기 전까지 compose 해석이 실패한다. 잠금은 publish 가 쓰는 파일이라 시험이 고치지 않고 사본을 쓴다.
# 요구 변수 목록은 손으로 적지 않고 compose 파일들에서 `${이름:?` 꼴을 뽑는다. 자리표시자는 형식만 맞는 sha256 0 값이다: 이 시험들이 기동하지 않는 서비스의 자리를 채울 뿐 어떤 이미지도 가리키지 않는다.
test_lock_copy() {
  local dest=$1 src="$DEPLOY_ROOT/locks/images.lock" v f
  cp "$src" "$dest"
  for f in "$DEPLOY_ROOT/compose.yaml" ${COMPOSE_EXTRA:-}; do
    [ -f "$f" ] || continue
    for v in $(grep -o '\${[A-Z][A-Z0-9_]*:?' "$f" | sed 's/^\${//; s/:?$//' | sort -u); do
      case "$v" in *_DIGEST) grep -q "^$v=" "$dest" || echo "$v=sha256:0000000000000000000000000000000000000000000000000000000000000000" >> "$dest";;
                   *_REVISION) grep -q "^$v=" "$dest" || echo "$v=0000000" >> "$dest";; esac
    done
  done
}
