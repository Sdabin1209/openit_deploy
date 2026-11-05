#!/usr/bin/env python3
"""e2e.sh 정적 순서 대조('쓰기 전에 만들어짐'): 단계가 읽는 파일·비밀·잠금이 그 단계보다 앞에서 만들어지는지 본다. 실행 없이 e2e.sh 를 읽어서 찾는다(4차 E2E 뒤 실제로 났다: deploy 도구 이미지 빌드가 임시 잠금을 만들기 전에 그 잠금을 읽었다).
(1) 스크립트가 읽는 산출물: 각 스크립트의 코드 줄(주석 제외)에 DEPLOY_LOCK / DEPLOY_REGISTRY_ENV / SECRETS_DIR 가 나오면 그 스크립트를 부르는 e2e.sh 의 첫 줄은 산출물을 만드는 줄보다 뒤여야 한다.
(2) $W 아래 파일: 만드는 줄(리다이렉션·cp·함수 안 생성 + 그 함수를 부르는 chk)이 최상위 줄 사용보다 앞이다. 변이: 순서를 바꾸면 실패한다. 사용: python3 scripts/test_e2e_sh_order.py"""
import pathlib, re, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
S = ROOT / "scripts"


def code(text: str):
    return [re.sub(r"\s#.*$", "", l) if not l.lstrip().startswith("#") else "" for l in text.splitlines()]


def first(lines, pat, start=0):
    r = re.compile(pat)
    for i in range(start, len(lines)):
        if r.search(lines[i]): return i + 1
    return None


def reader_scripts(var):
    out = set()
    for f in S.glob("*.sh"):
        if f.name in ("lib.sh", "e2e.sh") or f.name.startswith("test-"): continue
        if any(var in l for l in code(f.read_text(encoding="utf-8"))): out.add(f.name)
    return out


# 산출물: (이름, 만드는 줄 패턴, 만드는 일을 하는 스크립트(읽기 대상에서 뺀다))
ARTIFACTS = [
    ("DEPLOY_LOCK", r'> "\$DEPLOY_LOCK"', set()),
    ("DEPLOY_REGISTRY_ENV", r'scripts/registry\.sh" up', {"registry.sh"}),
    ("SECRETS_DIR", r'gen-secrets\.sh" --test-fixtures "\$SECRETS_DIR"', {"gen-secrets.sh"}),
]
# $W 파일: (파일, 만드는 줄 패턴)
W_FILES = [
    ("tool-image.txt", r'> \$W/tool-image\.txt'),
    ("pki/root_ca.crt", r'chk "추론 서버용 일회용 TLS 토큰'),
    ("trust.crt", r'chk "추론 서버용 일회용 TLS 토큰'),
    ("tls.ott", r'chk "추론 서버용 일회용 TLS 토큰'),
    ("gateway-ca.crt", r'export-gateway-ca\.sh" --project'),
]


# 순서쌍(앞, 뒤, 이유): 뒤 패턴의 첫 최상위 줄은 앞 패턴의 첫 최상위 줄보다 뒤여야 한다
ORDER_PAIRS = [
    (r'scripts/up\.sh" "\$PROJECT"', r'chk "추론 서버 기동', "추론 서버가 읽는 영역 게이트웨이 노출 선언(state/gateways)은 up.sh 가 이미지 라벨에서 만든다"),
    (r'scripts/up\.sh" "\$PROJECT"', r'scripts/idp-test-users\.sh" "\$PROJECT"', "사용자 등록 잡은 identity 가 뜬 뒤 돈다"),
    (r'gen-secrets\.sh" --test-fixtures', r'scripts/up\.sh" "\$PROJECT"', "비밀 파일은 기동 전에 있다"),
    (r'scripts/publish-images\.sh"', r'scripts/up\.sh" "\$PROJECT"', "digest 잠금은 기동 전에 있다"),
    (r'export-gateway-ca\.sh" --project', r'chk "추론 서버 기동', "추론 서버가 믿을 게이트웨이 CA 는 기동 전에 꺼내 둔다"),
    (r'scripts/build-tool-image\.sh', r'scripts/e2e_steps\.py" --forms-dir', "시험 드라이버(exec_py)가 쓰는 deploy 도구 이미지는 단계 실행 전에 있다"),
]


