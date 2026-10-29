#!/usr/bin/env python3
"""lib.sh 의 서비스 목록(SERVICES + SERVICES_OPTIONAL)이 계약 PublishRequest.service enum 과 같은지 점검한다(U46).
왜 시험인가: 같은 사실(게시할 수 있는 서비스 이름)이 계약 enum 과 lib.sh 두 곳에 있다. 정본은 계약 enum 이고 lib.sh 는 그 사본이다. lib.sh 가 셸 변수라 계약에서 매번 만들면
모든 스크립트가 python 과 계약 패키지에 기대게 되므로, 다르면 실패하는 시험으로 같음을 보장한다. 계약 enum 이 바뀌어야 하면 docs/change-requests/ 로 헤드에게 보낸다.
사용: python3 -I scripts/test_services_enum.py   (deploy .venv: boundary_contracts 설치 필요)"""
import os, pathlib, subprocess, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def lib_lists(lib=None):
    lib = lib or ROOT / "scripts" / "lib.sh"
    out = subprocess.run(["bash", "-c", f'DEPLOY_NO_DOCKER=1; source "{lib}"; echo "$SERVICES|$SERVICES_OPTIONAL"'], capture_output=True, text=True, check=True).stdout.strip()
    a, b = out.split("|"); return a.split(), b.split()


def contract_enum():
    import boundary_contracts as bc
    return list(bc.load_schema("PublishRequest")["properties"]["service"]["enum"])


def diff(services, optional, enum):
    """(계약에만 있음, lib.sh 에만 있음, 중복). 비어 있으면 같다."""
    lib = services + optional
    return sorted(set(enum) - set(lib)), sorted(set(lib) - set(enum)), sorted({x for x in lib if lib.count(x) > 1})


class T(unittest.TestCase):
    def test_lib_matches_contract_enum(self):
        s, o = lib_lists(); only_c, only_l, dup = diff(s, o, contract_enum())
        self.assertEqual((only_c, only_l, dup), ([], [], []), f"계약 enum 에만 {only_c}, lib.sh 에만 {only_l}, 중복 {dup}")

    def test_diff_detects_mismatch(self):   # 점검 자체가 어긋남을 잡는지(틀린 입력으로)
        enum = ["a", "b", "c"]
        self.assertEqual(diff(["a", "b"], ["c"], enum), ([], [], []))
        self.assertEqual(diff(["a"], ["c"], enum), (["b"], [], []))
        self.assertEqual(diff(["a", "b", "x"], ["c"], enum), ([], ["x"], []))
        self.assertEqual(diff(["a", "b"], ["b", "c"], enum), ([], [], ["b"]))


if __name__ == "__main__":
    unittest.main()
