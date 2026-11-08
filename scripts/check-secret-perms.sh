#!/usr/bin/env bash
# 비밀 파일 권한 점검(읽기 전용, 값은 읽지도 출력하지도 않는다). 사용: check-secret-perms.sh [비밀 폴더]   (기본 $SECRETS_DIR 또는 secrets/)
# 규칙(docs/adr/0022-secret-file-permissions.md): 폴더 700. 호스트 전용 파일(lib.sh secret_mode 가 600)은 600/400. 컨테이너가 읽는 파일은 640 + 그룹 SECRETS_GID(0054). 다른 호스트가 읽는 추론 서버 파일 셋은 644.
# 그룹·기타 쓰기 비트는 어디서든 FAIL. 호스트 전용인데 644 이면 FAIL(평문 계정 암호 등). 컨테이너가 읽는데 600 이면 FAIL(서비스가 못 읽는다).
# 종료 코드 0 통과, 1 어긋남 있음, 2 비밀 폴더 없음. doctor.sh 가 --up 에서 부른다.
set -uo pipefail
DEPLOY_NO_DOCKER=1; source "$(dirname "$0")/lib.sh"
D=${1:-${SECRETS_DIR:-$DEPLOY_ROOT/secrets}}
[ -d "$D" ] || { echo "비밀 폴더가 없다: $D" >&2; exit 2; }
bad=0
for d in "$D" "$D/tokens"; do [ -d "$d" ] || continue
  m=$(stat -c %a "$d"); [ "$m" = 700 ] || { echo "FAIL 폴더 모드 $m (700 이어야 한다): ${d#$D}/ (해결: chmod 700 $d)"; bad=$((bad+1)); }; done
for f in "$D"/tokens/* "$D"/devices/*; do [ -f "$f" ] || continue
  n=$(basename "$f"); m=$(stat -c %a "$f"); want=$(secret_mode "$n")
  [ "$(basename "$(dirname "$f")")" = devices ] && want=640   # 기기 토큰 폴더는 공개 입구 컨테이너가 읽는다(그룹 읽기)
  if (( 8#$m & 8#022 )); then echo "FAIL $n 모드 $m: 그룹·기타 쓰기 비트가 있다"; bad=$((bad+1))
  elif [ "$want" = 600 ] && (( 8#$m & 8#077 )); then echo "FAIL $n 모드 $m: 호스트 전용 비밀은 600 이어야 한다 (chmod 600; gen-secrets.sh 를 다시 실행하면 바로잡는다)"; bad=$((bad+1))
  elif [ "$want" = 640 ] && { (( 8#$m & 8#007 )) || ! (( 8#$m & 8#040 )); }; then echo "FAIL $n 모드 $m: 컨테이너가 읽는 파일은 640 이어야 한다(그룹 읽기 있고 기타 접근 없음). 아니면 서비스가 못 읽는다(600) 또는 필요 이상으로 열려 있다(기타 접근) (gen-secrets.sh 를 다시 실행)"; bad=$((bad+1))
  elif [ "$want" = 640 ] && [ "$(stat -c %g "$f")" != "$SECRETS_GID" ]; then echo "FAIL $n 그룹 $(stat -c %g "$f"): 컨테이너 group_add 의 gid(SECRETS_GID=$SECRETS_GID)와 다르다 -> 서비스가 못 읽는다 (gen-secrets.sh 를 다시 실행)"; bad=$((bad+1))
  elif false; then echo "FAIL $n 모드 $m: 다른 호스트의 컨테이너가 읽는 파일인데 기타 읽기가 없다 (gen-secrets.sh 를 다시 실행)"; bad=$((bad+1)); fi
done
# 영역 DB 계정·접속 URI(db-accounts, db-urls; gen-db-secrets-all.sh): 컨테이너가 읽으므로 파일 640 + 그룹 SECRETS_GID, 폴더 750(기타 접근 없음). 호스트 전용 기기 CA 키·기기 키는 600, 공개 인증서(.pem/.crt)는 그룹·기타 쓰기 없음.
# 시험 사용자 암호(idp-users-secrets, idp-test-users.sh)는 비밀 폴더 밖(state/)에 있고 잡 컨테이너가 읽으므로 640 + 그룹 SECRETS_GID 다(IDP_USERS_SECRETS 로 위치를 바꾼다).
# 왜 여기까지: 이 점검은 tokens/·devices/ 만 봐서 DB 비밀과 기기 CA 키가 644 로 나와도 통과했다(2026-11-08 점검 범위 구멍).
perm_of() { stat -c %a "$1"; }
for dir in "$D"/db-accounts "$D"/db-urls; do [ -d "$dir" ] || continue
  while IFS= read -r -d '' e; do n=${e#$D/}; m=$(perm_of "$e")
    if [ -d "$e" ]; then (( 8#$m & 8#027 )) && { echo "FAIL $n/ 폴더 모드 $m: 750 이어야 한다(그룹 쓰기·기타 접근 없음)"; bad=$((bad+1)); }
    else
      if (( 8#$m & 8#027 )) || ! (( 8#$m & 8#040 )); then echo "FAIL $n 모드 $m: 컨테이너가 읽는 DB 비밀은 640 이어야 한다"; bad=$((bad+1))
      elif [ "$(stat -c %g "$e")" != "$SECRETS_GID" ]; then echo "FAIL $n 그룹 $(stat -c %g "$e"): group_add 의 gid(SECRETS_GID=$SECRETS_GID)와 다르다 -> 서비스가 못 읽는다"; bad=$((bad+1)); fi
    fi
  done < <(find "$dir" -mindepth 1 -print0)
done
for f in "$D"/device-ca.key "$D"/device-certs/*.key; do [ -f "$f" ] || continue
  m=$(perm_of "$f"); (( 8#$m & 8#077 )) && { echo "FAIL ${f#$D/} 모드 $m: 호스트 전용 개인 키는 600 이어야 한다"; bad=$((bad+1)); }; done
for f in "$D"/device-ca.pem "$D"/device-certs/*.crt; do [ -f "$f" ] || continue
  m=$(perm_of "$f"); (( 8#$m & 8#022 )) && { echo "FAIL ${f#$D/} 모드 $m: 그룹·기타 쓰기 비트가 있다"; bad=$((bad+1)); }; done
IDPD=${IDP_USERS_SECRETS:-$DEPLOY_ROOT/state/idp-users-secrets}
if [ -d "$IDPD" ]; then for f in "$IDPD"/*; do [ -f "$f" ] || continue
  m=$(perm_of "$f"); if (( 8#$m & 8#027 )) || ! (( 8#$m & 8#040 )); then echo "FAIL idp-users-secrets/$(basename "$f") 모드 $m: 640 이어야 한다"; bad=$((bad+1))
  elif [ "$(stat -c %g "$f")" != "$SECRETS_GID" ]; then echo "FAIL idp-users-secrets/$(basename "$f") 그룹 $(stat -c %g "$f"): SECRETS_GID($SECRETS_GID)와 다르다"; bad=$((bad+1)); fi
done; fi
[ $bad = 0 ] && { echo "OK 비밀 파일 권한 ($(ls "$D/tokens" 2>/dev/null | wc -l)개 + 기기 $(ls "$D/devices" 2>/dev/null | wc -l)개)"; exit 0; } || { echo "비밀 권한 어긋남 ${bad}건"; exit 1; }
