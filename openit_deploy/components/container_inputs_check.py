"""컴포넌트 container_inputs_check: compose 가 서비스마다 주입하는 것이 그 이미지의 주입 선언(계약 ContainerInputs 3.5.0, 라벨 io.openit.inputs)과 정확히 같은지 대조한다.
입력 ContainerInputsCheckRequest, 출력 ContainerInputsCheckResult(schemas/). 실행하지 않는다(compose 설정과 라벨만 본다).
왜: 파일 권한·쓰기 경로·실행 사용자·argv 가 문장 규칙뿐이라 영역과 deploy 가 각자 해석했고, 2026-11-06 E2E 기동 실패(DB 비밀 읽기, TLS 사본 경로,
잡 argv)가 모두 그 어긋남이었다. 선언과 다르면 기동 전에 멈춘다.
규칙(위반 번호):
  I1 루트는 읽기 전용(read_only: true)            I2 cap_drop 에 ALL, cap_add 는 선언 capabilities 와 같다
  I3 sysctls 는 선언과 같다                          I4 user·entrypoint 를 덮어쓰지 않는다(이미지 USER 가 선언 process, 진입점이 argv 규칙을 지킨다)
  I5 서비스의 묶음(역할·잡)이 선언에 있다
  I6 선언한 필수 파일이 주입된다(경로 = path_env 값 또는 path; 폴더는 그 경로 또는 그 아래 파일)
  I7 주입한 파일(secrets·configs·읽기 전용 마운트)은 선언에 있다(선언한 파일이거나 선언한 폴더 아래)
  I8 선언한 쓰기 경로가 주어진다(persist 면 이름 있는 볼륨). tmpfs 는 명시 mode(없으면 이미지 경로의 모드에 root 소유, 경로가 없으면 재시작 때의 0:0 0755, 확인 못 하면 검증 불가 실패)로 쓰는 사용자가 쓸 수 있어야 한다
  I9 주어진 쓰기 마운트(tmpfs·쓰기 볼륨)는 선언에 있다(선언한 쓰기 경로이거나 그 아래: 이미지가 쓰는 폴더를 배치가 볼륨으로 나눌 수 있다. 유지 경로 아래면 볼륨이어야 한다)
  I10 compose secrets 로 파일을 주입하면 group_add 에 SECRETS_GID 가 있다(호스트 비밀 파일은 0640·그룹 SECRETS_GID, 시작 프로세스가 그룹으로 읽는다: opened_by=start-process)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import ContainerInputsCheckRequest, ContainerInputsCheckResult


def _under(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip("/") + "/")


def _check_service(s: dict, decl: dict, out: list) -> int:
    svc, n = s["service"], 0
    def bad(rule, detail):
        out.append({"service": svc, "rule": rule, "detail": detail})
    n += 1
    if not s["read_only"]:
        bad("I1", "read_only 가 아니다(계약 ContainerInputs.read_only_root)")
    kind, _, name = s["set"].partition(":")
    st = (decl["roles"] if kind == "role" else decl["jobs"]).get(name)
    n += 1
    if st is None:
        bad("I5", f"{decl['image']} 선언에 {'역할' if kind == 'role' else '잡'} {name} 이(가) 없다(있는 것: {sorted(decl['roles'] if kind == 'role' else decl['jobs'])})")
        return n
    n += 1
    if "ALL" not in s["cap_drop"]:
        bad("I2", "cap_drop 에 ALL 이 없다")
    if sorted(s["cap_add"]) != sorted(st["capabilities"]):
        bad("I2", f"cap_add {sorted(s['cap_add'])} 가 선언 capabilities {sorted(st['capabilities'])} 와 다르다")
    n += 1
    if s["sysctls"] != st.get("sysctls", {}):
        bad("I3", f"sysctls {sorted(s['sysctls'])} 가 선언 {sorted(st.get('sysctls', {}))} 와 다르다")
    n += 1
    if s["user_override"]:
        bad("I4", "user 를 덮어쓴다(선언 process 는 이미지 USER 다)")
    if s["entrypoint_override"]:
        bad("I4", "entrypoint 를 덮어쓴다(잡은 선언 argv 로 고르고 진입점은 이미지 것)")
    if kind == "role" and s["command_override"]:
        bad("I4", "서비스 command 를 덮어쓴다(이미지의 기본 명령을 사용해야 한다)")
    if kind == "job":
        n += 1
        if not s["expected_argv"] or s["argv"] != s["expected_argv"]:
            bad("I11", "잡 command 가 이미지 JobsDeclaration.argv 와 다르다")
    given = [f["target"] for f in s["files"]]
    dirs = [f["target"] for f in s["files"] if f.get("directory") is True or f["source"] == "volume"]
    declared = []
    for f in st["files"]:
        n += 1
        path = s["env"].get(f["path_env"], f["path"]) if f.get("path_env") else f["path"]
        declared.append((path, f.get("directory", False)))
        if f.get("directory"):
            ok = any(_under(g, path) for g in given) or any(_under(path, d) for d in dirs)
        else:
            ok = path in given or any(_under(path, d) for d in dirs)
        exact = [g for g in s["files"] if g["target"] == path]
        if exact and any(g.get("directory") is not None and g["directory"] != f.get("directory", False) for g in exact):
            bad("I6", f"선언한 {path} 의 파일·폴더 종류가 주입과 다르다")
        if f["required"] and not ok:
            bad("I6", f"선언한 파일 {path}" + (f" ({f['path_env']})" if f.get("path_env") else "") + " 이(가) 주입되지 않는다")
    for g in given:
        n += 1
        if not any(_under(g, p) if d else (g == p or _under(p, g)) for p, d in declared):
            bad("I7", f"주입한 {g} 이(가) 선언에 없다")
    wgiven = {w["target"]: w for w in s["writable"]}
    for w in st["writable"]:
        n += 1
        g = wgiven.get(w["path"])
        if g is None:
            bad("I8", f"선언한 쓰기 경로 {w['path']} 이(가) 주어지지 않는다")
            continue
        if w["persist"] and g["kind"] != "volume":
            bad("I8", f"{w['path']} 는 유지해야 한다(persist): {g['kind']} 가 아니라 이름 있는 볼륨이어야 한다")
        wb = w["written_by"]
        if g["kind"] == "tmpfs":
            # tmpfs 뿌리의 소유는 uid·gid 옵션(없으면 root 0:0)이고, 모드는 명시 mode, 없으면 이미지의 같은 경로 디렉터리 모드다(소유는 따라오지 않는다).
            # 측정 2026-11-08(Docker 28.5.1): release-gate 이미지 /data 는 10001:0 0755 인데 --tmpfs /data 는 0:0 0755 -> 10001 의 mkdir PermissionError.
            # 이미지에 그 경로가 없으면(image_dir=null) 첫 기동만 0:0 1777 이고, Docker 가 마운트 지점을 컨테이너 층에 root 0755 로 만들어 두므로
            # 같은 컨테이너를 다시 시작하면(restart 정책·docker start) 0:0 0755 가 된다. 측정 2026-11-08(Docker 28.5.1, identity 이미지 /opt/keycloak/data/import:
            # 첫 start 0:0 1777 쓰기 성공, 둘째 start 0:0 755 Permission denied; E2E 단계 9 복구 뒤 재시작에서 identity 가 같은 이유로 unhealthy). 그래서 0755 로 판정한다.
            # 이미지 경로를 확인하지 못했으면(image_dir 없음) 쓸 수 있다고 가정하지 않고 실패한다
            if "mode" in g:
                mode, ou, og = int(g["mode"], 8), g.get("uid", 0), g.get("gid", 0)
            elif "image_dir" not in g:
                bad("I8", f"tmpfs {w['path']} 에 mode 가 없고 이미지의 그 경로 소유·모드를 확인하지 못했다(검증 불가): mode·uid·gid 를 명시하거나 볼륨을 쓴다")
                continue
            elif g["image_dir"] is None:
                mode, ou, og = 0o755, g.get("uid", 0), g.get("gid", 0)
            else:
                mode, ou, og = int(g["image_dir"]["mode"], 8), g.get("uid", 0), g.get("gid", 0)
            shift = 6 if wb["uid"] == ou else 3 if wb["gid"] == og else 0
            # POSIX directory creation requires both write and search permissions.
            allowed = ((mode >> shift) & 3) == 3
            if wb["uid"] == 0 and "DAC_OVERRIDE" in st["capabilities"]:
                allowed = True
            if not allowed:
                bad("I8", f"tmpfs {w['path']} 의 소유 {ou}:{og}·모드 {oct(mode)[2:]} 로 선언된 사용자 {wb['uid']}:{wb['gid']} 가 쓸 수 없다")
    for t, g in wgiven.items():
        n += 1
        parent = [w for w in st["writable"] if _under(t, w["path"])]
        if not parent:
            bad("I9", f"쓰기 마운트 {t} 이(가) 선언에 없다")
        elif t not in {w["path"] for w in parent} and any(w["persist"] for w in parent) and g["kind"] != "volume":
            bad("I9", f"쓰기 마운트 {t} 는 유지 경로 아래라 이름 있는 볼륨이어야 한다({g['kind']})")
    n += 1
    if any(f["source"] == "secret" for f in s["files"]) and not s["secrets_group"]:
        bad("I10", "compose secrets 로 파일을 주입하는데 group_add 에 SECRETS_GID 가 없다(0640 비밀을 읽지 못한다)")
    return n


def run(request: "ContainerInputsCheckRequest") -> "ContainerInputsCheckResult":
    out, checked = [], 0
    for s in request["services"]:
        decl = request["declarations"].get(s["image"])
        checked += 1
        if decl is None:
            out.append({"service": s["service"], "rule": "I5", "detail": f"이미지 {s['image']} 의 주입 선언(라벨 io.openit.inputs)이 없다"})
            continue
        checked += _check_service(s, decl, out)
    return {"status": "VIOLATIONS" if out else "OK", "checked": checked, "violations": out}
