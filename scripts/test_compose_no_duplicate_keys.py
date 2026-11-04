#!/usr/bin/env python3
"""compose 파일에 같은 매핑 안의 중복 키가 없다. 왜: PyYAML 은 중복 키를 조용히 덮어써서 다른 시험이 통과하지만 docker compose 는 파싱을 거부한다(3.4.17 역할 Env 이관에서 실제로 났다). 변이: 중복이 있는 문서를 잡는다.
사용: python3 scripts/test_compose_no_duplicate_keys.py"""
import pathlib, sys, unittest
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent


def dups(text: str):
    found = []
    class L(yaml.SafeLoader): pass
    for t in ("!reset", "!override"): L.add_multi_constructor(t, lambda l, s, n: None)   # compose 확장 태그
    def cm(loader, node, deep=False):
        seen = set()
        for k, _ in node.value:
            if k.tag != "tag:yaml.org,2002:merge":
                if k.value in seen: found.append((k.value, k.start_mark.line + 1))
                seen.add(k.value)
        return yaml.SafeLoader.construct_mapping(loader, node, deep)
    L.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, cm)
    yaml.load(text, Loader=L)
    return found


class T(unittest.TestCase):
    def test_compose_files_have_no_duplicate_keys(self):
        for f in sorted(ROOT.glob("compose*.yaml")) + sorted((ROOT / "test").glob("compose*.yaml")) + sorted((ROOT / "demo").glob("*.yaml")):
            self.assertEqual(dups(f.read_text(encoding="utf-8")), [], f.name)

    def test_mutation_duplicate_is_caught(self):
        self.assertEqual(dups("services:\n  a:\n    environment: {X: 1}\n    environment: {Y: 2}\n"), [("environment", 4)])


if __name__ == "__main__":
    unittest.main()
