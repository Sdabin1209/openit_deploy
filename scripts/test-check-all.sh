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
# mk <이름>... : 임시 워크스페이스 $W 에 영역(.git 과 올바른 README 포함)을 만든다
mk() { W="$(mktemp -d -p "$T")"; mkdir -p "$W/head/shared"; cp "$HERE/../../head/shared/areas.json" "$W/head/shared/areas.json"; for a in "$@"; do mkdir -p "$W/$a/.git"; done; }
# run <규칙번호> [환경...] : 출력을 $OUT, 종료 코드를 $RC 에
run() { local r=$1; shift; OUT=$(env CHECK_ALL_WORKSPACE="$W" CHECK_ALL_ONLY="$r" CHECK_ALL_EXCLUDE="${EXC:-/dev/null}" CHECK_ALL_ORDERED="${ORD:-$W/ordered.txt}" "$@" bash "$HERE/check-all.sh" 2>&1); RC=$?; }
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
run 3 CHECK_ALL_MR_PY="$W/없음"; expect "SKIP 이유에 해결 방법이 붙는다" SKIP "docs/SETUP.md F절"

echo "== 4 정본에 없는 이름 (ast 로 읽는다)"
truth(){ mkdir -p "$W/model-runtime/src/model_runtime" "$W/turn-engine/turn_engine" "$W/boundary-contracts/boundary_contracts"
  printf 'def _u7(role, i):\n    return ""\n\n\n_USER = {"prompt-7": _u7}\n' > "$W/model-runtime/src/model_runtime/prompts.py"
  printf '__all__ = ["validate_extraction", "ENGINE_VERSION"]\n' > "$W/turn-engine/turn_engine/__init__.py"; : > "$W/turn-engine/turn_engine/validation.py"
  printf 'PIPELINE_SCHEMA_VERSION = "9.9"\n' > "$W/boundary-contracts/boundary_contracts/schemas_api.py"; }
