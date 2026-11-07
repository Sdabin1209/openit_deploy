#!/usr/bin/env python3
"""기기 인증서 허용 목록(계약 DeviceAllowlist, PUBLIC_API F절, D136)을 읽고 바꾼다. kiosk-add-device.sh·gen-secrets.sh 가 부른다.
사용: device_allowlist.py <목록 파일> add <기기 ID> <일련번호> | remove-serial <기기 ID> <일련번호> | remove <기기 ID> | has <기기 ID> | init | list | serials <기기 ID>
왜 이 모양인가:
- 읽고-고치고-바꾸는 전 과정에 같은 배타 잠금(fcntl.flock, POSIX flock(2))을 쥔다: 동시에 등록하는 두 호출이 서로의 일련번호를 덮어쓰지 않게 한다(마지막 쓴 쪽만 남는 갱신 손실 방지).
  잠금 파일은 목록 폴더 밖(<폴더>.lock)에 둔다: 목록 폴더는 공개 입구에 읽기 전용으로 마운트되므로 목록 하나만 든다(계약 DeviceAllowlist: 부모 디렉터리를 마운트).
- 쓰기는 같은 폴더의 임시 파일 + fsync + os.replace(POSIX rename(2) 은 같은 파일시스템에서 원자적): 읽는 쪽은 옛 목록이나 새 목록 전체만 본다. 파일은 통째로 교체되므로 입구는 파일이 아니라 폴더를 마운트한다.
- 쓰기 전에 계약 패키지의 검증기로 검증하고(R7: 만드는 쪽이 검증한다), 어기면 파일을 바꾸지 않는다. 같은 기기 ID 는 한 항목으로 합친다(계약: device_id 중복은 입구가 시작을 거부한다).
- 권한 0644 / 폴더 0755: 입구 컨테이너(uid 10001, gid 0, 이미지 라벨 io.openit.inputs 의 roles.default.process)는 호스트 파일의 소유자도 그룹도 아니므로 '기타' 읽기 권한이 필요하다. 목록은 비밀이 아니다(계약 DeviceAllowlist).
"""
import fcntl, json, os, re, sys, tempfile

from boundary_contracts import validator

SERIAL = re.compile(r"^[0-9a-fA-F]{1,40}$")


def norm_serial(s):
    """RFC 5280 4.1.2.2: 일련번호는 양의 정수. 앞자리 0 없는 소문자 16진수로 맞춘다(계약 DeviceAllowlist.serials 형식)."""
    if not SERIAL.match(s): raise SystemExit(f"일련번호 형식 오류(16진수 1~40자리): {s!r}")
    s = s.lower().lstrip("0")
    if not s: raise SystemExit("일련번호 0 은 허용하지 않는다(RFC 5280: 양의 정수)")
    return s


def load(path):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except FileNotFoundError: return {"schema_version": 1, "devices": []}


def check(doc):
    errs = [f"/{'/'.join(map(str, e.path))}: {e.validator} 위반" for e in validator("DeviceAllowlist").iter_errors(doc)]
    ids = [d["device_id"] for d in doc.get("devices", [])]
    if len(ids) != len(set(ids)): errs.append("device_id 가 겹친다")
    if errs: raise SystemExit("기기 허용 목록이 계약 DeviceAllowlist 를 어긴다: " + "; ".join(errs))


def write(path, doc):
    check(doc)
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
        devs = {x["device_id"]: x for x in doc["devices"]} if "devices" in doc else {}
        if cmd == "add":
            did, ser = args[0], norm_serial(args[1])
            e = devs.setdefault(did, {"device_id": did, "serials": []})
            if ser not in e["serials"]: e["serials"].append(ser)
        elif cmd == "remove-serial":
            did, ser = args[0], norm_serial(args[1])
            if did not in devs or ser not in devs[did]["serials"]: raise SystemExit(f"없는 일련번호: {did}")
            devs[did]["serials"].remove(ser)
            if not devs[did]["serials"]: del devs[did]   # 계약: serials 는 1개 이상. 마지막 일련번호를 빼면 기기가 폐기된 것이다
        elif cmd == "remove":
            devs.pop(args[0], None)
        elif cmd == "init":
            if not os.path.exists(path): write(path, {"schema_version": 1, "devices": []})
            return
        elif cmd == "has": sys.exit(0 if args[0] in devs else 1)
        elif cmd == "list": print("\n".join(sorted(devs))); return
        elif cmd == "serials": print("\n".join(devs.get(args[0], {"serials": []})["serials"])); return
        else: raise SystemExit(__doc__)
        write(path, {"schema_version": 1, "devices": [devs[k] for k in sorted(devs)]})


if __name__ == "__main__":
    main(sys.argv)
