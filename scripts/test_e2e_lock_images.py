#!/usr/bin/env python3
"""E2E 가 임시 잠금(DEPLOY_LOCK)에 옮기는 외부 이미지 변수(scripts/e2e.sh 의 grep)가 compose 가 요구하는 `${NAME_IMAGE:?…}` 전부를 덮는지 본다.
새 외부 이미지(예: KEYCLOAK_IMAGE, OAUTH2_PROXY_IMAGE)를 compose 에 더하고 e2e.sh 목록을 빠뜨리면 E2E 가 기동 직전에 'required variable … missing' 으로 멈췄다(D9c).
사용: python3 scripts/test_e2e_lock_images.py"""
import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCK = (ROOT / "locks/images.lock").read_text(encoding="utf-8")


class T(unittest.TestCase):
    def test_e2e_copies_every_third_party_image_compose_requires(self):
        e2e = (ROOT / "scripts/e2e.sh").read_text(encoding="utf-8")
        m = re.search(r"grep -E '\^\[A-Z0-9_\]\+_IMAGE=' \"\$DEPLOY_ROOT/locks/images.lock\" > \"\$DEPLOY_LOCK\"", e2e)
        self.assertTrue(m, "e2e.sh 는 잠금의 외부 이미지 줄을 전부(`^[A-Z0-9_]+_IMAGE=`) 복사해야 한다: 손으로 적은 목록은 새 이미지(STEP_CA)가 빠졌다")
        demo = (ROOT / "scripts/demo.sh").read_text(encoding="utf-8")
        self.assertIn("grep -E '^[A-Z0-9_]+_IMAGE=' \"$DEPLOY_ROOT/locks/images.lock\" > \"$DEPLOY_LOCK\"", demo)
        copied = {n for n in re.findall(r"^([A-Z0-9_]+)_IMAGE=", LOCK, re.M)}
        need = set()
        for f in ("compose.yaml", "compose.monitoring.yaml", "compose.backup-target.yaml", "compose.registry.yaml", "compose.external-inference.yaml"):
            need |= set(re.findall(r"\$\{([A-Z0-9_]+)_IMAGE:\?", (ROOT / f).read_text(encoding="utf-8")))
        third = {n for n in need if re.search(rf"^{n}_IMAGE=", LOCK, re.M)}   # 잠금 파일에 고정 줄이 있는 외부 이미지(영역 이미지는 <NAME>_DIGEST 로 E2E 가 게시한다)
        self.assertEqual(sorted(third - copied), [], "compose 가 요구하는 외부 이미지가 E2E 임시 잠금에 복사되지 않는다")
        self.assertTrue({"KEYCLOAK", "OAUTH2_PROXY"} <= third)

    def test_dc_unsets_shell_overrides_for_every_locked_image(self):
        lib = (ROOT / "scripts/lib.sh").read_text(encoding="utf-8")
        for n in re.findall(r"^([A-Z0-9_]+_IMAGE)=", LOCK, re.M):
            self.assertIn(f"-u {n}", lib, f"dc 가 셸 환경의 {n} 이 잠금 파일을 이기지 못하게 지우지 않는다")


if __name__ == "__main__":
    unittest.main()
