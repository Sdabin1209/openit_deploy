#!/usr/bin/env bash
# 키오스크 기기 등록 관리(계약 PUBLIC_API F절, D136: 기기 인증은 mTLS 하나, 허용 목록 DeviceAllowlist). 사용:
#   kiosk-add-device.sh add <기기 ID> [--question-set <문진표 ID>] | rotate <기기 ID> | register <기기 ID> <일련번호> | revoke-serial <기기 ID> <일련번호>
#                       | place <기기 ID> <문진표 ID>|- | remove <기기 ID> | from-list [파일] | list
#   등록·회전·폐기는 허용 목록(DEVICE_ALLOWLIST_DIR/allowlist.json, 기본 state/device-allowlist)을 바꾸는 것이다. 입구는 요청마다 목록을 대조하므로 재시작이 필요 없다(계약 F절).
#   add      : 개발용 기기 CA(secrets/device-ca.key, gen-secrets.sh --test-fixtures 가 만든다)로 기기 인증서를 openssl 로 발급해 일련번호를 목록에 더한다(이미 있으면 그대로). 인증서·키는 secrets/device-certs/<ID>.crt·.key(키 600).
#            운영의 인증서 발급은 조직 PKI/MDM 몫이다(D113): 발급된 인증서의 일련번호(openssl x509 -noout -serial)를 register 로 넣는다.
#   rotate   : 새 인증서를 발급하고 일련번호를 목록에 더한다(옛 일련번호도 남는다: 새 인증서를 기기에 넣은 뒤 revoke-serial 로 옛 것을 뺀다. 계약: 회전 = 새 일련번호를 더한 뒤 옛 것을 뺀다).
#   register : 이미 발급된 인증서의 일련번호(16진수)를 기기 ID 에 더한다. revoke-serial: 일련번호 하나를 뺀다(마지막이면 기기가 빠진다). remove: 기기 전체를 뺀다(인증서 파일도 지운다). 인증서 파일만 지워서는 폐기가 아니다.
#   기기마다 산출물 secrets/kiosk-config/<ID>.json (DeviceConfig: allow_remote_stt, question_set_id, 모드 600)을 만든다. 그 기기의 정적 서버가 CONFIG_FILE 로 마운트해 /config.json 으로 낸다.
#   문진표 배치(계약 3.3.0 DeviceConfig.question_set_id, ADR 0052): add --question-set 또는 목록 파일의 둘째 칸(`기기ID 문진표ID`)으로 정하고 place 로 바꾼다(`-` 는 해제). 배치의 정본은 기기 설정 파일 하나다.
#   환경: SECRETS_DIR(기본 secrets/), DEVICE_ALLOWLIST_DIR(기본 state/device-allowlist: 공개 입구에 읽기 전용으로 마운트하는 폴더, 목록 파일 하나만 둔다)
#   동시에 부르면 목록 갱신은 배타 잠금으로 차례가 된다(scripts/device_allowlist.py).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
source "$(dirname "$0")/gateway-lib.sh"
D=${SECRETS_DIR:-$DEPLOY_ROOT/secrets}; [ -d "$D" ] || die "비밀 폴더가 없다: $D (먼저 scripts/gen-secrets.sh)"
CMD=${1:-}; ID=${2:-}; QSET=keep; PLACE=${3:-}
args=("$@"); for ((i=0;i<${#args[@]};i++)); do case "${args[$i]}" in --apply) die "--apply 는 없어졌다: 목록은 요청마다 대조되어 재시작이 필요 없다(ADR 0069)";; --question-set) QSET=${args[$((i+1))]:-}; [ -n "$QSET" ] || die "--question-set 에는 문진표 ID 가 필요하다";; esac; done
case "$CMD" in
  add|remove|rotate|place|register|revoke-serial) [[ "$ID" =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]] || die "기기 ID 규칙: 소문자·숫자·- (1~32자): '$ID'";;
  list|from-list) ;;
  *) die "사용: kiosk-add-device.sh add|rotate|remove <기기 ID> | register|revoke-serial <기기 ID> <일련번호> | place <기기 ID> <문진표 ID>|- | from-list [파일] | list";;
