#!/usr/bin/env bash
# 저장소(볼륨)별 백업. 사용: backup.sh [저장소 ...]   저장소: gate-data models-data registry-data (파일 저장소. 비우면 gate-data models-data registry-data). 데이터베이스는 PostgreSQL 이라 pg-backup.sh
#  환경: DEPLOY_PROJECT(기본 deploy), BACKUP_CONFIG(기본 config/backup.env), REGISTRY_PROJECT(기본 deploy-registry: 레지스트리 볼륨은 별도 프로젝트 소유)
# 설정(BACKUP_DIR, BACKUP_RETENTION_DAYS, 수신자 공개키)이 없거나 비어 있으면 CRIT 로 거부한다(종료 코드 2, 코드에 기본값 없음). 설정·암호화는 backup-lib.sh.
# 저장소마다 스냅샷을 tar 하나로 묶어 암호화한다(복원 시 풀어서 restore.sh 에 준다). 암호화를 쓰지 않는 시험 모드(BACKUP_ALLOW_PLAINTEXT=1)에서는 예전처럼 디렉터리 그대로.
# gateway-data(내부 CA 루트·비밀키)도 같은 암호화 경로로 백업한다(점검 M3). 복원하면 루트가 유지되어 기기들이 다시 신뢰하지 않아도 된다(runbook 9-1).
# registry-data 를 넣은 이유: 이미지는 CI 로 다시 만들 수 있으나 digest 로 고정된 운영 이미지를 레지스트리가 잃으면 롤백이 불가능하다(docs/adr/0020-backup-tool-and-encryption.md).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/backup-lib.sh"
backup_load_config
P=${DEPLOY_PROJECT:-deploy}
LOCK=${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$LOCK")
[ -n "$UTIL" ] || die "UTIL_IMAGE 가 잠금 파일에 없다"
STORES=${*:-gate-data models-data registry-data gateway-data}   # 세션·문항·로그·레지스트리 DB 는 PostgreSQL(D85)이라 pg-backup.sh 가 맡는다
TS=$(date -u +%Y%m%dT%H%M%SZ)
umask 077   # 임시 평문 tar·partial 도 소유자 전용
# 겹침 실행 방지(점검 M4): 같은 BACKUP_DIR 에서 두 번째 backup.sh 가 동시에 돌면 첫 번째의 진행 중 .partial 을 prune 이 지울 수 있다. 잠금을 못 잡으면 거부한다(종료 4)
mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR" 2>/dev/null || true
exec 9>"$BACKUP_DIR/.backup.lock"; flock -n 9 || { echo "CRIT: 다른 백업이 같은 BACKUP_DIR 에서 진행 중이다($BACKUP_DIR/.backup.lock): 겹쳐 돌리지 않는다" >&2; exit 4; }
SKIPPED=""
# 정리(점검 M1): 암호화 실패·중단·시그널 어느 경로에서도 평문 임시 파일(.tar-<시각>)과 partial(.partial-<시각>)을 지운다. 지우지 못하면 CRIT 로 남기고 비정상 종료(3)한다.
CUR=""
cleanup_tmp() {
  local rc=$? s left=""
  for s in $STORES; do
    rm -rf "$BACKUP_DIR/$s/.tar-$TS" "$BACKUP_DIR/$s/.partial-$TS" 2>/dev/null
    for f in "$BACKUP_DIR/$s/.tar-$TS" "$BACKUP_DIR/$s/.partial-$TS"; do [ -e "$f" ] && left="$left $f"; done
  done
  if [ -n "$left" ]; then echo "CRIT: 임시 평문/partial 파일을 지우지 못했다(수동 삭제 필요):$left" >&2; exit 3; fi
  exit $rc
}
trap cleanup_tmp EXIT; trap 'exit 130' INT; trap 'exit 143' TERM
vol_of() { case "$1" in registry-data) echo "${REGISTRY_PROJECT:-deploy-registry}_registry-data";; *) echo "${P}_$1";; esac; }
for s in $STORES; do
  # gateway-data: gateway(Caddy) 내부 CA 루트와 비밀키(/data/caddy/pki). 잃으면 새 CA 가 만들어져 모든 키오스크·직원 PC가 다시 신뢰해야 한다(점검 M3). 비밀키라 평문으로는 백업하지 않는다(runbook 9-1)
  if [ "$s" = gateway-data ] && [ "$BACKUP_CRYPT" = none ]; then echo "경고(WARN): gateway-data(CA 비밀키)는 평문으로 백업하지 않아 건너뛴다 -> 이 서버에는 CA 백업이 없다. 평문 모드(BACKUP_ALLOW_PLAINTEXT)는 시험 전용이다(암호화 설정 필요)" >&2; SKIPPED="$SKIPPED gateway-data"; continue; fi
  V=$(vol_of "$s")
  "$DOCKER" volume inspect "$V" >/dev/null 2>&1 || { case "$s" in registry-data) echo "건너뜀: 레지스트리 볼륨 $V 가 없다(레지스트리 프로젝트가 이 서버에 없음)"; continue;; *) die "볼륨이 없다: $V";; esac; }
  mkdir -p "$BACKUP_DIR/$s"; chmod 700 "$BACKUP_DIR/$s"
  # 일관성: SQLite 파일이 있으면 backup API(읽기 전용 연결). 나머지는 파일 복사. 서비스가 떠 있어도 된다.
  "$DOCKER" run --rm -v "$V:/src" -v "$BACKUP_DIR:/out" -v "$DEPLOY_ROOT/scripts:/tool:ro" \
    "$UTIL" python /tool/backup_tool.py backup /src "/out/$s/.partial-$TS" --store "$s" --owner "$(id -u):$(id -g)" >/dev/null
  P_DIR="$BACKUP_DIR/$s/.partial-$TS"
  if [ "$BACKUP_CRYPT" != none ]; then   # 디렉터리 -> tar -> 암호화. MANIFEST 는 평문 해시 목록이라 파일 이름·해시만 든다(내용 아님)
    tar -C "$P_DIR" -cf "$BACKUP_DIR/$s/.tar-$TS" . || die "tar 실패: $s"
    rm -rf "$P_DIR"; mkdir -p "$P_DIR"   # 평문 복사본(partial)은 tar 를 만든 즉시 지운다. 평문 tar 는 암호화 직후(성공 때는 backup_encrypt, 실패·중단 때는 위 trap)에 지워진다
    enc=$(backup_encrypt "$BACKUP_DIR/$s/.tar-$TS" "$P_DIR/$s.tar") || die "암호화 실패: $s"
    printf '{"store": "%s", "format": "tar", "encryption": "%s", "created_at": "%s", "stored_file": {"name": "%s", "sha256": "sha256:%s"}}\n' \
      "$s" "$BACKUP_CRYPT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(basename "$enc")" "$(sha256sum "$enc" | cut -d' ' -f1)" > "$P_DIR/MANIFEST.json"
  fi
  chmod -R u=rwX,go= "$P_DIR"   # 폴더 700, 파일 600 (컨테이너가 만든 사본의 모드를 호스트 소유자 전용으로)
  mv "$P_DIR" "$BACKUP_DIR/$s/$TS"
  echo "백업: $s -> $BACKUP_DIR/$s/$TS ($BACKUP_CRYPT)"
  backup_prune "$BACKUP_DIR/$s"
done
[ -z "$SKIPPED" ] || echo "요약 경고: 건너뛴 저장소:$SKIPPED (종료 코드 0이지만 백업이 빠졌다)" >&2
