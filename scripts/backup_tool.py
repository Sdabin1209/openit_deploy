#!/usr/bin/env python3
"""컨테이너 안에서 도는 백업·복구 도구(표준 라이브러리만). backup.sh / restore.sh 가 UTIL_IMAGE 안에서 부른다.

  backup   <src> <dst> --store S [--exclude NAME ...]   SQLite는 backup API로 일관된 사본, 나머지는 복사. MANIFEST.json에 해시를 남긴다
  verify   <snapshot>                                   MANIFEST의 해시를 다시 계산해 대조한다
  restore  <snapshot> <dst> --uid N --gid N             dst를 비우고 스냅샷을 복원한다(해시 검증 뒤)
  finger   <src>                                        논리 지문: SQLite는 덤프의 해시, 나머지는 바이트 해시. 복구 시험이 쓴다
"""
import argparse, hashlib, json, os, shutil, sqlite3, sys, time

SQLITE_EXT = (".db", ".sqlite", ".sqlite3")
SKIP_SUFFIX = ("-wal", "-shm", "-journal")
# 저장소별 제외: survey-data/releases 는 게이트 묶음에서 다시 적재되는 작업 폴더 사본이다
# datasets-data/.tmp 는 dataset-store 서버의 요청 임시 폴더다(시작 때 비우고 다시 만든다, synthetic-data ADR 0012). 복구할 데이터가 아니고 지문에 들어가면 서버를 껐다 켤 때마다 달라진다
STORE_EXCLUDES = {"survey-data": ("releases",), "datasets-data": (".tmp",)}


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return "sha256:" + h.hexdigest()


def walk(root, exclude=()):
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if os.path.relpath(os.path.join(d, x), root) not in exclude)
        for f in sorted(files):
            p = os.path.join(d, f); rel = os.path.relpath(p, root)
            if rel in exclude or rel.endswith(SKIP_SUFFIX): continue
            yield p, rel


def walk_dirs(root, exclude=()):
    for d, dirs, _ in os.walk(root):
        dirs[:] = sorted(x for x in dirs if os.path.relpath(os.path.join(d, x), root) not in exclude)
        for x in dirs: yield os.path.relpath(os.path.join(d, x), root)


def open_ro(p):
    """읽기 전용 연결(WAL 포함). 우리가 만든 -wal/-shm 은 release 가 지운다."""
    pre = {sfx: os.path.exists(p + sfx) for sfx in ("-wal", "-shm")}
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True), pre


def release(p, pre):
    for sfx, existed in pre.items():
        if not existed and os.path.exists(p + sfx): os.remove(p + sfx)


def is_sqlite(p):
    return p.endswith(SQLITE_EXT)


def chown_tree(root, owner):
    uid, gid = (int(x) for x in owner.split(":"))
    for d, dirs, files in os.walk(root):
        for n in dirs + files: os.chown(os.path.join(d, n), uid, gid)
    os.chown(root, uid, gid)


def backup(src, dst, store, exclude, owner=None):
    try:
        _backup(src, dst, store, exclude)
    finally:
        if owner and os.path.exists(dst): chown_tree(dst, owner)   # 실패해도 호스트 사용자가 지울 수 있게


def _backup(src, dst, store, exclude):
    os.makedirs(dst, exist_ok=True)
    files = {}
    # SQLite를 먼저, 나머지 파일을 나중에 복사한다. (게이트: DB의 행이 가리키는 릴리스 파일은 불변이라 DB보다 뒤에 복사한 디렉터리가 항상 포함한다)
    items = sorted(walk(src, exclude), key=lambda t: (not is_sqlite(t[0]), t[1]))
    for p, rel in items:
        out = os.path.join(dst, rel); os.makedirs(os.path.dirname(out), exist_ok=True)
        if is_sqlite(p):
            # 읽기 전용 연결이지만 WAL 모드 DB는 -shm 파일이 필요해 볼륨을 쓰기 가능으로 붙인다. 우리가 만든 -wal/-shm 은 지운다.
            s, pre = open_ro(p); d = sqlite3.connect(out)
            with d: s.backup(d)
            s.close(); d.close(); release(p, pre)
        else:
            shutil.copy2(p, out)
        files[rel] = {"sha256": sha(out), "size": os.path.getsize(out), "sqlite": is_sqlite(p)}
    man = {"store": store, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dirs": sorted(walk_dirs(src, exclude)), "files": files}
    json.dump(man, open(os.path.join(dst, "MANIFEST.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps({"store": store, "files": len(files)}))


def verify(snap):
    man = json.load(open(os.path.join(snap, "MANIFEST.json")))
    bad = [rel for rel, m in man["files"].items() if not os.path.exists(os.path.join(snap, rel)) or sha(os.path.join(snap, rel)) != m["sha256"]]
    if bad:
        print("해시 불일치: " + ", ".join(bad), file=sys.stderr); sys.exit(3)
    return man


def restore(snap, dst, uid, gid):
    man = verify(snap)
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(dst):
        p = os.path.join(dst, name)
        shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
    for rel in man.get("dirs", []): os.makedirs(os.path.join(dst, rel), exist_ok=True)
    for rel in man["files"]:
        out = os.path.join(dst, rel); os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copy2(os.path.join(snap, rel), out)
    for d, dirs, files in os.walk(dst):
        for n in dirs + files: os.chown(os.path.join(d, n), uid, gid)
    os.chown(dst, uid, gid)
    print(json.dumps({"restored": len(man["files"])}))


def finger(src, store):
    ex = STORE_EXCLUDES.get(store, ())
    h = hashlib.sha256(); n = 0
    for rel in sorted(walk_dirs(src, ex)): h.update(("dir:" + rel).encode())
    for p, rel in walk(src, ex):
        h.update(rel.encode())
        if is_sqlite(p):
            c, pre = open_ro(p)   # backup 과 같은 방식(WAL 포함)으로 읽어야 백업·복구 앞뒤가 같다
            for line in c.iterdump(): h.update(line.encode())
            c.close(); release(p, pre)
        else:
            h.update(sha(p).encode())
        n += 1
    print(json.dumps({"fingerprint": h.hexdigest(), "files": n}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd")
    ap.add_argument("a"); ap.add_argument("b", nargs="?")
    ap.add_argument("--store"); ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--owner"); ap.add_argument("--uid", type=int); ap.add_argument("--gid", type=int)
    x = ap.parse_args()
    if x.cmd == "backup": backup(x.a, x.b, x.store, tuple(x.exclude) + STORE_EXCLUDES.get(x.store, ()), x.owner)
    elif x.cmd == "verify": verify(x.a); print("ok")
    elif x.cmd == "restore": restore(x.a, x.b, x.uid, x.gid)
    elif x.cmd == "finger": finger(x.a, x.store)
    else: sys.exit("알 수 없는 명령")
