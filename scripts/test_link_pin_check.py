#!/usr/bin/env python3
"""link 핀 대조 자체 시험(U59, ADR 0046): 영역 잠금 파일의 openit-link 태그를 읽는 모양들, 판정(MATCH/DIFF/NO_PIN), 가짜 워크스페이스(git 리포 + main 브랜치)로 CLI 종료 코드. 이웃 영역의 실제 파일을 읽지 않는다. 사용: <deploy .venv>/bin/python scripts/test_link_pin_check.py"""
import json, pathlib, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from openit_deploy.components import link_pin_check as C
from openit_deploy.wiring import cli_check_link_pins as W

SSH = "git+ssh://git@github.com/Sdabin1209/openit_link.git"


class Pins(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(C.pins_in(f"openit-link @ {SSH}@v0.4.1\n"), ["v0.4.1"])
        self.assertEqual(C.pins_in(f"{SSH}@v0.4.0\n"), ["v0.4.0"])                        # 접두사 없는 줄(release-gate 모양)
        self.assertEqual(C.pins_in("FROM x\nARG LINK_VERSION=v0.4.1   # 설명\n"), ["v0.4.1"])   # Dockerfile
        self.assertEqual(C.pins_in(f"# openit-link @ {SSH}@v0.1.0\nboundary-contracts @ x@v3.1.1\n"), [])   # 주석·다른 패키지는 보지 않는다

    def test_status(self):
        f = lambda t: [{"path": "requirements.lock", "text": f"openit-link @ {SSH}@{t}\n"}]
        r = C.run({"expected_tag": "v0.4.1", "areas": [{"name": "a", "files": f("v0.4.1")}, {"name": "b", "files": f("v0.4.0")}, {"name": "c", "files": [{"path": "x.txt", "text": ""}]},
                                                        {"name": "d", "files": f("v0.4.1") + [{"path": "requirements.txt", "text": f"openit-link @ {SSH}@v0.4.0\n"}]}]})
        self.assertEqual([x["status"] for x in r["areas"]], ["MATCH", "DIFF", "NO_PIN", "DIFF"])   # 한 영역 안에서 파일끼리 어긋나도 DIFF
        self.assertEqual((r["match"], r["diff"], r["no_pin"], r["status"]), (1, 2, 1, "DIFF"))

    def test_all_no_pin_is_not_a_pass(self):
        r = C.run({"expected_tag": "v0.4.1", "areas": [{"name": "a", "files": []}]}); self.assertEqual(r["status"], "NO_PIN")


class Cli(unittest.TestCase):
    def ws(self, tags):
        d = pathlib.Path(tempfile.mkdtemp()); (d / "head/shared").mkdir(parents=True)
        (d / "head/shared/areas.json").write_text(json.dumps({"areas": [{"name": n, "kind": "python", "version_train": False} for n in tags]}))
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        for n, t in tags.items():
            r = d / n; r.mkdir(); subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
            if t: (r / "requirements.lock").write_text(f"openit-link @ {SSH}@{t}\n")
            (r / "README.md").write_text("x"); subprocess.run(g + ["-C", str(r), "add", "-A"], check=True); subprocess.run(g + ["-C", str(r), "commit", "-qm", "x"], check=True)
            if t: (r / "requirements.lock").write_text(f"openit-link @ {SSH}@v9.9.9\n")   # 미커밋 변경은 보지 않는다(정본은 main)
        return d

    def test_exit_codes(self):
        self.assertEqual(W.main(["--ws", str(self.ws({"a": "v0.4.1", "b": None})), "--tag", "v0.4.1"]), 0)   # 핀 없는 영역은 통과를 막지 않되 따로 센다
        self.assertEqual(W.main(["--ws", str(self.ws({"a": "v0.4.1", "b": "v0.4.0"})), "--tag", "v0.4.1"]), 1)
        self.assertEqual(W.main(["--ws", str(self.ws({"a": None})), "--tag", "v0.4.1"]), 3)


if __name__ == "__main__":
    unittest.main()
