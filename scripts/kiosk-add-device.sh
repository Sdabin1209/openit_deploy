#!/usr/bin/env bash
# 키오스크 기기 토큰 관리(D85 F절, D88/U8: 기기별 토큰). 사용: kiosk-add-device.sh add <기기 ID> [--question-set <문진표 ID>] | rotate <기기 ID> | place <기기 ID> <문진표 ID>|- | remove <기기 ID> | from-list [파일] | list | sync   [--apply]
#   문진표 배치(계약 3.3.0 DeviceConfig.question_set_id, 선택, ADR 0052): 기기 설정에 문진표 ID 를 적으면 그 기기는 그 문진표로 자동 시작한다. 없으면 활성 문진표가 둘 이상일 때 키오스크 첫 화면에서 고른다.
#     add --question-set 또는 목록 파일의 둘째 칸(`기기ID 문진표ID`)으로 정하고, place 로 나중에 바꾼다(`-` 는 배치 해제). rotate 와 배치 없는 add·from-list 는 기존 배치를 그대로 둔다. 배치의 정본은 기기 설정 파일 하나다(다른 곳에 복사하지 않는다).
#   기기마다 산출물 secrets/kiosk-config/<ID>.json ({"device_token": ..., "allow_remote_stt": false}, 모드 600)을 만든다. 이 파일을 그 기기의 정적 서버가 CONFIG_FILE 로 마운트해 /config.json 으로 낸다
#   (kiosk-frontend 런북). 중앙 kiosk-frontend 컨테이너에는 어떤 기기의 파일도 마운트하지 않는다: 한 컨테이너가 모든 키오스크에 같은 토큰을 내면 기기별 토큰의 의미가 없고, gateway 의 인증 없는 / 경로로 토큰이 샌다(Caddyfile 이 /config.json 을 404 로 막는다).
#   rotate : 같은 ID 의 새 토큰을 만들고 산출물을 다시 쓴다(옛 토큰은 즉시 무효: 새 파일을 기기에 전한 뒤 --apply). from-list : 기기 ID 목록 파일(한 줄에 하나, # 주석)로 add 를 되풀이한다(기본 config/kiosk-devices.conf).
#   add    : secrets/tokens/kiosk-device-<ID> 에 기기 토큰을 만들고(이미 있으면 그대로) 게이트웨이 목록을 다시 쓴다. 값은 출력하지 않고 파일 경로만 알린다.
#            기기에는 그 파일의 값을 기기 설정이나 시작 URL 조각(#)으로 한 번 전하고, 앱은 Authorization: Bearer 로 보낸다(URL 쿼리 금지).
#   remove : 토큰 파일을 지워 폐기하고 목록을 다시 쓴다.      sync : 파일을 직접 지웠을 때 목록만 다시 쓴다.      list : 기기 ID 목록.
#   --apply: 목록을 쓴 뒤 게이트웨이를 다시 시작해 반영한다(DEPLOY_PROJECT, 기본 deploy). Caddy 가 설정을 읽을 때 한 번 치환해 다시 시작해야 반영된다.
#   환경: SECRETS_DIR(기본 secrets/)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/gateway-lib.sh"
D=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}; [ -d "$D/tokens" ] || die "비밀 폴더가 없다: $D/tokens (먼저 scripts/gen-secrets.sh)"
CMD=${1:-}; ID=${2:-}; APPLY=0; QSET=keep; PLACE=${3:-}
args=("$@"); for ((i=0;i<${#args[@]};i++)); do case "${args[$i]}" in --apply) APPLY=1;; --question-set) QSET=${args[$((i+1))]:-}; [ -n "$QSET" ] || die "--question-set 에는 문진표 ID 가 필요하다";; esac; done
case "$CMD" in
  add|remove|rotate|place) [[ "$ID" =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]] || die "기기 ID 규칙: 소문자·숫자·- (1~32자): '$ID'";;
  list|sync|from-list) ;;
  *) die "사용: kiosk-add-device.sh add|rotate|remove <기기 ID> | from-list [파일] | list | sync [--apply]";;
