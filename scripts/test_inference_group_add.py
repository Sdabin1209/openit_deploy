#!/usr/bin/env python3
"""정적 시험(L02, ADR 0054/0060): 추론 compose(compose.inference.yaml)도 제품 compose 와 같은 비밀 규칙을 따른다. 비밀·설정 파일을 마운트하는 서비스는 모두 group_add(SECRETS_GID)를 갖고,
토큰 파일을 누구나 읽게(644) 하라는 문구가 머리말에 없다. 사용: python3 scripts/test_inference_group_add.py"""
import pathlib, unittest
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
TEXT = (ROOT / "compose.inference.yaml").read_text(encoding="utf-8")
S = yaml.safe_load(TEXT)["services"]


class T(unittest.TestCase):
    def test_every_service_with_secret_or_config_has_group_add(self):
        bad = [n for n, v in S.items() if (v.get("secrets") or v.get("configs")) and not any("SECRETS_GID" in str(g) for g in v.get("group_add", []))]
        self.assertEqual(bad, [], "비밀·설정을 마운트하는데 group_add(SECRETS_GID)가 없다")

    def test_header_does_not_ask_for_world_readable_tokens(self):
        head = TEXT.split("\nname:")[0]
        self.assertNotIn("모드 644", head, "토큰 파일은 640 + 그룹이다(누구나 읽게 하지 않는다)")


if __name__ == "__main__":
    unittest.main()