mk deploy; truth; mkdir -p "$W/deploy/app"; echo 'x = 1' > "$W/deploy/app/a.py"; run 4; expect "깨끗하면 PASS" PASS
echo 'v = "prompt-7"' > "$W/deploy/app/a.py"; run 4; expect "정본에 있는 템플릿은 PASS" PASS
echo 'v = "prompt-3"' > "$W/deploy/app/a.py"; run 4; expect "정본에 없는 템플릿(문자열 상수)은 FAIL" FAIL "deploy/app/a.py:1"
printf 'from turn_engine import (\n    validate_extraction,\n    plan,\n)\n' > "$W/deploy/app/a.py"; run 4; expect "공개 API 에 없는 turn_engine 이름 import 는 FAIL" FAIL "deploy/app/a.py:1"
printf 'from turn_engine import validate_extraction as v\n' > "$W/deploy/app/a.py"; run 4; expect "공개 API 의 이름은 별칭이 있어도 PASS" PASS
printf 'from turn_engine import validation\n' > "$W/deploy/app/a.py"; run 4; expect "하위 모듈 import 는 합법(파일 존재)" PASS
printf 'from turn_engine.validation import anything\n' > "$W/deploy/app/a.py"; run 4; expect "하위 모듈에서 가져오기는 PASS" PASS
printf 'from turn_engine.gone import x\n' > "$W/deploy/app/a.py"; run 4; expect "없는 하위 모듈은 FAIL" FAIL "deploy/app/a.py:1"
printf 'import turn_engine as te\nte.validate_extraction()\n' > "$W/deploy/app/a.py"; run 4; expect "별칭 import 의 공개 속성은 PASS" PASS
printf 'import turn_engine as te\nte.plan()\n' > "$W/deploy/app/a.py"; run 4; expect "별칭 import 의 없는 속성은 FAIL(줄)" FAIL "deploy/app/a.py:2"
printf 'import importlib\nimportlib.import_module("turn_engine.gone")\n' > "$W/deploy/app/a.py"; run 4; expect "importlib 의 없는 하위 모듈은 FAIL" FAIL "deploy/app/a.py:2"
printf '__import__("turn_engine.gone")\n' > "$W/deploy/app/a.py"; run 4; expect "__import__ 의 없는 하위 모듈은 FAIL" FAIL "deploy/app/a.py:1"
printf 'from .turn_engine import plan\n' > "$W/deploy/app/a.py"; run 4; expect "상대 import 는 보지 않는다" PASS
echo '# prompt-3 은 제거됨' > "$W/deploy/app/a.py"; run 4; expect "주석의 설명은 통과" PASS
printf 'v = "prompt-" + "3"\n' > "$W/deploy/app/a.py"; run 4; expect "조합한 이름은 보지 못한다고 명시한다" PASS "조합"
printf 'prompts:\n  - prompt-3\n' > "$W/deploy/app/c.yaml"; run 4; expect "YAML 의 없는 템플릿도 파서로 읽어 FAIL" FAIL "deploy/app/c.yaml"
rm "$W/deploy/app/c.yaml"
printf '_USER = {"prompt-7": missing_fn}\n' > "$W/model-runtime/src/model_runtime/prompts.py"; run 4; expect "정본의 키에 대응 함수가 없으면 FAIL(정본이 거짓)" FAIL "대응하는 템플릿 함수"
printf 'def f(r, i):\n    return ""\n\n\n_USER: dict = dict(**{})\n' > "$W/model-runtime/src/model_runtime/prompts.py"; run 4; expect "정본을 읽지 못하는 모양이면 SKIP 이 아니라 FAIL" FAIL "dict 리터럴"
printf 'def f(r, i):\n    return ""\n\n\n_USER: dict = dict(a=f)\n_USER |= {"b": f}\n' > "$W/model-runtime/src/model_runtime/prompts.py"; run 4; expect "AnnAssign·dict(...)·|= 를 읽는다" PASS
rm -rf "$W/model-runtime"; echo 'x = 1' > "$W/deploy/app/a.py"; run 4; expect "정본을 못 읽으면 통과로 치지 않고 FAIL" FAIL "읽지 못했다"
mk deploy; truth; echo '{"areas": []}' > "$W/head/shared/areas.json"; run 4; expect "영역이 0개면 PASS 가 아니라 FAIL" FAIL "0개"
rm "$W/head/shared/areas.json"; run 4; expect "areas.json 이 없으면 FAIL" FAIL "0개"
run 0; expect "areas.json 이 없으면 규칙 0 도 FAIL" FAIL "0개"

echo "== 5 박은 계약 문자열 (ast 와 파서)"
mk deploy; truth; mkdir -p "$W/deploy/app"; echo 'p = {"pipeline_schema_version": SCHEMA_VERSION}' > "$W/deploy/app/a.py"; run 5; expect "상수를 쓰면 PASS" PASS
echo 'p = {"pipeline_schema_version": "9.9"}' > "$W/deploy/app/a.py"; run 5; expect "계약의 현재 값과 같으면 PASS" PASS
echo 'p = {"pipeline_schema_version": "1.3"}' > "$W/deploy/app/a.py"; run 5; expect "계약의 현재 값과 다른 값을 박으면 FAIL" FAIL "deploy/app/a.py:1"
echo 'f(pipeline_schema_version="1.3", other="x")' > "$W/deploy/app/a.py"; run 5; expect "kwarg 로 박아도 FAIL" FAIL "deploy/app/a.py:1"
echo 'p = dict(pipeline_schema_version="1.3")' > "$W/deploy/app/a.py"; run 5; expect "dict(...) 로 박아도 FAIL" FAIL "deploy/app/a.py:1"
printf 'x: str = 1\npipeline_schema_version: str = "1.3"\n' > "$W/deploy/app/a.py"; run 5; expect "AnnAssign 로 박아도 FAIL" FAIL "deploy/app/a.py:2"
echo 'd["pipeline_schema_version"] = "1.3"' > "$W/deploy/app/a.py"; run 5; expect "키 대입으로 박아도 FAIL" FAIL "deploy/app/a.py:1"
echo 'f(pipeline_schema_version, "1.3")' > "$W/deploy/app/a.py"; run 5; expect "쉼표 뒤 다음 인자를 값으로 읽지 않는다(오탐 없음)" PASS
printf 'pipeline_schema_version: "1.3"\n' > "$W/deploy/app/c.yaml"; rm "$W/deploy/app/a.py"; run 5; expect "YAML 값은 파서로 읽어 FAIL" FAIL "deploy/app/c.yaml"
rm "$W/deploy/app/c.yaml"; printf '{"pipeline_schema_version": "9.9"}' > "$W/deploy/app/c.json"; run 5; expect "JSON 의 현재 값은 PASS" PASS
printf 'x = ' > "$W/deploy/app/bad.py"; run 5; expect "파싱하지 못한 파일은 통과가 아니라 SKIP" SKIP "파싱하지 못했다"
rm "$W/deploy/app/bad.py"
mkdir -p "$W/deploy/tests"; echo 'p = {"pipeline_schema_version": "1.3"}' > "$W/deploy/tests/t.py"; run 5; expect "시험 픽스처는 대상 아님" PASS
rm -rf "$W/boundary-contracts"; mkdir -p "$W/deploy/app"; echo 'x = 1' > "$W/deploy/app/a.py"; run 5; expect "정본을 못 읽으면 FAIL" FAIL "읽지 못했다"

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

