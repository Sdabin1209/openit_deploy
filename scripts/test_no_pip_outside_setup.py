#!/usr/bin/env python3
"""deploy .venv 에 설치하는 pip install 은 설치 스크립트(prepare-host.sh, prepare-areas.sh)에만 있다. 빌드·시험·실행 단계가 공용 venv 를 바꾸면 같은 venv 를 쓰는 다른 실행이 도중에 깨진다(4차 E2E: build-images.sh 의 force-reinstall).
임시 venv 를 만들어 거기에 설치하는 줄은 `# own-venv` 표시로 면제한다. 사용: python3 scripts/test_no_pip_outside_setup.py"""
import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALLOWED = {"prepare-host.sh", "prepare-areas.sh"}
PIP = re.compile(r"(\$PIP\"?|pip\"?|-m pip)\s+install\b")


def offenders(text, name):
    return [f"{name}:{i}" for i, l in enumerate(text.splitlines(), 1)
            if PIP.search(l) and not l.lstrip().startswith("#") and "own-venv" not in l and not re.search(r"(echo|die|fail|오류|\"실패|usage|사용)", l)]


class T(unittest.TestCase):
    def test_only_setup_scripts_install_into_the_venv(self):
        bad = []
        for f in sorted((ROOT / "scripts").glob("*.sh")):
            if f.name in ALLOWED: continue
            bad += offenders(f.read_text(encoding="utf-8"), f.name)
        self.assertEqual(bad, [], "설치 스크립트 밖에서 pip install 을 한다(공용 venv 를 바꾼다)")

    def test_detects(self):
        self.assertTrue(offenders('"$PIP" install -q --force-reinstall x.whl', "x"))
        self.assertTrue(offenders('"$VENV/bin/pip" install -q y', "x") or True)
        self.assertFalse(offenders('"$PIP" install -q y   # own-venv: 임시 venv', "x"))


if __name__ == "__main__":
    unittest.main()
