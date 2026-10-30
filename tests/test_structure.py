#!/usr/bin/env python3
"""구조 검사(DESIGN.md 6절, D117, ADR 0045). 사용: <deploy .venv>/bin/python tests/test_structure.py
1 schemas/·types/·components/·wiring/ 가 있다. 2 components/ 파일이 다른 components/ 파일을 import 하지 않는다.
3 HTTP 클라이언트·서버(boundary_contracts.clients, openit_link, urllib.request, http.client, requests, http.server)는 통신 컴포넌트(link_*) 밖에 없다.
4 모든 스키마에 통과·거부 예시가 있고 결과가 맞다. 5 types/ 가 schemas/ 에서 다시 생성한 결과와 같다. 6 시험을 뺀 모든 코드 파일이 components/·wiring/·types/ 또는 진입점·설정에 속한다.
덧붙임: 진입점(scripts/*.py)은 얇다(업무 규칙 없음), 컴포넌트마다 입력·출력 스키마가 있고 docs/components.md 표와 같다, 컴포넌트는 wiring/ 을 import 하지 않는다."""
import ast
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "openit_deploy"
sys.path.insert(0, str(ROOT))

HTTP_PY = re.compile(r"^\s*(from|import)\s+(boundary_contracts\.clients|openit_link|urllib\.request|http\.client|http\.server|requests|waitress|wsgiref)\b", re.M)
# 수용 시험(E2E 시나리오와 그 보조): 시스템 전체를 이웃의 HTTP 로 확인하는 시험이지 deploy 의 업무 컴포넌트가 아니다(ADR 0045). 시험에 든다.
ACCEPTANCE = {"e2e_steps.py", "e2e_plan.py", "e2e_asserts.py"}
SHIM_MAX_STATEMENTS = 8   # 진입점은 경로 설정, wiring 의 main 을 가져오기, 호출만 한다(머리말 설명은 세지 않는다)


def comps():
    return sorted(p for p in (PKG / "components").glob("*.py") if p.name != "__init__.py")


