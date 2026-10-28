#!/usr/bin/env bash
# 백업 공통(backup.sh, pg-backup.sh, backup-secrets.sh, restore*.sh, backup-check.sh, backup-restore-test.sh 가 source 한다). 설정 읽기·검증과 restic 호출.
# 왜 restic 인가: docs/adr/0038-restic-backup.md (옛 backup_tool.py·age/gpg 파일별 암호화를 대체). 설정 키는 config/backup.env.example 이 설명한다.
# source 하는 쪽이 lib.sh(die, DEPLOY_ROOT)를 먼저 source 해야 한다.

# 설정을 읽고 검증한다. 문제가 있으면 "CRIT: ..." 를 표준 오류로 내고 종료 코드 2(D88 U6: 경고가 아니라 실패).
# systemd 가 종료 코드와 마지막 줄을 journald 에 남기고 job-metrics.sh 가 실패를 지표로 내보내 JobFailed 경보가 된다.
backup_load_config() {
  CFG=${BACKUP_CONFIG:-$DEPLOY_ROOT/config/backup.env}
  [ -f "$CFG" ] || { echo "CRIT: 백업 설정 파일이 없다: $CFG (config/backup.env.example 을 복사해 채운다. 백업 없이 운영하지 않는다, D88 U6)" >&2; exit 2; }
  BACKUP_DIR=; BACKUP_RETENTION_DAYS=; BACKUP_PASSWORD_FILE=; BACKUP_ENCRYPT_RECIPIENTS=; BACKUP_ENCRYPT_TOOL=; BACKUP_ALLOW_PLAINTEXT=; BACKUP_SECRETS_DIR=; BACKUP_SECRETS_KEEP=
  set -a; source "$CFG"; set +a
  # 옛 키(age/gpg 공개키 암호화, ADR 0020)는 조용히 무시하지 않고 거부한다: 설정을 그대로 두면 암호화가 바뀐 줄 모르고 운영하게 된다
  if [ -n "$BACKUP_ENCRYPT_RECIPIENTS$BACKUP_ENCRYPT_TOOL$BACKUP_ALLOW_PLAINTEXT$BACKUP_SECRETS_DIR$BACKUP_SECRETS_KEEP" ]; then
    echo "CRIT: $CFG 에 옛 키(BACKUP_ENCRYPT_RECIPIENTS/BACKUP_ENCRYPT_TOOL/BACKUP_ALLOW_PLAINTEXT/BACKUP_SECRETS_DIR/BACKUP_SECRETS_KEEP)가 있다. 백업은 restic 으로 바뀌었다(ADR 0038): 이 키들을 지우고 BACKUP_PASSWORD_FILE 을 둔다" >&2; exit 2; fi
  [ -n "$BACKUP_DIR" ] || { echo "CRIT: BACKUP_DIR 이 비어 있다: 서버 밖(다른 디스크·원격 마운트) 경로를 적는다" >&2; exit 2; }
  [[ "$BACKUP_RETENTION_DAYS" =~ ^[0-9]+$ ]] || { echo "CRIT: BACKUP_RETENTION_DAYS 가 비었거나 정수가 아니다: '$BACKUP_RETENTION_DAYS' (예시 14, D88 U4)" >&2; exit 2; }
  [ -n "$BACKUP_PASSWORD_FILE" ] || { echo "CRIT: BACKUP_PASSWORD_FILE(restic 저장소 암호가 든 파일의 절대 경로)이 비어 있다. 덤프에는 개인정보가 든다: 암호화 없이 백업하지 않는다" >&2; exit 2; }
  case "$BACKUP_PASSWORD_FILE" in /*) ;; *) echo "CRIT: BACKUP_PASSWORD_FILE 은 절대 경로여야 한다: $BACKUP_PASSWORD_FILE" >&2; exit 2;; esac
  [ -r "$BACKUP_PASSWORD_FILE" ] && [ -s "$BACKUP_PASSWORD_FILE" ] || { echo "CRIT: 암호 파일을 읽을 수 없거나 비었다: $BACKUP_PASSWORD_FILE" >&2; exit 2; }
  case "$(stat -c %a "$BACKUP_PASSWORD_FILE")" in 400|600) ;; *) echo "CRIT: 암호 파일 모드가 400/600 이 아니다: $BACKUP_PASSWORD_FILE ($(stat -c %a "$BACKUP_PASSWORD_FILE")). chmod 600 으로 고친다" >&2; exit 2;; esac
  # 암호 파일이 백업 저장소 안에 있으면 저장소를 가진 사람이 암호도 가진다: 암호화가 의미가 없다
  case "$(readlink -f "$BACKUP_PASSWORD_FILE")" in "$(readlink -f "$BACKUP_DIR" 2>/dev/null || echo "$BACKUP_DIR")"/*) echo "CRIT: 암호 파일이 BACKUP_DIR 안에 있다. 저장소와 같은 곳에 두면 암호화가 의미가 없다: 다른 곳에 둔다" >&2; exit 2;; esac
  RESTIC_IMAGE=$(sed -n 's/^RESTIC_IMAGE=//p' "${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}")
  [ -n "$RESTIC_IMAGE" ] || { echo "CRIT: RESTIC_IMAGE 가 잠금 파일에 없다 (bash scripts/lock-third-party.sh)" >&2; exit 2; }
  [ "${BACKUP_CHECK_ONLY:-0}" = 1 ] || { umask 077; mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR" 2>/dev/null || true; }   # 점검 전용 호출은 아무것도 만들지 않는다
}

# restic 을 컨테이너로 부른다(호스트에 restic 이 없어도 된다, 이미지는 digest 고정): backup_restic [docker 인자...] -- <restic 인자...>
# 저장소는 $BACKUP_DIR/restic, 암호는 파일(RESTIC_PASSWORD_FILE, 값은 환경 변수·인자·로그에 나오지 않는다). 기본은 호스트 사용자로 실행하고, 볼륨을 읽거나 쓰는 호출은
# BACKUP_ROOT_ARGS 를 앞에 준다(root + 필요한 capability 만). 캐시는 컨테이너 tmpfs(저장소 크기를 늘리지 않는다).
BACKUP_ROOT_ARGS=(--user 0:0 --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER)
backup_restic() {
  local d=() u=(--user "$(id -u):$(id -g)")
  while [ $# -gt 0 ] && [ "$1" != -- ]; do d+=("$1"); [ "$1" = --user ] && u=(); shift; done
  shift
  "$DOCKER" run --rm "${u[@]+"${u[@]}"}" --security-opt no-new-privileges:true --tmpfs /tmp \
    -v "$BACKUP_DIR:/backup" -v "$BACKUP_PASSWORD_FILE:/run/secrets/restic-password:ro" \
    -e RESTIC_REPOSITORY=/backup/restic -e RESTIC_PASSWORD_FILE=/run/secrets/restic-password -e RESTIC_CACHE_DIR=/tmp/restic-cache \
    "${d[@]+"${d[@]}"}" "$RESTIC_IMAGE" "$@"
}
# root 로 쓴 저장소 파일의 소유자를 호스트 사용자로 되돌린다(이후 호스트 사용자 실행이 읽고 지울 수 있게)
backup_fixperm() {
  "$DOCKER" run --rm --user 0:0 --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER --security-opt no-new-privileges:true -v "$BACKUP_DIR:/backup" --entrypoint chown "$RESTIC_IMAGE" -R "$(id -u):$(id -g)" /backup/restic 2>/dev/null || die "저장소 파일 소유자를 되돌리지 못했다($BACKUP_DIR/restic): 호스트 사용자가 이후 읽지 못할 수 있다"
}
# 저장소가 없으면 만든다(있으면 건드리지 않는다: 암호가 틀린 기존 저장소를 새로 만들어 덮지 않는다)
backup_ensure_repo() {
  [ -f "$BACKUP_DIR/restic/config" ] && return 0
  backup_restic -- init --quiet >/dev/null || die "restic 저장소를 만들지 못했다: $BACKUP_DIR/restic"
}
# 보관 기간(BACKUP_RETENTION_DAYS)이 지난 스냅샷을 지운다. 저장소(host)마다 가장 최근 하나는 기간이 지나도 남긴다(옛 backup_prune 과 같은 규칙).
backup_forget() {
  local keep=(--keep-last 1); [ "$BACKUP_RETENTION_DAYS" -eq 0 ] || keep+=(--keep-within "${BACKUP_RETENTION_DAYS}d")
  backup_restic -- forget "${keep[@]}" --prune --quiet >/dev/null || die "보관 기간 정리(restic forget --prune)에 실패했다"
}
# 스냅샷 지정: latest 또는 restic 스냅샷 ID(16진수 8~64자)만 받는다
backup_snapshot_arg() { [[ "$1" =~ ^(latest|[0-9a-f]{8,64})$ ]] || die "스냅샷은 latest 또는 restic 스냅샷 ID(16진수)여야 한다: $1"; echo "$1"; }
