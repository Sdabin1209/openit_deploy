#!/usr/bin/env bash
# 내리기. 사용: scripts/down.sh [프로젝트=deploy] [--stop | --remove | --purge] [--registry] [--purge-hf-cache] [--yes-purge-<프로젝트>]
#   --stop     컨테이너만 멈춘다. 데이터·네트워크는 그대로(`docker compose -p <프로젝트> start` 로 이어 간다)
#   --remove   (기본) 컨테이너와 네트워크를 지운다. 데이터 볼륨은 남는다(다시 up.sh 하면 이어 쓴다)
#   --purge    볼륨까지 지운다. 되돌릴 수 없다. 지울 볼륨과 들어 있는 데이터를 보여 주고, 프로젝트 이름을 직접 쳐야 진행한다
#              (비대화형은 --yes-purge-<프로젝트> 를 명시해야 한다)
#   --registry 로컬 레지스트리(REGISTRY_PROJECT, 기본 deploy-registry)도 내린다. 이미지는 레지스트리 볼륨에 남는다.
#              레지스트리 볼륨 삭제는 --purge 와 함께 쓸 때만, 따로 확인한다
#   --purge-hf-cache  실제 LLM의 Hugging Face 캐시 볼륨(deploy-llm-hf-cache, 약 3GB)을 지운다. **캐시는 기본적으로 남는다**(프로젝트 밖 볼륨이라
#              --remove/--purge 도 지우지 않는다). 볼륨 이름을 직접 쳐야 하며 비대화형은 --yes-purge-deploy-llm-hf-cache. 다른 옵션 없이 쓰면 프로젝트는 건드리지 않는다
# 프로젝트 이름은 deploy 또는 deploy- 로 시작해야 한다(다른 이름은 거부). 끝나면 남은 자원을 보여 준다.
# 참고: `dc` 는 lib.sh 안의 셸 함수라 터미널에서 직접 칠 수 없다. 이 스크립트를 쓴다. 표준 docker 만 쓴다.
set -uo pipefail
DEPLOY_NO_DOCKER=1   # 사용법·인자 검사는 Docker 없이도 동작한다
source "$(dirname "$0")/lib.sh"
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; }
P=""; MODE=remove; REG=0; YES=""; HFP=0; HFYES=0; MODE_SET=0
for x in "$@"; do
  case "$x" in
    -h|--help) usage; exit 0;;
    --stop) MODE=stop; MODE_SET=1;; --remove) MODE=remove; MODE_SET=1;; --purge) MODE=purge; MODE_SET=1;; --registry) REG=1;;
    --purge-hf-cache) HFP=1;;
    --yes-purge-"${HF_CACHE_VOLUME:-deploy-llm-hf-cache}") HFYES=1;;
    --yes-purge-*) YES=${x#--yes-purge-};;
    -*) usage >&2; echo "알 수 없는 인자: $x" >&2; exit 2;;
    *) [ -z "$P" ] || { usage >&2; echo "프로젝트는 하나만 받는다: $x" >&2; exit 2; }; P=$x;;
  esac
done
[ $HFP = 1 ] || [ $HFYES = 0 ] || { echo "--yes-purge-$HF_CACHE_VOLUME 는 --purge-hf-cache 와 함께만 쓴다" >&2; exit 2; }
# --purge-hf-cache 만 주면 캐시 볼륨만 처리한다(프로젝트는 건드리지 않는다)
HF_ONLY=0; [ $HFP = 1 ] && [ $MODE_SET = 0 ] && [ -z "$P" ] && [ $REG = 0 ] && HF_ONLY=1
P=${P:-deploy}
case "$P" in deploy|deploy-*) ;; *) usage >&2; echo "허용되지 않는 프로젝트 이름: $P (deploy 또는 deploy- 로 시작해야 한다)" >&2; exit 2;; esac
[ -z "$YES" ] || [ "$YES" = "$P" ] || { echo "--yes-purge-$YES 는 프로젝트 $P 와 맞지 않는다" >&2; exit 2; }
[ -z "$YES" ] || [ "$MODE" = purge ] || { echo "--yes-purge-* 는 --purge 와 함께만 쓴다" >&2; exit 2; }
detect_docker
if [ $HF_ONLY = 1 ]; then hf_cache_purge $HFYES; exit $?; fi

