#!/usr/bin/env python3
"""빌드 기록(build/images.env)을 서비스 한 줄씩 합쳐 원자적으로 바꾼다.
사용: images_record.py <기록 파일> set <서비스> <나머지 열...>   그 서비스의 줄을 바꾸거나 더한다(다른 줄은 그대로)
      images_record.py <기록 파일> keep <서비스...>             목록에 없는 서비스의 줄을 지운다(전체 빌드의 시작: 사라진 서비스·버릴 GPU 기록 정리)
왜: 예전 build-images.sh 는 전체 빌드 시작에 기록을 지우고(rm) 서비스마다 sed -i 삭제 + >> 추가를 했다. 두 빌드가 겹치면 뒤 빌드의 rm 이
앞 빌드의 줄을 지우고 sed -i(임시 파일 + rename)와 >> 가 서로의 쓰기를 덮어써, 2026-11-08 기록이 21줄 중 4줄만 남았다.
그래서 (1) 읽기-바꾸기-쓰기 전체를 잠금 파일(<기록>.lock)의 배타 잠금(fcntl.flock, POSIX advisory lock) 안에서 하고
(2) 같은 디렉터리의 임시 파일에 쓴 뒤 os.replace(POSIX rename(2), 같은 파일 시스템에서 원자적)로 바꾼다. 읽는 쪽은 언제나 완성된 파일 하나를 본다.
종료 코드: 0 성공, 2 사용 오류."""
import fcntl, os, sys, tempfile


def _lines(path):
    try:
        with open(path, encoding="utf-8") as f: return [l.rstrip("\n") for l in f if l.strip()]
    except FileNotFoundError: return []


def update(path, fn):
    """잠금 안에서 줄 목록을 fn 으로 바꿔 원자적으로 쓴다."""
    d = os.path.dirname(os.path.abspath(path)); os.makedirs(d, exist_ok=True)
    with open(path + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        new = fn(_lines(path))
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".images.env.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("".join(l + "\n" for l in new)); f.flush(); os.fsync(f.fileno())
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        except BaseException:
            try: os.unlink(tmp)
            except FileNotFoundError: pass
            raise


def main(argv):
    if len(argv) < 3 or argv[1] not in ("set", "keep"): print(__doc__, file=sys.stderr); return 2
    path, op, args = argv[0], argv[1], argv[2:]
    if op == "set":
        if len(args) < 2: print("set 에는 <서비스> 와 열이 필요하다", file=sys.stderr); return 2
        svc, row = args[0], " ".join(args)
        def fn(ls):
            out, done = [], False
            for l in ls:
                if l.split(" ", 1)[0] == svc:
                    if not done: out.append(row); done = True
                else: out.append(l)
            return out if done else out + [row]
        update(path, fn)
    else:
        keep = set(args); update(path, lambda ls: [l for l in ls if l.split(" ", 1)[0] in keep])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
