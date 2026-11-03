#!/usr/bin/env python3
"""정적 시험: E2E 사전 점검의 단독 시험은 깨끗한 환경에서 돈다(E2E 가 내보낸 DEPLOY_LOCK·SECRETS_DIR·COMPOSE_EXTRA 가 새면 안 된다).
왜: 분리 배치 플레이북 시험은 단독으로 통과하는데 E2E 사전 점검에서만 실패했다. 원인은 E2E 의 임시 DEPLOY_LOCK 이 새어 들어간 것이다(재현·확인함)."""
import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AMBIENT = ("DEPLOY_LOCK", "SECRETS_DIR", "COMPOSE_EXTRA", "COMPOSE_PROJECT_NAME", "STEP_CA_PORT", "DEPLOY_REGISTRY_ENV")


class T(unittest.TestCase):
    def test_precheck_loop_uses_env_i(self):
        s = (ROOT / "scripts/e2e.sh").read_text()
        self.assertRegex(s, r'chk "\$_d" env -i "\$\{_cleanenv\[@\]\}" bash -c "\$_c"')

    def test_tests_that_use_ambient_vars_set_them_themselves(self):
        """단독 시험(self-checks.list 등록)이 위 변수를 읽으면 스스로 정하거나(대입·export) 지워야(unset) 한다."""
        listed = set(re.findall(r"scripts/(test[-_][\w.-]+\.sh)", (ROOT / "scripts/self-checks.list").read_text()))
        bad = []
        for name in sorted(listed):
            p = ROOT / "scripts" / name
            if not p.exists():
                continue
            s = p.read_text()
            for v in AMBIENT:
                if re.search(r"\$\{?%s\b" % v, s) and not re.search(r"(^|[\s;])(export\s+)?%s=|unset\s+[^\n]*\b%s\b|export\s+[^\n]*\b%s=" % (v, v, v), s, re.M):
                    bad.append(f"{name}: {v}")
        self.assertEqual(bad, [], "밖에서 온 값을 그대로 읽는 단독 시험")


if __name__ == "__main__":
    unittest.main()
