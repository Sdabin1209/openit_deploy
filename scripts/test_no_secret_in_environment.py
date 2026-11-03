#!/usr/bin/env python3
"""D84 정적 검사: 비밀이 컨테이너 프로세스의 환경 변수로 들어가는 구성을 잡는다(3차 E2E: Keycloak 래퍼가 파일을 읽어 export 해 /proc/1/environ 에 값이 남았다. 동적 점검 check-secrets-hidden 이 E2E 에서야 잡았다).
(1) compose 서비스의 environment 키 중 비밀 이름(PASSWORD·SECRET·TOKEN·PRIVATE_KEY·API_KEY)은 `_FILE` 로 끝나고 값이 /run/secrets/ 아래 경로여야 한다(예외 표에 이유와 함께 적은 것만 면제).
(2) config/ 아래 셸(엔트리포인트 래퍼)이 비밀 이름의 변수를 export 하지 않는다. 사용: python3 scripts/test_no_secret_in_environment.py (PyYAML 필요)"""
import pathlib, re, unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRET_NAME = re.compile(r"(PASSWORD|SECRET|TOKEN|PRIVATE_KEY|API_KEY)")
EXEMPT = {   # (서비스, 변수): 이유
    ("gateway", "GATEWAY_PUBLIC_TLS_PORT"): "이름에 비밀 단어가 없다(예시 아님: 안 걸린다)",
}


def services():
    out = {}
    for f in ("compose.yaml", "compose.monitoring.yaml", "compose.backup-target.yaml", "compose.inference.yaml", "compose.registry.yaml"):
        p = ROOT / f
        if p.exists(): out.update({f"{f}:{k}": v for k, v in (yaml.safe_load(p.read_text(encoding="utf-8")).get("services") or {}).items()})
    return out


class T(unittest.TestCase):
    def test_compose_environment_has_no_secret_values(self):
        bad = []
        for name, svc in services().items():
            env = svc.get("environment") or {}
            if isinstance(env, list): env = dict(x.split("=", 1) if "=" in x else (x, "") for x in env)
            for k, v in env.items():
                if not SECRET_NAME.search(k) or (name.split(":")[1], k) in EXEMPT: continue
                if not (k.endswith("_FILE") and str(v).startswith("/run/secrets/")): bad.append(f"{name}.{k}={str(v)[:40]}")
        self.assertEqual(bad, [], "비밀 이름의 환경 변수는 *_FILE 이고 /run/secrets/ 경로여야 한다(값 직접 금지, D84)")

    def test_entrypoint_scripts_do_not_export_secrets(self):
        bad = []
        for f in sorted((ROOT / "config").rglob("*.sh")):
            for i, l in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if l.lstrip().startswith("#"): continue
                if re.search(r"\bexport\s+\w*(PASSWORD|SECRET|TOKEN|PRIVATE_KEY|API_KEY)\w*\b", l): bad.append(f"{f.relative_to(ROOT)}:{i}")
        self.assertEqual(bad, [], "엔트리포인트가 비밀을 환경 변수로 옮긴다(프로세스 환경에 값이 남는다)")

    def test_detects_the_old_keycloak_wrapper_pattern(self):
        # 예전 래퍼는 `export X; X=$(…)` 두 문장이었다: 대입 문장도 같이 잡는다
        self.assertTrue(re.search(r"\bexport\s+\w*(PASSWORD|SECRET)\w*\b", 'export KC_DB_PASSWORD; KC_DB_PASSWORD=$(rd x)'))
        self.assertTrue(re.search(r"\bexport\s+\w*(PASSWORD|SECRET)\w*\b", 'export KC_DB_PASSWORD="$(cat f)"'))


if __name__ == "__main__":
    unittest.main()
