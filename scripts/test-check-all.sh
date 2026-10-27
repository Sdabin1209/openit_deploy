#!/usr/bin/env bash
# check-all.sh 자체 시험: 임시 워크스페이스에 일부러 어긋난 예시를 만들어 FAIL 이 나오고, 올바른 예시는 PASS 가 나오는지 규칙마다 본다.
# 사용: scripts/test-check-all.sh        (형제 영역이나 실제 워크스페이스를 건드리지 않는다)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
# pytest 가 있는 파이썬(규칙 8 시험용, 읽기 전용 호출). 없으면 그 시험만 건너뛴다
PYT=""; for v in "$ROOT"/../*/.venv/bin/python; do [ -x "$v" ] && "$v" -c 'import pytest' 2>/dev/null && { PYT="$v"; break; }; done
FAILS=0; N=0
README='# 영역

소개 문단.

## 1. 전체 속의 위치
## 2. 구조
## 3. 실행 방법
## 4. 현재 상태
## 5. 이 영역의 열린 항목
## 6. 더 자세한 문서
'
# mk <이름>... : 임시 워크스페이스 $W 에 영역(.git 과 올바른 README 포함)을 만든다
mk() { W="$(mktemp -d -p "$T")"; for a in "$@"; do mkdir -p "$W/$a/.git"; printf '%s' "$README" > "$W/$a/README.md"; done; }
# run <규칙번호> [환경...] : 출력을 $OUT, 종료 코드를 $RC 에
run() { local r=$1; shift; OUT=$(env CHECK_ALL_WORKSPACE="$W" CHECK_ALL_ONLY="$r" CHECK_ALL_ALLOW=/dev/null CHECK_ALL_EXCLUDE="${EXC:-/dev/null}" CHECK_ALL_ORDERED="${ORD:-$W/ordered.txt}" "$@" bash "$HERE/check-all.sh" 2>&1); RC=$?; }
expect() { # expect <설명> <PASS|FAIL|SKIP> [출력에 있어야 할 글]
  N=$((N+1)); local ok=1
  grep -q ": $2\$" <<<"$OUT" || ok=0
  if [ "$2" = FAIL ]; then [ $RC = 1 ] || ok=0; else [ $RC = 0 ] || ok=0; fi
  [ -z "${3:-}" ] || grep -qF -- "$3" <<<"$OUT" || ok=0
  if [ $ok = 1 ]; then echo "  ok   $1"; else echo "  FAIL $1 (기대 $2 ${3:-})"; echo "$OUT" | sed 's/^/       /' | head -12; FAILS=$((FAILS+1)); fi
}
BC=boundary-contracts
mkschema() { echo "Foo | 시험용 모델 출력" > "$W/ordered.txt"; mkdir -p "$W/$BC/schemas" "$W/$BC/examples"; cat > "$W/$BC/schemas/Foo.schema.json" <<'J'
{"type":"object","properties":{"a":{"type":"string"},"b":{"type":"array","items":{"type":"object","properties":{"x":{"type":"integer"},"y":{"type":"integer"}}}}}}
J
}

echo "== 0 모르는 대상"
mk deploy head; unset EXC; run 0; expect "알려진 영역만 있으면 통과" PASS
mkdir -p "$W/newarea/.git"; run 0; expect "새 영역 디렉터리는 모르는 대상으로 FAIL" FAIL "모르는 대상: newarea"
printf 'area:newarea | 시험용 제외\n' > "$W/ex.txt"; EXC="$W/ex.txt" run 0; expect "이유와 함께 제외하면 통과하고 목록을 출력한다" PASS "newarea = 시험용 제외"
printf 'area:newarea\n' > "$W/ex2.txt"; EXC="$W/ex2.txt" run 0; expect "제외 목록에 이유가 없으면 FAIL" FAIL "이유가 없다"
mk deploy; mkschema; echo '{"a":"1"}' > "$W/$BC/examples/Bar.json"; mkdir -p "$W/$BC/.git"; run 0; expect "스키마 없는 예시는 모르는 대상으로 FAIL" FAIL "모르는 대상: boundary-contracts/examples/Bar.json"
unset EXC

echo "== 1 버전표"
mk survey-service release-gate model-lab ops-feedback question-authoring synthetic-data turn-engine model-runtime kiosk-frontend admin-console; run 1 CHECK_ALL_VERSIONS_CMD=true; expect "버전표 일치(대리 명령 성공)" PASS "검증됨 10/10"
run 1 CHECK_ALL_VERSIONS_CMD=false; expect "버전표 불일치(대리 명령 실패)는 FAIL" FAIL

echo "== 2 예시 키 순서"
mk $BC; mkschema; echo '{"a":"1","b":[{"x":1,"y":2}]}' > "$W/$BC/examples/Foo.json"; run 2; expect "올바른 순서는 PASS" PASS "검증됨 1/1"
echo '{"b":[{"x":1,"y":2}],"a":"1"}' > "$W/$BC/examples/Foo.json"; run 2; expect "최상위 순서가 다르면 FAIL" FAIL "Foo.json"
printf '{\n  "a": "1",\n  "b": [\n    {\n      "y": 2,\n      "x": 1\n    }\n  ]\n}\n' > "$W/$BC/examples/Foo.json"; run 2; expect "중첩 객체 순서가 다르면 FAIL(줄 번호)" FAIL "Foo.json:5"

echo '{"b":[],"a":"1"}' > "$W/$BC/examples/Foo.json"; printf '' > "$W/ordered.txt"; run 2; expect "목록에 없는 스키마의 예시는 대상 아님(FAIL 아님)" PASS "모델 생성 출력이 아님"
printf 'Foo\n' > "$W/ordered.txt"; run 2; expect "대상 목록 항목에 이유가 없으면 FAIL" FAIL "이유가 없다"
echo "Nope | x" > "$W/ordered.txt"; run 2; expect "목록의 스키마가 없으면 FAIL" FAIL "가 boundary-contracts 에 없다"

echo "== 3 완화 정책"
mk deploy
printf '#!/bin/sh\necho "[\\"allOf->anyOf\\"]"\n' > "$W/py-ok"; chmod +x "$W/py-ok"
printf '#!/bin/sh\necho "[\\"allOf@/values[0]:unsupported\\"]"\n' > "$W/py-bad"; chmod +x "$W/py-bad"
run 3 CHECK_ALL_MR_PY="$W/py-ok"; expect "허용 집합 안이면 PASS" PASS
run 3 CHECK_ALL_MR_PY="$W/py-bad"; expect "규칙을 빼면 FAIL" FAIL
run 3 CHECK_ALL_MR_PY="$W/없음"; expect "venv 가 없으면 SKIP(검증 안 함 1)" SKIP "검증 안 함 1"

echo "== 4 삭제된 이름"
mk deploy; mkdir -p "$W/deploy/app"; echo 'x = 1' > "$W/deploy/app/a.py"; run 4; expect "깨끗하면 PASS" PASS
echo 'v = "prompt-3"' > "$W/deploy/app/a.py"; run 4; expect "prompt-3 잔존은 FAIL" FAIL "deploy/app/a.py:1"
printf 'from turn_engine import (\n    plan,\n)\n' > "$W/deploy/app/a.py"; run 4; expect "제거된 turn_engine 함수 import 는 FAIL" FAIL "deploy/app/a.py:1"
echo 'r = "PARSER"' > "$W/deploy/app/a.py"; run 4; expect "v1 열거값은 FAIL" FAIL
echo '# prompt-3 은 제거됨' > "$W/deploy/app/a.py"; run 4; expect "주석의 설명은 통과" PASS

echo "== 5 박은 계약 문자열"
mk deploy; mkdir -p "$W/deploy/app"; echo 'p = {"pipeline_schema_version": SCHEMA_VERSION}' > "$W/deploy/app/a.py"; run 5; expect "상수를 쓰면 PASS" PASS
echo 'p = {"pipeline_schema_version": "1.3"}' > "$W/deploy/app/a.py"; run 5; expect "\"1.\" 값을 박으면 FAIL" FAIL "deploy/app/a.py:1"
mkdir -p "$W/deploy/tests"; rm "$W/deploy/app/a.py"; echo 'p = {"pipeline_schema_version": "1.3"}' > "$W/deploy/tests/t.py"; run 5; expect "시험 픽스처는 대상 아님" PASS

echo "== 6 설정 인라인 비밀"
mk deploy; mkdir -p "$W/deploy/config"; printf 'api_key: MY_ENV_KEY\nauth:\n  token: {env: MY_TOKEN}\n  max_tokens: 5\n' > "$W/deploy/config/a.yaml"; run 6; expect "환경 변수 이름·env 형식은 PASS" PASS
printf 'auth:\n  password: hunter2hunter2\n' > "$W/deploy/config/a.yaml"; run 6; expect "인라인 값은 FAIL(줄 번호)" FAIL "deploy/config/a.yaml:2"
grep -q hunter2 <<<"$OUT" && { echo "  FAIL 값이 출력에 나왔다"; FAILS=$((FAILS+1)); } || echo "  ok   값은 출력하지 않는다"
echo '{"private_key": "abc"}' > "$W/deploy/config/b.json"; rm "$W/deploy/config/a.yaml"; run 6; expect "json 도 본다" FAIL "deploy/config/b.json"

echo "== 7 compose 비밀"
mk deploy; printf 'services:\n  web:\n    image: x\n    environment:\n      SVC_TOKEN_FILE: /run/secrets/t\n      LOG: debug\n' > "$W/deploy/compose.yaml"; run 7; expect "NAME_FILE 경로는 PASS" PASS "검증됨 1/1"
printf 'services:\n  web:\n    image: x\n    environment:\n      SVC_TOKEN: s3cretvalue\n' > "$W/deploy/compose.yaml"; run 7; expect "직접 준 값은 FAIL" FAIL "deploy/compose.yaml:5"
grep -q s3cretvalue <<<"$OUT" && { echo "  FAIL 값이 출력에 나왔다"; FAILS=$((FAILS+1)); } || echo "  ok   값은 출력하지 않는다"
printf 'services:\n  web:\n    image: x\n    environment:\n      - DB_PASSWORD=pw123456\n' > "$W/deploy/compose.yaml"; run 7; expect "리스트 형식도 FAIL" FAIL
printf 'services:\n  web:\n    image: x\n    env_file: [./e.env]\n' > "$W/deploy/compose.yaml"; printf 'API_KEY=zzzz\n' > "$W/deploy/e.env"; run 7; expect "env_file 안의 비밀 값은 FAIL" FAIL "e.env"

echo "== 8 시험 수집"
mk deploy; mkdir -p "$W/deploy/scripts"; echo 'true' > "$W/deploy/scripts/test-a.sh"; run 8; expect "deploy 시험 스크립트 수집은 PASS" PASS
echo 'if [' > "$W/deploy/scripts/test-a.sh"; run 8; expect "문법 오류는 FAIL" FAIL
mk admin-console; run 8; expect "node_modules 없으면 SKIP(검증 안 함)" SKIP "검증 안 함 1"
mkdir -p "$W/admin-console/node_modules"; cat > "$W/admin-console/package.json" <<'J'
{"scripts":{"test":"node -e \"console.log('tests 3')\""}}
J
run 8; expect "npm test 통과는 PASS" PASS "검증됨 1/1"
echo '{"scripts":{"test":"node -e \"process.exit(1)\""}}' > "$W/admin-console/package.json"; run 8; expect "npm test 실패는 FAIL" FAIL
mk model-lab; run 8; expect ".venv 없으면 SKIP" SKIP "검증 안 함 1"
if [ -n "$PYT" ]; then
  mkdir -p "$W/model-lab/.venv/bin" "$W/model-lab/tests"; printf '#!/bin/sh\nexec %s "$@"\n' "$PYT" > "$W/model-lab/.venv/bin/python"; chmod +x "$W/model-lab/.venv/bin/python"
  printf 'def test_a():\n    pass\n' > "$W/model-lab/tests/test_a.py"; run 8; expect "시험이 수집되면 PASS" PASS "검증됨 1/1"
  printf 'import 없는_모듈\ndef test_a():\n    pass\n' > "$W/model-lab/tests/test_a.py"; run 8; expect "수집 오류는 FAIL" FAIL "model-lab/"
else echo "  skip pytest 가 있는 venv 가 없어 py 수집 시험을 건너뛴다"; fi

echo "== 9 README"
mk deploy; run 9; expect "필수 절이 다 있으면 PASS" PASS
printf '# x\n\n소개.\n\n## 1. 전체 속의 위치\n## 2. 구조\n' > "$W/deploy/README.md"; run 9; expect "필수 절이 빠지면 FAIL" FAIL "필수 절 없음: 실행 방법"
rm "$W/deploy/README.md"; run 9; expect "README 가 없으면 FAIL" FAIL "README.md:1"

echo
[ $FAILS = 0 ] && echo "통과: 자체 시험 $N건 + 값 비출력 확인" || { echo "실패: $FAILS건 (시험 $N건)"; exit 1; }