esac
kiosk_config() { # kiosk_config <ID> [keep|-|<문진표 ID>]: 기기 산출물(600). R7: 쓰기 전에 계약 DeviceConfig 로 검증한다(어기면 파일을 만들지 않고 실패: 기존 산출물도 그대로 둔다)
  mkdir -p "$D/kiosk-config"; chmod 700 "$D/kiosk-config"
  ( umask 077; "$DEPLOY_PY" -W ignore -I - "$D/tokens/kiosk-device-$1" "$D/kiosk-config/$1.json" "${2:-keep}" <<'PY'
import json, os, sys, tempfile
from boundary_contracts import validator
cfg = {"device_token": open(sys.argv[1]).read().strip(), "allow_remote_stt": False}
qs = sys.argv[3]   # keep: 기존 배치 유지(없으면 없음), -: 해제, 그 밖: 그 문진표 ID. 왜 파일에서 읽나: 배치의 정본이 기기 설정 파일 하나라서 회전이 배치를 지우지 않게 한다(ADR 0052)
if qs == "keep":
    try: qs = json.load(open(sys.argv[2])).get("question_set_id", "-")
    except (OSError, ValueError): qs = "-"
if qs != "-": cfg["question_set_id"] = qs
errs = [f"/{'/'.join(map(str, e.path))}: {e.validator} 위반" for e in validator("DeviceConfig").iter_errors(cfg)]   # 값(토큰)은 출력하지 않는다
if errs:
    sys.exit("기기 설정이 계약 DeviceConfig 를 어긴다: " + "; ".join(errs))
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(sys.argv[2]), prefix=".cfg-"); os.close(fd)
with open(tmp, "w") as f: f.write(json.dumps(cfg) + "\n")
os.replace(tmp, sys.argv[2])
PY
  ) || die "기기 $1 의 설정을 쓰지 못했다(위 사유)"; chmod 600 "$D/kiosk-config/$1.json"
}
case "$CMD" in
  from-list) LIST=${2:-}; case "$LIST" in ""|--*) LIST=$DEPLOY_ROOT/config/kiosk-devices.conf;; esac;   # from-list --apply 처럼 옵션이 두 번째 인자로 오면 기본 목록(점검 L4)
    [ -f "$LIST" ] || die "기기 목록 파일이 없다: $LIST (config/kiosk-devices.conf.example 참고)"
    while read -r id qsid _; do case "$id" in ""|\#*) continue;; esac; case "${qsid:-}" in ""|\#*) qsid=keep;; esac; [[ "$id" =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]] || die "기기 ID 규칙 위반: $id"
      f="$D/tokens/kiosk-device-$id"; [ -s "$f" ] || { ( umask 077; gw_rnd > "$f" ); echo "기기 토큰을 만들었다: $id" >&2; }; chmod 600 "$f"; kiosk_config "$id" "$qsid"; done < "$LIST";;
  rotate) f="$D/tokens/kiosk-device-$ID"; [ -s "$f" ] || die "없는 기기: $ID (먼저 add)"; ( umask 077; gw_rnd > "$f" ); chmod 600 "$f"; kiosk_config "$ID" keep; echo "회전: $ID (옛 토큰 무효. 새 산출물 $D/kiosk-config/$ID.json 을 기기에 전한다)" >&2;;
  add) f="$D/tokens/kiosk-device-$ID"; [ -s "$f" ] && echo "이미 있다: $ID (토큰은 그대로)" >&2 || { ( umask 077; gw_rnd > "$f" ); echo "기기 토큰을 만들었다: $ID" >&2; }; chmod 600 "$f"; kiosk_config "$ID" "$QSET"; echo "토큰 파일: $f (값은 출력하지 않는다)" >&2;;
  place) [ -s "$D/tokens/kiosk-device-$ID" ] || die "없는 기기: $ID (먼저 add)"; [ -n "$PLACE" ] && [[ "$PLACE" != --* ]] || die "사용: kiosk-add-device.sh place <기기 ID> <문진표 ID>|-"; kiosk_config "$ID" "$PLACE"; echo "배치: $ID -> $PLACE (새 산출물 $D/kiosk-config/$ID.json 을 기기에 전한다. 게이트웨이 재시작은 필요 없다)" >&2;;
  remove) rm -f "$D/tokens/kiosk-device-$ID" "$D/kiosk-config/$ID.json"; echo "폐기: $ID" >&2;;
  list) gw_devices "$D"; exit 0;;
esac
gw_write_devices "$D"
echo "게이트웨이 기기 목록을 다시 썼다($(gw_devices "$D" | wc -l)대)" >&2
if [ $APPLY = 1 ]; then dc "${DEPLOY_PROJECT:-deploy}" restart gateway survey-service >/dev/null && echo "gateway 와 survey-service 를 다시 시작했다(기기 목록·기기 토큰 표 반영)" >&2
else echo "반영하려면 게이트웨이를 다시 시작한다: dc ... restart gateway (또는 --apply)" >&2; fi