esac
kiosk_config() { # kiosk_config <ID> [keep|-|<문진표 ID>]: 기기 산출물(600). R7: 쓰기 전에 계약 DeviceConfig 로 검증한다(어기면 파일을 만들지 않고 실패: 기존 산출물도 그대로 둔다)
  mkdir -p "$D/kiosk-config"; chmod 700 "$D/kiosk-config"
  ( umask 077; "$DEPLOY_PY" -W ignore -I - "$D/kiosk-config/$1.json" "${2:-keep}" <<'PY'
import json, os, sys, tempfile
from boundary_contracts import validator
cfg = {"allow_remote_stt": False}
qs = sys.argv[2]   # keep: 기존 배치 유지(없으면 없음), -: 해제, 그 밖: 그 문진표 ID. 왜 파일에서 읽나: 배치의 정본이 기기 설정 파일 하나라서 회전이 배치를 지우지 않게 한다(ADR 0052)
if qs == "keep":
    try: qs = json.load(open(sys.argv[1])).get("question_set_id", "-")
    except (OSError, ValueError): qs = "-"
if qs != "-": cfg["question_set_id"] = qs
errs = [f"/{'/'.join(map(str, e.path))}: {e.validator} 위반" for e in validator("DeviceConfig").iter_errors(cfg)]
if errs:
    sys.exit("기기 설정이 계약 DeviceConfig 를 어긴다: " + "; ".join(errs))
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(sys.argv[1]), prefix=".cfg-"); os.close(fd)
with open(tmp, "w") as f: f.write(json.dumps(cfg) + "\n")
os.replace(tmp, sys.argv[1])
PY
  ) || die "기기 $1 의 설정을 쓰지 못했다(위 사유)"; chmod 600 "$D/kiosk-config/$1.json"
}
issue() { # issue <ID>: 인증서 발급 + 목록에 일련번호 더하기. 발급은 키를 비밀 폴더에 두고 일련번호만 목록으로 간다
  local s; s=$(gw_issue_device_cert "$D" "$1") || die "기기 $1 인증서를 발급하지 못했다"; gw_allowlist add "$1" "$s" || die "기기 $1 을 허용 목록에 넣지 못했다"
}
add_one() { # add_one <ID> <문진표|keep>
  if gw_allowlist has "$1"; then echo "이미 있다: $1 (인증서·일련번호는 그대로)" >&2
  else issue "$1"; echo "기기를 등록했다: $1 (인증서 $D/device-certs/$1.crt, 키는 $1.key: 값은 출력하지 않는다)" >&2; fi
  kiosk_config "$1" "$2"
}
case "$CMD" in
  from-list) LIST=${2:-}; case "$LIST" in ""|--*) LIST=$DEPLOY_ROOT/config/kiosk-devices.conf;; esac;   # from-list --apply 처럼 옵션이 두 번째 인자로 오면 기본 목록(점검 L4)
    [ -f "$LIST" ] || die "기기 목록 파일이 없다: $LIST (config/kiosk-devices.conf.example 참고)"
    while read -r id qsid _; do case "$id" in ""|\#*) continue;; esac; case "${qsid:-}" in ""|\#*) qsid=keep;; esac; [[ "$id" =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]] || die "기기 ID 규칙 위반: $id"
      add_one "$id" "$qsid"; done < "$LIST";;
  add) add_one "$ID" "$QSET";;
  rotate) gw_allowlist has "$ID" || die "없는 기기: $ID (먼저 add)"; old=$(gw_allowlist serials "$ID" | tr '\n' ' '); issue "$ID"; kiosk_config "$ID" keep
    echo "회전: $ID 새 인증서를 발급해 목록에 더했다. 새 인증서($D/device-certs/$ID.crt)를 기기에 넣은 뒤 옛 일련번호를 뺀다: kiosk-add-device.sh revoke-serial $ID <일련번호> (옛 일련번호: $old)" >&2;;
  register) [ -n "$PLACE" ] || die "사용: kiosk-add-device.sh register <기기 ID> <일련번호(16진수)>"; gw_allowlist add "$ID" "$PLACE" || die "등록 실패"; kiosk_config "$ID" "$QSET"; echo "등록: $ID" >&2;;
  revoke-serial) [ -n "$PLACE" ] || die "사용: kiosk-add-device.sh revoke-serial <기기 ID> <일련번호>"; gw_allowlist remove-serial "$ID" "$PLACE" || die "일련번호를 빼지 못했다"; echo "일련번호를 뺐다: $ID (다음 요청부터 그 인증서는 거부된다)" >&2;;
  place) gw_allowlist has "$ID" || die "없는 기기: $ID (먼저 add)"; [ -n "$PLACE" ] && [[ "$PLACE" != --* ]] || die "사용: kiosk-add-device.sh place <기기 ID> <문진표 ID>|-"; kiosk_config "$ID" "$PLACE"; echo "배치: $ID -> $PLACE (새 산출물 $D/kiosk-config/$ID.json 을 기기에 전한다)" >&2;;
  remove) gw_allowlist remove "$ID" || die "목록에서 빼지 못했다"; rm -f "$D/device-certs/$ID.crt" "$D/device-certs/$ID.key" "$D/kiosk-config/$ID.json"; echo "폐기: $ID (목록에서 뺐다. 다음 요청부터 거부된다)" >&2;;
  list) gw_allowlist list; exit 0;;
esac
