#!/usr/bin/env python3
"""deploy 가 내는 설정 파일 중 계약 스키마가 있는 것은 전부 계약 validator 로 검증한다(U-config: 옛 `rollback: null` 이 2.7.0 부터 계약을 어기고도 아무 시험에도 걸리지 않았다).
대상 표(CONTRACT)는 파일 -> 스키마 이름. config/ 바로 아래 *.yaml·*.json 이 이 표에도 OWN(deploy 자신의 형식, 이유 필수)에도 없으면 실패한다: 새 설정 파일을 만들 때 계약이 있는지 먼저 따지게 한다.
사용: <deploy .venv>/bin/python scripts/test_config_contracts.py   (계약 패키지가 설치된 파이썬)"""
import json, pathlib, unittest

import yaml
from boundary_contracts import validator

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT = {
    "config/ops-feedback-job.yaml": "OpsFeedbackJobConfig",
    "test/ops-job/test-ops-job.yaml": "OpsFeedbackJobConfig",
    "test/risk-rules.e2e.json": "SurveyRiskRulesFile",
}
OWN = {   # deploy 자신의 형식(계약 스키마 없음)
    "config/exposure-hosts.json": "Caddyfile 상류 호스트 -> 서비스 이름 대응(check-exposure 입력, ADR 0043)",
    "config/exposure-known-diffs.json": "알려진 노출 어긋남 목록과 이유(ADR 0043)",
    "config/verify-areas.yaml": "영역 -> 시험·E2E 단계 대응표(verify_area.py)",
}


def load(rel):
    p = ROOT / rel
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.suffix in (".yaml", ".yml") else json.loads(p.read_text(encoding="utf-8"))


class T(unittest.TestCase):
    def test_each_config_matches_its_contract(self):
        for rel, schema in CONTRACT.items():
            with self.subTest(rel):
                try: v = validator(schema)
                except Exception: self.skipTest(f"SKIP: 설치된 계약 패키지에 {schema} 가 없다(확인 못 함)")
                errs = [f"{'/'.join(map(str, e.path))}: {e.message[:100]}" for e in v.iter_errors(load(rel))]
                self.assertEqual(errs, [], f"{rel} 가 계약 {schema} 를 어긴다")

    def test_every_config_file_is_classified(self):
        files = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "config").iterdir() if p.is_file() and p.suffix in (".yaml", ".yml", ".json"))
        unknown = [f for f in files if f not in CONTRACT and f not in OWN]
        self.assertEqual(unknown, [], f"계약 스키마 대상인지 deploy 자신의 형식인지 정하지 않은 설정 파일: {unknown} (이 시험의 CONTRACT 또는 OWN 에 이유와 함께 적는다)")

    def test_tables_point_at_existing_files(self):
        for rel in list(CONTRACT) + list(OWN):
            self.assertTrue((ROOT / rel).is_file(), f"{rel} 가 없다(표를 고친다)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