echo "== 11 compose 마운트 원본이 실제 파일"
mk deploy; mkdir -p "$W/deploy/config"; printf 'services:\n  j:\n    image: x\n    volumes:\n      - ${J:-./config/job.yaml}:/config/job.yaml:ro\n' > "$W/deploy/compose.yaml"
run 11; expect "원본 파일이 없으면 FAIL" FAIL "가 없다"
mkdir "$W/deploy/config/job.yaml"; run 11; expect "원본이 (Docker 가 만든) 디렉터리면 FAIL" FAIL "디렉터리다"
rmdir "$W/deploy/config/job.yaml"; echo "a: 1" > "$W/deploy/config/job.yaml"; run 11; expect "실제 파일이면 PASS" PASS "검증됨 1/1"
printf 'services:\n  j:\n    image: x\n    volumes:\n      - data:/data\n      - ./dir:/d\n' > "$W/deploy/compose.yaml"; run 11; expect "이름 있는 볼륨·확장자 없는 경로는 대상 아님" PASS

echo "== record-e2e.sh (정본에 한 줄 더하기)"
RF="$T/E2E_RESULTS.md"; cp "$ROOT/docs/E2E_RESULTS.md" "$RF"
printf -- '-- 결과: FAIL 0, SKIP 0, PASS 11 / 규칙 11개, 소요 2.5s\n' > "$T/ca.out"
printf '== 요약 (단계 1~8)\n     1 REAL      a\n     2 BLOCKED   b\n     3 TEST-SUB  c\n    4x BLOCKED   d\n\n-- 9단계 및 준비 검사\n   PASS 40 / FAIL 0\nE2E 결과: 실행한 검사 전부 통과 (x)\n' > "$T/sum.txt"
rec() { N=$((N+1)); local want=$1 desc=$2; shift 2; OUT=$(bash "$HERE/record-e2e.sh" --file "$RF" "$@" 2>&1); RC=$?; local good=0; { [ "$want" = ok ] && [ $RC = 0 ]; } && good=1; { [ "$want" = fail ] && [ $RC != 0 ]; } && good=1; if [ $good = 1 ]; then echo "  ok   $desc"; else echo "  FAIL $desc (rc=$RC)"; echo "$OUT" | head -3 | sed 's/^/       /'; FAILS=$((FAILS+1)); fi; }
rec ok "로그에서 숫자를 파싱해 한 줄을 더한다" --when "2026-01-01 00:00" "$T/ca.out" "$T/sum.txt"
N=$((N+1)); if grep -qE '^\| 2026-01-01 00:00 \| [0-9a-f]+(\+dirty)? \| .* \| 전체 \| 40 \| 0 \| 0 \| 0/0/11 \| 2 \| 1 \|' "$RF"; then echo "  ok   더한 줄의 PASS/FAIL/check-all/BLOCKED/TEST-SUB 값이 로그와 같다"; else echo "  FAIL 더한 줄의 값이 로그와 다르다"; FAILS=$((FAILS+1)); fi
B=$(md5sum < "$RF"); rec fail "check-all 요약이 없는 로그는 실패" "$T/sum.txt"; N=$((N+1)); [ "$B" = "$(md5sum < "$RF")" ] && echo "  ok   실패하면 파일을 바꾸지 않는다" || { echo "  FAIL 실패했는데 파일이 바뀌었다"; FAILS=$((FAILS+1)); }
printf 'garbage\n' > "$T/bad.txt"; rec fail "PASS 줄을 파싱하지 못하면 실패" "$T/ca.out" "$T/bad.txt"
rec fail "--manual 은 출처 없이는 실패" --manual --commit abc1234 --mode 전체 --pass 1 --fail 0 --exit 0 --ca-fail 0 --ca-skip 0 --ca-pass 1
rec ok "--manual 은 출처를 '수동 입력'으로 표시해 더한다" --manual --source "시험" --commit abc1234 --mode 전체 --pass 1 --fail 0 --exit 0 --ca-fail 0 --ca-skip 0 --ca-pass 1 --when "2026-01-02 00:00"
N=$((N+1)); grep -q '수동 입력: 시험' "$RF" && echo "  ok   수동 입력 표시" || { echo "  FAIL 수동 입력 표시가 없다"; FAILS=$((FAILS+1)); }
# 환경 칸: hostname 으로 gpu-dev 를 알아본다(WSL2 위의 gpu-dev 가 '이 PC (WSL2)' 로 적히던 버그). 원문 hostname 은 기록에 쓰지 않는다
envrow() { # envrow <when> <기대 환경 칸> <설명> [환경 변수 ...]  (DEPLOY_ENV_NAME, E2E_ENV 는 지정한 것만 남긴다)
  local when=$1 want=$2 desc=$3; shift 3; N=$((N+1))
  env -u DEPLOY_ENV_NAME -u E2E_ENV RECORD_E2E_PROC_VERSION=microsoft "$@" bash "$HERE/record-e2e.sh" --file "$RF" --manual --source "환경 시험" --commit abc1234 --mode 전체 --pass 1 --fail 0 --exit 0 --ca-fail 0 --ca-skip 0 --ca-pass 1 --when "$when" >/dev/null 2>&1
  if grep -qF "| $when | abc1234 | $want | 전체 |" "$RF"; then echo "  ok   $desc"; else echo "  FAIL $desc (기대: $want)"; FAILS=$((FAILS+1)); fi
}
envrow "2026-02-01 00:00" "gpu-dev" "WSL2 위에서도 hostname gpu-dev 는 gpu-dev 로 적는다" RECORD_E2E_HOSTNAME=gpu-dev
envrow "2026-02-01 00:01" "gpu-dev" "gpu-dev-01 처럼 접미사가 붙어도 gpu-dev" RECORD_E2E_HOSTNAME=GPU-DEV-01
envrow "2026-02-01 00:02" "이 PC (WSL2)" "다른 hostname 의 WSL2 는 이 PC (WSL2)" RECORD_E2E_HOSTNAME=my-laptop
N=$((N+1)); if grep -q 'my-laptop' "$RF"; then echo "  FAIL hostname 원문이 기록에 들어갔다"; FAILS=$((FAILS+1)); else echo "  ok   hostname 원문은 기록에 쓰지 않는다"; fi
envrow "2026-02-01 00:03" "서버-A" "DEPLOY_ENV_NAME 이 있으면 그것을 쓴다(hostname 보다 우선)" RECORD_E2E_HOSTNAME=gpu-dev DEPLOY_ENV_NAME=서버-A
envrow "2026-02-01 00:04" "직접 지정" "E2E_ENV 가 가장 우선" RECORD_E2E_HOSTNAME=gpu-dev DEPLOY_ENV_NAME=서버-A E2E_ENV=직접\ 지정

echo
[ $FAILS = 0 ] && echo "통과: 자체 시험 $N건 + 값 비출력 확인" || { echo "실패: $FAILS건 (시험 $N건)"; exit 1; }
