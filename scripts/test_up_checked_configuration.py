"""The startup gate checks the generated configuration that is actually used."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def test_up_uses_the_generation_that_passed_the_gate():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        scripts = root / 'scripts'
        scripts.mkdir()
        (scripts / 'up.sh').write_text((ROOT / 'scripts/up.sh').read_text())
        for name in ['check-compose.sh', 'gen-db-secrets-all.sh']:
            (scripts / name).write_text('#!/bin/bash\nexit 0\n')
        (scripts / 'lib.sh').write_text('''
DEPLOY_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DOCKER=true
DEPLOY_PY="$DEPLOY_ROOT/checker"
generation=0
die() { echo "$*" >&2; exit 1; }
gen_stack_files() { generation=$((generation+1)); }
dc() {
  case " $* " in
    *" config "*) printf '{"generation":%s,"services":{}}' "$generation";;
    *" up "*)
      [ -n "${GEN_STACK_ACTIVE:-}" ] || gen_stack_files "$1"
      printf '%s' "$generation" > "$DEPLOY_ROOT/started"
      ;;
  esac
}
''')
        checker = root / 'checker'
        checker.write_text('''#!/usr/bin/env python3
import json,sys
from pathlib import Path
path=Path(sys.argv[sys.argv.index('--compose-json')+1])
value=json.loads(path.read_text())['generation']
with (Path(__file__).parent/'checked').open('a') as out:out.write(str(value)+'\\n')
''')
        checker.chmod(0o755)
        result = subprocess.run(
            ['bash', str(scripts / 'up.sh'), 'isolated-test'],
            env={**os.environ, 'DEPLOY_SKIP_DOCTOR': '1'},
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr
        checked = (root / 'checked').read_text().splitlines()
        assert checked and set(checked) == {(root / 'started').read_text()}
        assert checked[0] != '0', 'the gate ran before declaration generation'
