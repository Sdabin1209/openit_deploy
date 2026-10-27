#!/usr/bin/env bash
# 저장소(볼륨)별 백업. 사용: backup.sh [저장소 ...]   저장소: gate-data models-data registry-data (파일 저장소. 비우면 gate-data models-data registry-data). 데이터베이스는 PostgreSQL 이라 pg-backup.sh
#  환경: DEPLOY_PROJECT(기본 deploy), BACKUP_CONFIG(기본 config/backup.env), REGISTRY_PROJECT(기본 deploy-registry: 레지스트리 볼륨은 별도 프로젝트 소유)
# 설정(BACKUP_DIR, BACKUP_RETENTION_DAYS, 수신자 공개키)이 없거나 비어 있으면 CRIT 로 거부한다(종료 코드 2, 코드에 기본값 없음). 설정·암호화는 backup-lib.sh.
# 저장소마다 스냅샷을 tar 하나로 묶어 암호화한다(복원 시 풀어서 restore.sh 에 준다). 암호화를 쓰지 않는 시험 모드(BACKUP_ALLOW_PLAINTEXT=1)에서는 예전처럼 디렉터리 그대로.
# registry-data 를 넣은 이유: 이미지는 CI 로 다시 만들 수 있으나 digest 로 고정된 운영 이미지를 레지스트리가 잃으면 롤백이 불가능하다(docs/adr/0001).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/backup-lib.sh"
backup_load_config
P=${DEPLOY_PROJECT:-deploy}
LOCK=${DEPLOY_LOCK:-$DEPLOY_ROOT/locks/images.lock}
UTIL=$(sed -n 's/^UTIL_IMAGE=//p' "$LOCK")
[ -n "$UTIL" ] || die "UTIL_IMAGE 가 잠금 파일에 없다"
STORES=${*:-gate-data models-data registry-data}   # 세션·문항·로그·레지스트리 DB 는 PostgreSQL(D85)이라 pg-backup.sh 가 맡는다
TS=$(date -u +%Y%m%dT%H%M%SZ)
vol_of() { case "$1" in registry-data) echo "${REGISTRY_PROJECT:-deploy-registry}_registry-data";; *) echo "${P}_$1";; esac; }
for s in $STORES; do
  V=$(vol_of "$s")
  "$DOCKER" volume inspect "$V" >/dev/null 2>&1 || { case "$s" in registry-data) echo "건너뜀: 레지스트리 볼륨 $V 가 없다(레지스트리 프로젝트가 이 서버에 없음)"; continue;; *) die "볼륨이 없다: $V";; esac; }
  mkdir -p "$BACKUP_DIR/$s"; chmod 700 "$BACKUP_DIR/$s"
  # 일관성: SQLite 파일이 있으면 backup API(읽기 전용 연결). 나머지는 파일 복사. 서비스가 떠 있어도 된다.
  "$DOCKER" run --rm -v "$V:/src" -v "$BACKUP_DIR:/out" -v "$DEPLOY_ROOT/scripts:/tool:ro" \
    "$UTIL" python /tool/backup_tool.py backup /src "/out/$s/.partial-$TS" --store "$s" --owner "$(id -u):$(id -g)" >/dev/null
  P_DIR="$BACKUP_DIR/$s/.partial-$TS"
  if [ "$BACKUP_CRYPT" != none ]; then   # 디렉터리 -> tar -> 암호화. MANIFEST 는 평문 해시 목록이라 파일 이름·해시만 든다(내용 아님)
    tar -C "$P_DIR" -cf "$BACKUP_DIR/$s/.tar-$TS" . || die "tar 실패: $s"
    rm -rf "$P_DIR"; mkdir -p "$P_DIR"
    enc=$(backup_encrypt "$BACKUP_DIR/$s/.tar-$TS" "$P_DIR/$s.tar") || die "암호화 실패: $s"
    printf '{"store": "%s", "format": "tar", "encryption": "%s", "created_at": "%s", "stored_file": {"name": "%s", "sha256": "sha256:%s"}}\n' \
      "$s" "$BACKUP_CRYPT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(basename "$enc")" "$(sha256sum "$enc" | cut -d' ' -f1)" > "$P_DIR/MANIFEST.json"
  fi
  chmod -R u=rwX,go= "$P_DIR"   # 폴더 700, 파일 600 (컨테이너가 만든 사본의 모드를 호스트 소유자 전용으로)
  mv "$P_DIR" "$BACKUP_DIR/$s/$TS"
  echo "백업: $s -> $BACKUP_DIR/$s/$TS ($BACKUP_CRYPT)"
  backup_prune "$BACKUP_DIR/$s"
done
