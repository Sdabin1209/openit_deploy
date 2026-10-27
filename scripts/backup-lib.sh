#!/usr/bin/env bash
# 백업 공통(backup.sh, pg-backup.sh, backup-check.sh, backup-restore-test.sh 가 source 한다). 설정 읽기·검증과 암호화.
# 왜 이 구조인가: docs/adr/0020-backup-tool-and-encryption.md. 설정 키는 config/backup.env.example 이 설명한다.
# source 하는 쪽이 lib.sh(die, DEPLOY_ROOT)를 먼저 source 해야 한다.

# 설정을 읽고 검증한다. 문제가 있으면 "CRIT: ..." 를 표준 오류로 내고 종료 코드 2(D88 U6: 경고가 아니라 실패).
# 스케줄러는 종료 코드와 마지막 줄을 상태 파일에 남기고 check-health 가 이것을 CRIT 로 읽는다.
backup_load_config() {
  CFG=${BACKUP_CONFIG:-$DEPLOY_ROOT/config/backup.env}
  [ -f "$CFG" ] || { echo "CRIT: 백업 설정 파일이 없다: $CFG (config/backup.env.example 을 복사해 채운다. 백업 없이 운영하지 않는다, D88 U6)" >&2; exit 2; }
  BACKUP_DIR=; BACKUP_RETENTION_DAYS=; BACKUP_ENCRYPT_RECIPIENTS=; BACKUP_ENCRYPT_TOOL=auto; BACKUP_ALLOW_PLAINTEXT=0
  set -a; source "$CFG"; set +a
  [ -n "$BACKUP_DIR" ] || { echo "CRIT: BACKUP_DIR 이 비어 있다: 서버 밖(다른 디스크·원격 마운트) 경로를 적는다" >&2; exit 2; }
  [[ "$BACKUP_RETENTION_DAYS" =~ ^[0-9]+$ ]] || { echo "CRIT: BACKUP_RETENTION_DAYS 가 비었거나 정수가 아니다: '$BACKUP_RETENTION_DAYS' (예시 14, D88 U4)" >&2; exit 2; }
  case "$BACKUP_ENCRYPT_TOOL" in auto|age|gpg) ;; *) echo "CRIT: BACKUP_ENCRYPT_TOOL 은 auto|age|gpg: '$BACKUP_ENCRYPT_TOOL'" >&2; exit 2;; esac
  if [ "$BACKUP_ALLOW_PLAINTEXT" = 1 ]; then
    BACKUP_CRYPT=none
  else
    [ -n "$BACKUP_ENCRYPT_RECIPIENTS" ] || { echo "CRIT: BACKUP_ENCRYPT_RECIPIENTS(수신자 공개키 파일 경로)가 비어 있다. 덤프에는 개인정보가 든다: 암호화 없이 백업하지 않는다(시험 전용: BACKUP_ALLOW_PLAINTEXT=1)" >&2; exit 2; }
    [ -r "$BACKUP_ENCRYPT_RECIPIENTS" ] || { echo "CRIT: 수신자 공개키 파일을 읽을 수 없다: $BACKUP_ENCRYPT_RECIPIENTS" >&2; exit 2; }
    if grep -qE 'PRIVATE KEY|AGE-SECRET-KEY' "$BACKUP_ENCRYPT_RECIPIENTS"; then
      echo "CRIT: $BACKUP_ENCRYPT_RECIPIENTS 에 개인키가 들어 있다. 서버에는 공개키만 둔다(복호 키는 서버 밖, 사람이 보관)" >&2; exit 2; fi
    case "$BACKUP_ENCRYPT_TOOL" in
      auto) if command -v age >/dev/null 2>&1; then BACKUP_CRYPT=age; elif command -v gpg >/dev/null 2>&1; then BACKUP_CRYPT=gpg
            else echo "CRIT: 암호화 도구(age 또는 gpg)가 없다. 설치: docs/SETUP.md 백업 절" >&2; exit 2; fi;;
      *) command -v "$BACKUP_ENCRYPT_TOOL" >/dev/null 2>&1 || { echo "CRIT: $BACKUP_ENCRYPT_TOOL 이 설치되어 있지 않다" >&2; exit 2; }; BACKUP_CRYPT=$BACKUP_ENCRYPT_TOOL;;
    esac
  fi
  [ "${BACKUP_CHECK_ONLY:-0}" = 1 ] || { umask 077; mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR" 2>/dev/null || true; }   # 점검 전용 호출은 아무것도 만들지 않는다
}

# 파일 하나를 수신자 공개키로 암호화한다: backup_encrypt <입력> <출력 접두어> -> 출력 파일 이름(.age 또는 .gpg)을 표준 출력으로. 입력은 지운다.
# 왜 파일마다: 스트림 하나로 묶으면 복원 시험·부분 복원에서 한 파일만 풀 수 없다.
backup_encrypt() {
  local in=$1 out=$2
  case "$BACKUP_CRYPT" in
    none) echo "$in"; return 0;;
    age) age -R "$BACKUP_ENCRYPT_RECIPIENTS" -o "$out.age" "$in" || return 1; rm -f "$in"; echo "$out.age";;
    gpg) # 임시 홈에 공개키만 가져와 쓴다(서버의 키링을 건드리지 않는다). 신뢰 확인은 공개키 파일을 사람이 배치했다는 사실로 갈음한다(--trust-model always)
         local h; h=$(mktemp -d); chmod 700 "$h"
         gpg --batch --quiet --homedir "$h" --import "$BACKUP_ENCRYPT_RECIPIENTS" 2>/dev/null || { rm -rf "$h"; return 1; }
         local fprs=() f; while read -r f; do fprs+=(-r "$f"); done < <(gpg --batch --homedir "$h" --with-colons --list-keys 2>/dev/null | awk -F: '$1=="fpr"{print $10}')
         [ ${#fprs[@]} -gt 0 ] || { rm -rf "$h"; return 1; }
         gpg --batch --quiet --yes --homedir "$h" --trust-model always "${fprs[@]}" -o "$out.gpg" --encrypt "$in" || { rm -rf "$h"; return 1; }
         rm -rf "$h"; rm -f "$in"; echo "$out.gpg";;
  esac
}

# 보관 기간이 지난 스냅샷 폴더를 지운다(방금 만든 것과 가장 최근 하나는 남긴다): backup_prune <저장소 폴더>
backup_prune() {
  local dir=$1 old total d
  [ "$BACKUP_RETENTION_DAYS" -ge 0 ] || return 0
  # 이 도구가 만든 임시 파일(.tar-*, .partial-*)이 접두사 때문에 영영 안 지워지는 일이 없게, 1시간이 지난 것은 지운다(실행 중인 백업은 건드리지 않는다; 점검 M1)
  find "$dir" -mindepth 1 -maxdepth 1 \( -name '.tar-*' -o -name '.partial-*' \) -mmin +60 -exec rm -rf {} + 2>/dev/null || true
  mapfile -t old < <(find "$dir" -mindepth 1 -maxdepth 1 -type d -name '2*' -mtime +"$BACKUP_RETENTION_DAYS" | sort)
  total=$(find "$dir" -mindepth 1 -maxdepth 1 -type d -name '2*' | wc -l)
  for d in "${old[@]}"; do [ "$total" -gt 1 ] || break; rm -rf "$d"; total=$((total-1)); echo "보관 기간 경과로 삭제: $d"; done
}