class Structure(unittest.TestCase):
    def test_1_directories_exist(self):
        for d in ("schemas", "openit_deploy/types", "openit_deploy/components", "openit_deploy/wiring"):
            self.assertTrue(any((ROOT / d).glob("*.py")) or any((ROOT / d).glob("*.json")), f"{d}/ 가 비었거나 없다")

    def test_2_components_do_not_import_each_other(self):
        names = {p.stem for p in comps()}
        bad = []
        for p in comps():
            t = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(t):
                mods = [n.module or ""] + [a.name for a in n.names] if isinstance(n, ast.ImportFrom) else [a.name for a in n.names] if isinstance(n, ast.Import) else []
                for m in mods:
                    parts = m.split(".")
                    if ("components" in parts and parts[-1] in names and parts[-1] != p.stem) or (isinstance(n, ast.ImportFrom) and (n.module or "") == "openit_deploy.components" and any(a.name in names and a.name != p.stem for a in n.names)):
                        bad.append(f"{p.name}: 다른 컴포넌트 import {m}")
                    if parts[:2] == ["openit_deploy", "wiring"]:
                        bad.append(f"{p.name}: wiring 을 import (컴포넌트는 wiring 을 모른다)")
        self.assertEqual(bad, [])

    def test_3_http_only_in_link_components(self):
        bad = []
        for p in list(PKG.rglob("*.py")):
            if p.name.startswith("link_") and p.parent.name == "components": continue
            if HTTP_PY.search(p.read_text(encoding="utf-8")): bad.append(str(p.relative_to(ROOT)))
        # 진입점 중 수용 시험은 시험으로 센다. 그 밖의 scripts/*.py 는 HTTP 를 쓰지 않는다
        for p in (ROOT / "scripts").glob("*.py"):
            if p.name.startswith("test_") or p.name in ACCEPTANCE: continue
            if HTTP_PY.search(p.read_text(encoding="utf-8")): bad.append(str(p.relative_to(ROOT)))
        self.assertEqual(bad, [], "통신 컴포넌트(link_*) 밖에서 HTTP")

    def test_3b_acceptance_gets_clients_only_from_link(self):
        t = (ROOT / "scripts/e2e_steps.py").read_text(encoding="utf-8")
        self.assertNotIn("boundary_contracts.clients", t.replace("(openit_link.clients", ""), "E2E 는 이웃 클라이언트를 통신 기반 라이브러리 link(openit_link.clients)로만 가져온다")
        self.assertIn("from openit_link.clients import", t)

    def test_4_every_schema_has_valid_and_invalid_examples_with_right_results(self):
        from openit_deploy.wiring.schema_check import errors, SCHEMA_DIR
        names = sorted(p.name[:-len(".schema.json")] for p in SCHEMA_DIR.glob("*.schema.json"))
        self.assertTrue(names)
        for n in names:
            ex = ROOT / "schemas/examples"
            valid, invalid = sorted(ex.glob(f"{n}.valid*.json")), sorted(ex.glob(f"{n}.invalid*.json"))
            self.assertTrue(valid and invalid, f"{n}: 통과·거부 예시가 모두 있어야 한다")
            for f in valid: self.assertEqual(errors(n, json.loads(f.read_text(encoding="utf-8"))), [], f"{f.name} 은 통과해야 한다")
            for f in invalid: self.assertNotEqual(errors(n, json.loads(f.read_text(encoding="utf-8"))), [], f"{f.name} 은 거부돼야 한다")
        stray = [p.name for p in (ROOT / "schemas/examples").glob("*.json") if p.name.split(".")[0] not in names]
        self.assertEqual(stray, [], "스키마가 없는 예시")

    def test_5_types_match_regenerated(self):
        gen = ROOT / "build/venv-types/bin/datamodel-codegen"
        if not gen.exists():   # 작업 트리(worktree)면 본 리포의 생성기 환경
            gen = pathlib.Path(subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"], capture_output=True, text=True).stdout.strip()).resolve().parent / "build/venv-types/bin/datamodel-codegen"
        self.assertTrue(gen.exists(), "생성기가 없다(건너뛰지 않고 실패로 센다): python3 -m venv build/venv-types && build/venv-types/bin/pip install -r requirements-types.txt")
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "deploy_types.py"
            r = subprocess.run(["bash", str(ROOT / "scripts/gen-types.sh"), str(out)], capture_output=True, text=True, env={**__import__("os").environ, "TYPES_GEN": str(gen)})
            self.assertEqual(r.returncode, 0, r.stderr[-400:])
            self.assertEqual(out.read_text(encoding="utf-8"), (PKG / "types/deploy_types.py").read_text(encoding="utf-8"), "types/ 가 schemas/ 와 다르다: bash scripts/gen-types.sh")

    def test_6_every_code_file_has_a_place(self):
        files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "*.py"], capture_output=True, text=True).stdout.split()
        bad = []
        for f in files:
            if re.search(r"(^|/)(tests?)/|(^|/)test_[^/]*\.py$|^scripts/test_", f): continue   # 시험
            if re.match(r"openit_deploy/(components|wiring|types)/", f) or f == "openit_deploy/__init__.py": continue
            if f.startswith("scripts/") and (f.split("/")[-1] in ACCEPTANCE): continue   # 수용 시험
            if f.startswith("scripts/"): continue   # 진입점: 아래 test_entry_points_are_thin 이 얇은지 본다
            bad.append(f)
        self.assertEqual(bad, [], "components/·wiring/·types/·진입점 어디에도 속하지 않는 코드")

    def test_entry_points_are_thin(self):
        fat = []
        for p in (ROOT / "scripts").glob("*.py"):
            if p.name.startswith("test_") or p.name in ACCEPTANCE: continue
            body = ast.parse(p.read_text(encoding="utf-8")).body
            n = len([x for x in body if not (isinstance(x, ast.Expr) and isinstance(getattr(x, "value", None), ast.Constant))])
            if n > SHIM_MAX_STATEMENTS: fat.append(f"{p.name} (문장 {n}개)")
        self.assertEqual(fat, [], "진입점에 업무 규칙이 들어갔다(컴포넌트로 옮긴다)")

    def test_each_component_has_input_and_output_schema_and_is_in_components_md(self):
        from openit_deploy.wiring.schema_check import SCHEMA_DIR
        md = (ROOT / "docs/components.md").read_text(encoding="utf-8")
        rows = {}
        for line in md.splitlines():
            m = re.match(r"^\|\s*(\w+)\s*\|\s*`openit_deploy/components/(\w+)\.py`\s*\|\s*(\w+)\s*\|\s*(\w+)\s*\|", line)
            if m: rows[m.group(2)] = (m.group(3), m.group(4))
        self.assertEqual(sorted(rows), sorted(p.stem for p in comps()), "docs/components.md 의 표와 components/ 파일이 다르다")
        for name, (i, o) in rows.items():
            for t in (i, o):
                self.assertTrue((SCHEMA_DIR / f"{t}.schema.json").is_file(), f"{name}: 스키마 {t} 가 없다")
            src = (PKG / f"components/{name}.py").read_text(encoding="utf-8")
            self.assertIn(i, src, f"{name}: 소스가 입력 타입 {i} 를 가리키지 않는다"); self.assertIn(o, src, f"{name}: 소스가 출력 타입 {o} 를 가리키지 않는다")

    def test_secret_files_table_matches_schema_enum(self):
        from openit_deploy.components.job_command import SECRET_FILES
        s = json.loads((ROOT / "schemas/JobCommandRequest.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(SECRET_FILES), sorted(s["properties"]["job"]["properties"]["secret_files"]["items"]["enum"]))


if __name__ == "__main__":
    unittest.main()
