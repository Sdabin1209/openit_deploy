#!/usr/bin/env bash
# check_secret_names.py 자체 시험: 임시 워크스페이스에서 compose(yaml)와 영역 코드(ast)의 *_FILE 이름 대조가 맞게 판정하는지 본다.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_NO_DOCKER=1; source "$HERE/lib.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/head/shared" "$T/deploy" "$T/area-a"; cp "$HERE/../../head/shared/areas.json" "$T/head/shared/"
python3 - "$T" <<'P'
import json, sys
p = sys.argv[1] + "/head/shared/areas.json"; d = json.load(open(p)); d["areas"] = [{"name": "area-a", "kind": "python", "version_train": False}]; json.dump(d, open(p, "w"))
P
printf 'services:\n  a:\n    environment:\n      A_TOKEN_FILE: /run/secrets/a\n      B_TOKENS_FILE: /run/secrets/b\n      UNUSED_TOKEN_FILE: /run/secrets/u\n' > "$T/deploy/compose.yaml"
rc=0; N=0
chk() { N=$((N+1)); out=$("$DEPLOY_PY" -W ignore "$HERE/check_secret_names.py" --ws "$T" 2>&1); r=$?; if [ "$r" = "$2" ] && grep -qF -- "$3" <<<"$out"; then echo "  ok   $1"; else echo "  FAIL $1 (rc=$r)"; echo "$out" | head -5; rc=1; fi; }
printf 'x = read_secret("A_TOKEN")\ny = "B_TOKEN_FILE"\n' > "$T/area-a/m.py"; chk "코드가 읽는 이름이 compose 에 있으면(단수·복수 변형 포함) 통과하고 안 읽히는 이름은 경고" 0 "WARN UNUSED_TOKEN_FILE"
printf 'x = read_secret("C_TOKEN")\n' > "$T/area-a/m.py"; chk "코드가 읽는 비밀을 compose 가 주지 않으면 FAIL(줄)" 1 "area-a/m.py:1"
printf 'x = "SOME_RULES_FILE"\n' > "$T/area-a/m.py"; chk "비밀 꼴이 아닌 설정 파일 경로는 FAIL 이 아니다" 0 "FAIL 0"
rm "$T/deploy/compose.yaml"; chk "compose 를 읽지 못하면 FAIL" 1 "읽지 못했다"
[ $rc = 0 ] && echo "통과: 비밀 이름 대조 자체 시험 ${N}건" || exit 1
