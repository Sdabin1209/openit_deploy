"""기기 인증서 허용 목록(계약 DeviceAllowlist, PUBLIC_API F절, D136)을 읽고 바꾼다. kiosk-add-device.sh·gen-secrets.sh 가 부른다.
사용: device_allowlist.py <목록 파일> add <기기 ID> <일련번호> | remove-serial <기기 ID> <일련번호> | remove <기기 ID> | has <기기 ID> | init | list | serials <기기 ID>
왜 이 모양인가:
- 읽고-고치고-바꾸는 전 과정에 같은 배타 잠금(fcntl.flock, POSIX flock(2))을 쥔다: 동시에 등록하는 두 호출이 서로의 일련번호를 덮어쓰지 않게 한다(마지막 쓴 쪽만 남는 갱신 손실 방지).
  잠금 파일은 목록 폴더 밖(<폴더>.lock)에 둔다: 목록 폴더는 공개 입구에 읽기 전용으로 마운트되므로 목록 하나만 든다(계약 DeviceAllowlist: 부모 디렉터리를 마운트).
- 쓰기는 같은 폴더의 임시 파일 + fsync + os.replace(POSIX rename(2) 은 같은 파일시스템에서 원자적): 읽는 쪽은 옛 목록이나 새 목록 전체만 본다. 파일은 통째로 교체되므로 입구는 파일이 아니라 폴더를 마운트한다.
- 쓰기 전에 계약 패키지의 검증기로 검증하고(R7: 만드는 쪽이 검증한다), 어기면 파일을 바꾸지 않는다. 같은 기기 ID 는 한 항목으로 합친다(계약: device_id 중복은 입구가 시작을 거부한다).
- 권한 0644 / 폴더 0755: 입구 컨테이너(uid 10001, gid 0, 이미지 라벨 io.openit.inputs 의 roles.default.process)는 호스트 파일의 소유자도 그룹도 아니므로 '기타' 읽기 권한이 필요하다. 목록은 비밀이 아니다(계약 DeviceAllowlist).
"""
import fcntl
import json
import os
import sys
import tempfile

from openit_deploy.components import device_allowlist
from openit_deploy.wiring.call import call

NEEDS_ID = {"add", "remove-serial", "remove", "has", "serials"}
NEEDS_SERIAL = {"add", "remove-serial"}


def load(path):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except FileNotFoundError: return {"schema_version": 1, "devices": []}


def write(path, doc):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".allowlist-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=2, sort_keys=True) + "\n"); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def main(argv):
    if len(argv) < 3: raise SystemExit(__doc__)
    path, cmd, args = os.path.abspath(argv[1]), argv[2], argv[3:]
    d = os.path.dirname(path); os.makedirs(d, exist_ok=True); os.chmod(d, 0o755)
    lock = d.rstrip("/") + ".lock"
    with open(lock, "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)   # 파일을 닫을 때(프로세스 끝) 풀린다
        doc = load(path)
        if cmd not in NEEDS_ID | {"init", "list"}: raise SystemExit(__doc__)
        req = {"command": cmd, "exists": os.path.exists(path), "current": doc}
        if cmd in NEEDS_ID: req["device_id"] = args[0]
        if cmd in NEEDS_SERIAL: req["serial"] = args[1]
        res = call(device_allowlist, "DeviceAllowlistEditRequest", "DeviceAllowlistEditResult", req)
        st = res["status"]
        if st == "REJECTED": raise SystemExit(res["message"])
        if st in ("YES", "NO"): sys.exit(0 if st == "YES" else 1)
        if st == "PRINT": print("\n".join(res["lines"])); return
        if st == "WRITE": write(path, res["doc"])
