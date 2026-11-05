#!/usr/bin/env python3
"""단독 시험: 영역 DB 의 계정 비밀은 이미지 라벨 io.openit.database(계약 DatabaseDeclaration)에서 만든다(계약 3.4.10, 구조 규칙 1·4). 입력은 계약 예시 examples/DatabaseDeclaration.json.
변이 확인: 암호를 DB 쪽과 URI 쪽에서 다르게 쓰거나 sslmode 를 빼거나 라벨 없는 이미지를 받으면 실패한다(이 파일의 test_mutation_*)."""
import json, os, stat, sys, tempfile, unittest, pathlib
from urllib.parse import urlparse, parse_qs

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from boundary_contracts import validator  # noqa: E402
from openit_deploy.components import db_secrets  # noqa: E402
from openit_deploy.wiring import cli_gen_db_secrets as G  # noqa: E402

def example() -> dict:
    # 시험 자료는 deploy 가 갖는다(scripts/fixtures, 계약 예시에서 가져옴). 이웃 리포 폴더 위치에 기대지 않는다(구조 규칙 1). 계약을 따르는지는 아래 첫 시험이 검증한다
    return json.loads((ROOT / "scripts" / "fixtures" / "DatabaseDeclaration.json").read_text(encoding="utf-8"))


class T(unittest.TestCase):
    def test_example_is_valid_declaration(self):
        self.assertEqual([e.message for e in validator("DatabaseDeclaration").iter_errors(example())], [])

    def test_component_uri_and_files(self):
        d = example()
        pw = {a["name"]: ("%02d" % i) * 16 for i, a in enumerate(d["accounts"])}
        r = db_secrets.run({"db_host": "ops-feedback-db", "declaration": d, "passwords": pw})
        for a in d["accounts"]:
            self.assertEqual(r["account_files"][a["name"]], pw[a["name"]] + "\n")
            for env in a["url_env"]:
                u = urlparse(r["url_files"][a["name"]][env].strip())
                self.assertEqual((u.scheme, u.username, u.password, u.hostname, u.port, u.path), ("postgresql", a["name"], pw[a["name"]], "ops-feedback-db", d["port"], "/" + a["database"]))
                q = parse_qs(u.query)
                self.assertEqual(q["sslmode"], ["verify-full"]); self.assertTrue(q["sslrootcert"][0].startswith("/"))

    def test_same_password_in_db_and_uri(self):   # 변이: 한쪽만 다른 암호를 쓰면 접속이 안 된다
        with tempfile.TemporaryDirectory() as t:
            f = pathlib.Path(t) / "decl.json"; f.write_text(json.dumps(example()))
            self.assertEqual(G.main(["--declaration", str(f), "--db-host", "x-db", "--accounts-dir", t + "/a", "--urls-dir", t + "/u"]), 0)
            for a in example()["accounts"]:
                pw = (pathlib.Path(t) / "a" / a["name"]).read_text().strip()
                for env in a["url_env"]:
                    self.assertEqual(urlparse((pathlib.Path(t) / "u" / a["name"] / env).read_text().strip()).password, pw)
                    self.assertEqual(stat.S_IMODE(os.stat(pathlib.Path(t) / "u" / a["name"] / env).st_mode), 0o600)

    def test_idempotent_keeps_password(self):
        with tempfile.TemporaryDirectory() as t:
            f = pathlib.Path(t) / "decl.json"; f.write_text(json.dumps(example()))
            args = ["--declaration", str(f), "--db-host", "x-db", "--accounts-dir", t + "/a", "--urls-dir", t + "/u"]
            G.main(args); first = {p.name: p.read_text() for p in (pathlib.Path(t) / "a").iterdir()}
            G.main(args); self.assertEqual(first, {p.name: p.read_text() for p in (pathlib.Path(t) / "a").iterdir()})

    def test_mutation_label_missing_rejected(self):
        with self.assertRaises(SystemExit):
            G.main(["--image", "img/db", "--db-host", "x-db", "--accounts-dir", "/tmp/x-a", "--urls-dir", "/tmp/x-u"], labels_of=lambda i: {})

    def test_mutation_invalid_declaration_rejected(self):
        bad = example(); bad["engine"] = "mysql"
        with self.assertRaises(SystemExit):
            G.main(["--image", "img/db", "--db-host", "x-db", "--accounts-dir", "/tmp/x-a", "--urls-dir", "/tmp/x-u"], labels_of=lambda i: {"io.openit.database": json.dumps(bad)})

    def test_label_path(self):
        with tempfile.TemporaryDirectory() as t:
            rc = G.main(["--image", "img/db", "--db-host", "x-db", "--accounts-dir", t + "/a", "--urls-dir", t + "/u"], labels_of=lambda i: {"io.openit.database": json.dumps(example())})
            self.assertEqual(rc, 0)

    def test_same_env_in_two_accounts_kept_apart(self):   # ops-feedback 은 owner·app 이 같은 환경 변수 이름을 선언한다: 계정별 파일로 나뉘어야 한다
        d = example(); d["accounts"][1]["url_env"] = list(d["accounts"][0]["url_env"])
        r = db_secrets.run({"db_host": "x-db", "declaration": d, "passwords": {a["name"]: ("%d" % i) * 16 for i, a in enumerate(d["accounts"])}})
        env = d["accounts"][0]["url_env"][0]
        self.assertNotEqual(r["url_files"][d["accounts"][0]["name"]][env], r["url_files"][d["accounts"][1]["name"]][env])

if __name__ == "__main__":
    unittest.main(verbosity=1)