def function_ranges(lines):
    """함수 정의 줄 범위. 한 줄 정의(줄 끝이 })는 그 줄, 여러 줄 정의는 첫 번째 '}' 만 있는 줄까지(중괄호 개수는 ${..}·템플릿 때문에 믿을 수 없다)."""
    rng = []
    for i, l in enumerate(lines):
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\(\) \{", l):
            if l.rstrip().endswith("}"): rng.append((i + 1, i + 1)); continue
            j = next((k for k in range(i + 1, len(lines)) if lines[k].rstrip() == "}"), len(lines) - 1)
            rng.append((i + 1, j + 1))
    return rng


def violations(e2e_text: str, readers_of=reader_scripts):
    lines = code(e2e_text); out = []
    fr = function_ranges(lines)
    top = lambda i: not any(a <= i <= b for a, b in fr)   # 함수 본문(cleanup 등)은 정의 줄이 아니라 부르는 때 돈다: 최상위 줄만 순서를 본다
    for var, creator, creators in ARTIFACTS:
        made = first(lines, creator)
        if made is None: out.append(f"{var}: 만드는 줄이 e2e.sh 에 없다({creator})"); continue
        for name in sorted(readers_of(var) - creators):
            use = next((i for i, l in enumerate(lines, 1) if top(i) and re.search(r'scripts/' + re.escape(name) + r'\b', l)), None)
            if use is not None and use < made: out.append(f"e2e.sh:{use}: {name} 가 {var} 를 읽는데 {var} 는 e2e.sh:{made} 에서 만들어진다")
    for before, after, why in ORDER_PAIRS:
        b = next((i for i, l in enumerate(lines, 1) if top(i) and re.search(before, l)), None)
        a = next((i for i, l in enumerate(lines, 1) if top(i) and re.search(after, l)), None)
        if b is None or a is None: out.append(f"순서쌍 패턴을 e2e.sh 에서 찾지 못했다: {before!r} -> {after!r}"); continue
        if a < b: out.append(f"e2e.sh:{a}: {why} (앞 줄 e2e.sh:{b})")
    for fname, creator in W_FILES:
        made = first(lines, creator)
        if made is None: out.append(f"$W/{fname}: 만드는 줄이 없다({creator})"); continue
        pat = r'\$W/' + re.escape(fname)
        for i, l in enumerate(lines, 1):
            if i < made and re.search(pat, l) and not any(a <= i <= b for a, b in fr) and not re.search(r'>\s*"?' + pat, l):
                out.append(f"e2e.sh:{i}: $W/{fname} 를 쓰는데 만드는 줄은 e2e.sh:{made} 이다")
    return out


class T(unittest.TestCase):
    def test_e2e_sh_order(self):
        self.assertEqual(violations((S / "e2e.sh").read_text(encoding="utf-8")), [])

    def test_mutation_tool_image_before_lock_is_not_a_reader_problem_but_swapped_order_is_caught(self):
        t = (S / "e2e.sh").read_text(encoding="utf-8").splitlines()
        i = next(k for k, l in enumerate(t) if '> "$DEPLOY_LOCK"' in l); j = next(k for k, l in enumerate(t) if 'scripts/check-compose.sh' in l)
        t[i], t[j] = t[j], t[i]   # 잠금을 만드는 줄과 잠금을 읽는 스크립트의 줄을 맞바꾼다
        self.assertTrue(violations("\n".join(t)))

    def test_mutation_reader_added_before_creation(self):
        t = (S / "e2e.sh").read_text(encoding="utf-8").splitlines()
        k = next(i for i, l in enumerate(t) if l.startswith("must bash") and "prepare-host.sh\" venv" in l)
        t.insert(k + 1, 'chk "x" bash "$DEPLOY_ROOT/scripts/publish-images.sh"')
        self.assertTrue(violations("\n".join(t)))


if __name__ == "__main__":
    unittest.main()
