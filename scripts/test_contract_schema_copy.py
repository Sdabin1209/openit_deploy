#!/usr/bin/env python3
"""계약 패키지(boundary_contracts)가 deploy 경계 스키마를 가졌고, deploy 리포에 스키마 사본이 없으며, check_image_labels.py 가 계약 패키지의 스키마를 쓰는지 고정한다.
왜: 공통 규칙 '스키마는 패키지에 들어 있으므로 복사본을 만들지 않는다'. 예전에는 contract-ready/ 사본을 두고 패키지와 같은지 비교했으나(승격 전 임시 정본), 사본은 패키지와 어긋나
(BuildImageRequest 등 4개) 정본이 둘이 됐다. 사본을 지웠고, 이 시험은 사본이 다시 생기지 않음을 확인한다.
사용: <deploy .venv>/bin/python scripts/test_contract_schema_copy.py   (계약 패키지가 설치된 파이썬. 패키지에 스키마가 없으면 실패: 통과로 세지 않는다)"""
import json, pathlib, subprocess, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
NAMES = ["BuildImageRequest", "BuildImageResult", "Exposure", "ImageLabels", "JobsDeclaration", "PublishRequest", "PublishResult", "SetupEnvReport"]


def pkg_dir():
    import boundary_contracts
    return pathlib.Path(boundary_contracts.__file__).parent / "schemas"


class T(unittest.TestCase):
    def test_package_has_all_deploy_schemas(self):
        missing = [n for n in NAMES if not (pkg_dir() / f"{n}.schema.json").is_file()]
        self.assertEqual(missing, [], "설치된 계약 패키지에 deploy 경계 스키마가 없다")

    def test_no_schema_copies_in_repo(self):
        files = [p for p in ROOT.rglob("*.schema.json") if not any(x in p.parts for x in (".venv", "build", "node_modules", ".git", "state"))]
        # deploy 자신의 내부 파일 형식 스키마(schemas/, ADR 0034)는 계약이 아니라 deploy 의 것이므로 허용한다
        bad = [str(p.relative_to(ROOT)) for p in files if p.parent.name != "schemas" or p.parent.parent != ROOT]
        self.assertEqual(bad, [], f"계약 스키마 사본이 리포에 있다(정본은 계약 패키지): {bad}")
        for n in NAMES:
            self.assertFalse((ROOT / "schemas" / f"{n}.schema.json").exists(), f"deploy schemas/ 에 계약 스키마 {n} 사본이 있다")

    def test_checker_uses_package(self):
        labels = {"io.openit.service": "s", "io.openit.revision": "abc1234", "io.openit.contracts.boundary": "v2.6.0", "io.openit.contracts.survey-schema": "1"}
        p = subprocess.run([sys.executable, "-W", "ignore", str(HERE / "check_image_labels.py")], input=json.dumps(labels), capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("스키마 출처: 계약 패키지", p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
