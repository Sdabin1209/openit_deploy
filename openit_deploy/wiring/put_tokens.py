"""Remote I/O adapter: consumes a producer-validated TokenDeliveryRequest; needs only Python stdlib.
Outputs /r/root_ca.crt (0644) and /t/<declared name>.ott (0640, declared reader uid/gid).
"""
import base64
import json
import os
import pathlib
import sys
import tempfile


def atomic_file(path, value, mode, uid, gid):
    path = pathlib.Path(path)
    # 임시 이름은 대상 이름 길이와 무관한 고정 길이다: 251바이트 이름의 <이름>.ott(255바이트)에 접두어를 붙이면 NAME_MAX 를 넘는다(계약 3.6.5, 2026-11-07 교차검증)
    descriptor, temporary = tempfile.mkstemp(prefix='.tok-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as output:
            output.write(value)
            output.flush()
            os.fchmod(output.fileno(), mode)
            os.fchown(output.fileno(), uid, gid)
            os.fsync(output.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_delivery(data, root_dir='/r', token_dir='/t'):
    atomic_file(pathlib.Path(root_dir) / 'root_ca.crt', data['root'], 0o644, 0, 0)
    for name, token in data['tokens'].items():
        atomic_file(pathlib.Path(token_dir) / (name + '.ott'), token['value'], 0o640, token['uid'], token['gid'])
    return {'tokens_written': len(data['tokens']), 'root_written': True}


def main():
    try:
        request = json.loads(base64.b64decode(sys.stdin.read().strip(), validate=True))
        result = write_delivery(request)
    except Exception as error:
        print(f'token delivery write failed: {type(error).__name__}', file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