REGP=${REGISTRY_PROJECT:-deploy-registry}
vols_of() { "$DOCKER" volume ls -q --filter "label=com.docker.compose.project=$1" 2>/dev/null; }
describe() { # 볼륨 이름(프로젝트 접두 제거) -> 들어 있는 것
  case "${1#"$P"_}" in
    survey-data) echo "문진 세션 DB, 발신함, 릴리스 작업 폴더";;
    qa-data) echo "문항 저장소(questions.sqlite3)";;
    ops-data) echo "원본 Trace 로그, 실패 사례 DB";;
    gate-data) echo "릴리스 이력(registry.sqlite3)과 번들(releases/), 승인 기록";;
    models-data) echo "모델 패키지(어댑터)";;
    serving-data) echo "추론 서버 번들 캐시(다시 받을 수 있음)";;
    gateway-*) echo "gateway 설정 사본(다시 만들어짐)";;
    *) echo "(알 수 없음)";;
  esac
}
confirm_name() { # confirm_name <이름> <주제>
  [ "$YES" = "$1" ] && return 0
  if [ -t 0 ]; then
    printf '%s 되돌릴 수 없다. 계속하려면 이름 "%s" 을(를) 그대로 입력: ' "$2" "$1"; read -r ans
    [ "$ans" = "$1" ] && return 0
  else
    echo "비대화형이다. 진행하려면 --yes-purge-$1 을 명시하라." >&2
  fi
  echo "취소했다. 아무것도 지우지 않았다." >&2; exit 1
}
compose_p() { "$DOCKER" compose -p "$P" "$@"; } # 이미 만들어진 프로젝트는 -p 만으로 stop/start/down 된다

case "$MODE" in
  stop)
    echo "== $P 컨테이너 멈춤 (데이터·네트워크 유지)"
    ids=$("$DOCKER" ps -q --filter "label=com.docker.compose.project=$P")
    [ -z "$ids" ] || "$DOCKER" stop $ids >/dev/null
    echo "이어 가기: docker compose -p $P start   (또는 scripts/up.sh $P)";;
  remove)
    echo "== $P 컨테이너·네트워크 제거 (볼륨은 남긴다)"
    compose_p --profile jobs down --remove-orphans 2>&1 | tail -3;;
  purge)
    vs=$(vols_of "$P")
    echo "== $P 볼륨 삭제 대상"
    if [ -n "$vs" ]; then for v in $vs; do printf '  %-40s %s\n' "$v" "$(describe "$v")"; done; else echo "  (볼륨 없음)"; fi
    hf_cache_exists && echo "  (HF 캐시 볼륨 $HF_CACHE_VOLUME 은 프로젝트 밖이라 지우지 않는다. 지우려면 --purge-hf-cache)"
    confirm_name "$P" "위 볼륨의 데이터가 영구히 사라진다."
    compose_p --profile jobs down -v --remove-orphans 2>&1 | tail -3;;
esac

if [ $REG = 1 ]; then
  echo "== 로컬 레지스트리 $REGP 내림"
  if [ "$MODE" = purge ]; then
    rv=$(vols_of "$REGP")
    echo "  레지스트리 볼륨(게시한 이미지가 들어 있다. 지우면 이미지를 다시 게시해야 한다): ${rv:-없음}"
    if [ -n "$rv" ]; then
      confirm_name "$REGP" "레지스트리 볼륨도 지운다."
      REGISTRY_PROJECT=$REGP bash "$DEPLOY_ROOT/scripts/registry.sh" down -v 2>&1 | tail -1
    fi
  else
    REGISTRY_PROJECT=$REGP bash "$DEPLOY_ROOT/scripts/registry.sh" down 2>&1 | tail -1
    echo "  (이미지는 레지스트리 볼륨에 남아 있다)"
  fi
fi

echo "== 남은 자원 ($P$( [ $REG = 1 ] && echo ", $REGP"))"
for q in "$P" $( [ $REG = 1 ] && echo "$REGP"); do
  "$DOCKER" ps -a --filter "label=com.docker.compose.project=$q" --format '  컨테이너 {{.Names}} ({{.Status}})'
  "$DOCKER" network ls --filter "label=com.docker.compose.project=$q" --format '  네트워크 {{.Name}}'
  "$DOCKER" volume ls --filter "label=com.docker.compose.project=$q" --format '  볼륨     {{.Name}}'
done
if [ $HFP = 1 ]; then echo "== HF 캐시 볼륨"; hf_cache_purge $HFYES; fi
