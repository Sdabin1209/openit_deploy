#!/usr/bin/env python3
"""idp_users_config.py 시험: accounts.test.conf 에서 만든 설정이 계약 IdentityUsersConfig 를 통과하고, 암호 값은 설정에 없으며 암호 파일은 모드 640 으로 복사된다. 변이: 모르는 역할 그룹, 암호 파일 없음은 종료 1.
사용: python3 scripts/test_idp_users_config.py"""
import json, os, pathlib, stat, sys, tempfile, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import idp_users_config as C  # noqa: E402


class T(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup); self.d = pathlib.Path(self.t.name)
        (self.d / "pw").mkdir(); self.acc = self.d / "acc.conf"

    def run_cfg(self, text, users=()):
        self.acc.write_text(text)
        for u in users: (self.d / "pw" / f"idp-test-{u}-password").write_text("secret-" + u + "\n")
        return C.main(["--accounts", str(self.acc), "--passwords", str(self.d / "pw"), "--secrets-out", str(self.d / "so"), "--out", str(self.d / "cfg.json")])

    def test_real_accounts_file_passes_the_contract(self):
        text = (ROOT / "test/gateway-oidc/accounts.test.conf").read_text()
        names = [l.split()[0] for l in text.splitlines() if l.split() and not l.startswith("#")]
        self.assertEqual(self.run_cfg(text, names), 0)
        cfg = json.loads((self.d / "cfg.json").read_text()); self.assertEqual([u["username"] for u in cfg["users"]], names)
        self.assertNotIn("secret-", json.dumps(cfg))   # 값은 설정에 없다
        f = self.d / "so" / names[0]; self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o640); self.assertEqual(f.read_text(), "secret-" + names[0] + "\n")

    def test_dash_means_no_groups(self):
        self.assertEqual(self.run_cfg("wait-e2e -\n", ["wait-e2e"]), 0)
        self.assertEqual(json.loads((self.d / "cfg.json").read_text())["users"][0]["groups"], [])

    def test_unknown_group_is_a_contract_violation(self): self.assertEqual(self.run_cfg("x-e2e superuser\n", ["x-e2e"]), 1)
    def test_missing_password_file_fails(self): self.assertEqual(self.run_cfg("x-e2e staff\n", []), 1)


if __name__ == "__main__":
    unittest.main()
