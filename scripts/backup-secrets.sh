#!/usr/bin/env bash
# secrets/ 폴더 백업(DB 백업과 별도 산출물). 사용: backup-secrets.sh      환경: SECRETS_DIR(기본 secrets/), BACKUP_CONFIG
# 왜 따로인가: DB 백업만 있고 secrets/ 가 없으면 서버를 잃었을 때 DB 암호·서비스 토큰·계정 해시·기기 토큰이 없어 서비스가 다시 서지 못하고,
#   비식별 salt(deid-salt)를 잃으면 이후 가명화 값이 이전과 이어지지 않는다(되돌릴 수 없다). 그래서 secrets/ 전체를 같은 수신자 공개키로 암호화해 서버 밖 대상에 둔다.
# 설정(config/backup.env): 공통 키(BACKUP_DIR, 수신자 공개키 등)는 backup-lib.sh. 추가 키:
#   BACKUP_SECRETS_DIR   (선택) 비밀 백업 대상 폴더. 없으면 $BACKUP_DIR/secrets. DB 백업과 다른 곳(다른 접근 권한)에 두면 더 좋다
#   BACKUP_SECRETS_KEEP  (선택) 남길 최신 개수, 기본 14(일일 백업 14일과 맞춘 시작값, 근거 기록 없음)
# 결과: <대상>/<UTC 시각>/secrets.tar.age|gpg + MANIFEST.json(파일 이름 목록과 암호화 파일 해시만; 값 없음). 폴더 700, 파일 600.
# 평문 모드(BACKUP_ALLOW_PLAINTEXT=1)에서는 거부한다: 비밀을 평문으로 내보내지 않는다. 값은 출력하지 않는다.
# 복호 개인키는 서버에 없다. **개인키를 잃으면 이 백업은 영영 못 푼다.** 복구: docs/runbook.md 4-6절, scripts/restore-secrets.sh
set -euo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/backup-lib.sh"
backup_load_config
[ "$BACKUP_CRYPT" != none ] || { echo "CRIT: 비밀 백업은 평문으로 하지 않는다(BACKUP_ALLOW_PLAINTEXT 를 끄고 수신자 공개키를 설정한다)" >&2; exit 2; }
SD=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}
[ -d "$SD/tokens" ] || { echo "건너뜀: 비밀 폴더가 없다($SD): 이 서버에는 백업할 비밀이 없다"; exit 0; }
OUT=${BACKUP_SECRETS_DIR:-$BACKUP_DIR/secrets}; KEEP=${BACKUP_SECRETS_KEEP:-14}
[[ "$KEEP" =~ ^[1-9][0-9]*$ ]] || { echo "CRIT: BACKUP_SECRETS_KEEP 는 1 이상의 정수: '$KEEP'" >&2; exit 2; }
umask 077; mkdir -p "$OUT"; chmod 700 "$OUT"
TS=$(date -u +%Y%m%dT%H%M%SZ); W="$OUT/.partial-$TS"; mkdir -p "$W"; trap 'rm -rf "$W"' EXIT
( cd "$SD" && tar -cf "$W/secrets.tar" . ) || die "tar 실패"
names=$(tar -tf "$W/secrets.tar" | sed 's|^\./||' | grep -v '/$' | grep -v '^$' | sort)
enc=$(backup_encrypt "$W/secrets.tar" "$W/secrets.tar") || die "암호화 실패"
printf '{"store": "secrets", "format": "tar", "encryption": "%s", "created_at": "%s", "file_count": %s, "stored_file": {"name": "%s", "sha256": "sha256:%s"}, "note": "복호 개인키는 서버 밖. 잃으면 복구 불가"}\n' \
  "$BACKUP_CRYPT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(echo "$names" | wc -l)" "$(basename "$enc")" "$(sha256sum "$enc" | cut -d' ' -f1)" > "$W/MANIFEST.json"
chmod 600 "$W"/*; chmod 700 "$W"; mv "$W" "$OUT/$TS"; trap - EXIT
echo "비밀 백업: $OUT/$TS ($BACKUP_CRYPT, 파일 $(echo "$names" | wc -l)개, 복호 개인키는 서버 밖에 있어야 한다)"
mapfile -t all < <(find "$OUT" -mindepth 1 -maxdepth 1 -type d -name '2*' | sort)
n=${#all[@]}; for d in "${all[@]}"; do [ "$n" -gt "$KEEP" ] || break; rm -rf "$d"; n=$((n-1)); echo "보존 개수($KEEP) 초과로 삭제: $d"; done
