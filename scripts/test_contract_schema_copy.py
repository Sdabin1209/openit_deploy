#!/usr/bin/env python3
"""계약 패키지(boundary_contracts, 2.2.0 부터 ImageLabels 등 deploy 경계 스키마 8개를 가진다)와 deploy 의 contract-ready 사본이 같은지,
그리고 check_image_labels.py 가 설치된 계약 패키지의 스키마를 사본보다 먼저 쓰는지 고정한다. 다르면 계약 쪽이 정본이다(사본을 계약에 맞춘다).
사용: <deploy .venv>/bin/python scripts/test_contract_schema_copy.py   (계약 패키지가 설치된 파이썬. 패키지에 스키마가 없으면 실패: 통과로 세지 않는다)"""
import json, pathlib, subprocess, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent
COPY = HERE.parent / "docs/change-requests/contract-ready/schemas"
NAMES = ["BuildImageRequest", "BuildImageResult", "Exposure", "ImageLabels", "JobsDeclaration", "PublishRequest", "PublishResult", "SetupEnvReport"]


def pkg_dir():
    import boundary_contracts
    return pathlib.Path(boundary_contracts.__file__).parent / "schemas"


class T(unittest.TestCase):
    def test_package_has_all_deploy_schemas(self):
        missing = [n for n in NAMES if not (pkg_dir() / f"{n}.schema.json").is_file()]
        self.assertEqual(missing, [], "설치된 계약 패키지에 deploy 경계 스키마가 없다(2.2.0 이상이 필요하다)")

    def test_copy_equals_package(self):
        diff = [n for n in NAMES if json.loads((COPY / f"{n}.schema.json").read_text(encoding="utf-8")) != json.loads((pkg_dir() / f"{n}.schema.json").read_text(encoding="utf-8"))]
        self.assertEqual(diff, [], "contract-ready 사본이 계약 패키지와 다르다(계약이 정본: 사본을 맞춘다)")

    def test_checker_prefers_package(self):
        labels = {"io.openit.service": "s", "io.openit.revision": "abc1234", "io.openit.contracts.boundary": "v2.3.0", "io.openit.contracts.survey-schema": "1"}
        p = subprocess.run([sys.executable, "-W", "ignore", str(HERE / "check_image_labels.py")], input=json.dumps(labels), capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("스키마 출처: 계약 패키지", p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
