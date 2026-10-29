#!/usr/bin/env bash
# 백업 저장소 쪽 보관 정리(저장소 관리 자격으로 한다, ADR 0038/D112). **서버가 아니라 저장소를 가진 호스트에서** 돌린다: 서버의 자격은 append-only 라 지울 수 없다.
# 사용: backup-prune.sh <저장소 폴더 또는 도커 볼륨 이름> <저장소 이름> <암호 파일> <보관 일수> [--check]
#   저장소 폴더 = rest-server 의 --path (그 안 <저장소 이름>/ 이 restic 저장소). 도커 볼륨 이름이면 볼륨을 붙여 쓴다.
#   host(저장소 이름이 아니라 스냅샷 host: 파일 저장소마다, pg-<db>, secrets)마다 가장 최근 하나는 기간이 지나도 남긴다: restic forget --keep-within <N>d --keep-last 1 --prune
#   --check : 정리 뒤 restic check --read-data-subset=5% 도 한다
# 이 스크립트가 쓰는 관리 자격 = 이 호스트의 저장소 파일 접근 권한 + 저장소 암호. 서버(백업을 쓰는 쪽)에는 이 둘 중 앞의 것이 없다.
set -euo pipefail
DEPLOY_NO_DOCKER=0; source "$(dirname "$0")/lib.sh"
SRC=${1:?저장소 폴더 또는 볼륨}; NAME=${2:?저장소 이름}; PW=${3:?암호 파일}; DAYS=${4:?보관 일수}; CHECK=0; [ "${5:-}" = --check ] && CHECK=1
[[ "$DAYS" =~ ^[0-9]+$ ]] || die "보관 일수는 정수: $DAYS"; [[ "$NAME" =~ ^[A-Za-z0-9._-]+$ ]] || die "저장소 이름 형식 오류: $NAME"
[ -r "$PW" ] || die "암호 파일을 읽을 수 없다: $PW"
IMG=$(sed -n 's/^RESTIC_IMAGE=//p' "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}"); [ -n "$IMG" ] || die "RESTIC_IMAGE 가 잠금 파일에 없다"
case "$SRC" in /*) MNT="$SRC";; *) "$DOCKER" volume inspect "$SRC" >/dev/null 2>&1 || die "폴더(절대 경로)도 도커 볼륨도 아니다: $SRC"; MNT="$SRC";; esac
keep=(--keep-last 1); [ "$DAYS" -eq 0 ] || keep+=(--keep-within "${DAYS}d")
# rest-server 가 저장소 파일을 쓴 사용자(보통 컨테이너 안 restic 사용자)와 같은 권한이 필요하다: root 로 실행하고 필요한 capability 만 준다
run() { "$DOCKER" run --rm --user 0:0 --cap-drop ALL --cap-add DAC_OVERRIDE --cap-add FOWNER --cap-add CHOWN --security-opt no-new-privileges:true --tmpfs /tmp \
  -v "$MNT:/data" -v "$PW:/run/secrets/restic-password:ro" -e RESTIC_REPOSITORY="/data/$NAME" -e RESTIC_PASSWORD_FILE=/run/secrets/restic-password -e RESTIC_CACHE_DIR=/tmp/restic-cache "$IMG" "$@"; }
run forget "${keep[@]}" --prune --quiet
[ $CHECK = 0 ] || run check --read-data-subset=5%
echo "보관 정리 완료: $SRC/$NAME (보관 ${DAYS}일, host마다 최신 1개 유지)"
