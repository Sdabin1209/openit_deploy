"""scripts/fixtures 의 시험·도구 자료가 계약 스키마를 따른다(계약 예시에서 가져온 자료다. 계약이 바뀌어 어긋나면 여기서 실패한다)."""
import json, pathlib, unittest
from boundary_contracts import validator

FX = pathlib.Path(__file__).resolve().parent / "fixtures"


class T(unittest.TestCase):
    def test_every_fixture_follows_its_contract_schema(self):
        files = sorted(FX.glob("*.json"))
        self.assertTrue(files)
        for f in files:
            name = f.name.split(".")[0]   # <계약 스키마 이름>[.<예시 이름>].json
            errs = [e.message for e in validator(name).iter_errors(json.loads(f.read_text(encoding="utf-8")))]
            self.assertEqual(errs, [], f.name)

    def test_mutation_broken_fixture_is_caught(self):
        bad = dict(json.loads((FX / "DatabaseDeclaration.json").read_text(encoding="utf-8")))
        bad.pop(next(iter(bad)))
        self.assertTrue(list(validator("DatabaseDeclaration").iter_errors(bad)))


if __name__ == "__main__":
    unittest.main()
