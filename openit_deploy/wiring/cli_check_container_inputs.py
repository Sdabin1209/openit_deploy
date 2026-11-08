"""wiring/진입: check_container_inputs.py --compose-json 파일 [--declarations-dir 폴더] [--secrets-gid N]
compose 가 우리 이미지에 주입하는 것(docker compose config 의 해석 결과)을 이미지의 주입 선언(라벨 io.openit.inputs, 계약 ContainerInputs 3.5.0)과 대조한다.
선언은 기본으로 이미지 라벨에서 읽는다(up.sh 가 기동 전에 부른다). --declarations-dir 를 주면 <이미지>.json 파일에서 읽는다(이미지 없이 정적 대조: 시험·자체 점검).
선언은 계약 validator 로 검증한 뒤 컴포넌트에 넘긴다(R7). 종료 코드: 0 일치, 1 어긋남(서비스·규칙·경로만 출력, 값은 출력하지 않는다), 2 입력 오류."""
import argparse
import copy
import shlex
import json
import os
import pathlib
import re
import sys

from openit_deploy.components import container_inputs_check
from openit_deploy.wiring.call import call
from openit_deploy.wiring.cli_gen_jobs import JOB_NAMES, image_labels

OURS = re.compile(r"/openit/([a-z0-9-]+)[@:]")


def _secret_target(item: dict) -> str:
    t = item.get("target") or item["source"]
    return t if t.startswith("/") else "/run/secrets/" + t   # compose: 상대 target 은 /run/secrets 아래


def _config_target(item: dict) -> str:
    t = item.get("target") or item["source"]
    return t if t.startswith("/") else "/" + t   # compose: configs 의 target 이 없으면 /<이름>


class FileBindingError(ValueError):
    """A sanitized descriptor/schema/path error; never include file contents."""


def typed_role_file_documents(body: dict, inputs: dict, config: dict) -> list:
    """Bind declared JSON content schemas to the files actually being mounted."""
    mounts = [(v["target"], pathlib.Path(v["source"])) for v in body.get("volumes", [])
              if v.get("type") == "bind"]
    for kind, target in [("configs", _config_target), ("secrets", _secret_target)]:
        for item in body.get(kind, []):
            source = config.get(kind, {}).get(item["source"], {}).get("file")
            if source:
                mounts.append((target(item), pathlib.Path(source)))
    documents = []
    for descriptor in inputs["files"]:
        if not descriptor.get("schema"):
            continue
        path = {k: str(v) for k, v in body.get("environment", {}).items() if v is not None}.get(descriptor.get("path_env"), descriptor["path"])
        candidates = []
        for target, source in mounts:
            if path == target:
                candidates.append(source)
            elif path.startswith(target.rstrip("/") + "/") and source.is_dir():
                candidates.append(source / path[len(target.rstrip("/")) + 1:])
        if not candidates:
            if descriptor["required"]:
                raise FileBindingError(f"{descriptor['schema']} {path}: required typed file has no readable host binding")
            continue
        if len(candidates) != 1 or descriptor.get("directory"):
            raise FileBindingError(f"{descriptor['schema']} {path}: typed file binding is ambiguous or unsupported")
        try:
            document = json.loads(candidates[0].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise FileBindingError(f"{descriptor['schema']} {path}: typed file is missing, unreadable or invalid JSON") from None
        documents.append((descriptor["schema"], document))
    return documents


def facts(name: str, body: dict, image: str, decl: dict, secrets_gid: str, expected_argv=None) -> dict:
    env = {k: str(v) for k, v in (body.get("environment") or {}).items() if v is not None}
    if name in JOB_NAMES:
        st = "job:" + JOB_NAMES[name]
    else:
        role = env.get(decl["role_env"]) if decl.get("role_env") else "default"
        if decl.get("role_env") and role is None:
            from boundary_contracts import load_schema
            defaults = {
                load_schema(profile["env_schema"]).get("properties", {}).get(decl["role_env"], {}).get("default")
                for profile in decl["roles"].values()
            }
            defaults.discard(None)
            if len(defaults) != 1:
                raise ValueError(f"{name}: role default is missing or ambiguous in declared Env schemas")
            role = defaults.pop()
        st = "role:" + role
    files = [{"target": _secret_target(s), "source": "secret"} for s in body.get("secrets") or []]
    files += [{"target": _config_target(c), "source": "config"} for c in body.get("configs") or []]
    writable = []
    for v in body.get("volumes") or []:
        if v.get("type") == "tmpfs":
            options = v.get("tmpfs") or {}
            writable.append({"target": v["target"], "kind": "tmpfs", **({"mode": format(options["mode"], "o")} if "mode" in options else {})})
        elif v.get("read_only"):
            source = pathlib.Path(v["source"]) if v.get("type") == "bind" else None
            directory = source.is_dir() if source is not None and source.exists() else True if v.get("type") == "volume" else None
            files.append({"target": v["target"], "source": "bind" if v.get("type") == "bind" else "volume", "directory": directory})
        else:
            writable.append({"target": v["target"], "kind": "volume" if v.get("type") == "volume" else "bind"})
    for t in body.get("tmpfs") or []:
        path, _, opt = str(t).partition(":")
        w = {"target": path, "kind": "tmpfs"}
        mu, mg = re.search(r"uid=(\d+)", opt), re.search(r"gid=(\d+)", opt)
        if mu: w["uid"] = int(mu.group(1))
        if mg: w["gid"] = int(mg.group(1))
        mm = re.search(r"mode=([0-7]+)", opt)
        if mm: w["mode"] = mm.group(1)
        writable.append(w)
    return {"service": name, "image": image, "set": st, "read_only": bool(body.get("read_only")),
            "cap_drop": list(body.get("cap_drop") or []), "cap_add": list(body.get("cap_add") or []),
            "sysctls": {k: int(v) for k, v in (body.get("sysctls") or {}).items()},
            "user_override": bool(body.get("user")), "entrypoint_override": "entrypoint" in body and body["entrypoint"] is not None,
            "command_override": "command" in body and body["command"] is not None,
            "argv": shlex.split(body["command"]) if isinstance(body.get("command"), str) else body.get("command"),
            "expected_argv": expected_argv,
            "secrets_group": str(secrets_gid) in [str(g) for g in body.get("group_add") or []],
            "env": env, "files": files, "writable": writable}


_UNVERIFIED = object()


def image_dir(image: str, path: str):
    """이미지의 path 디렉터리 소유·모드를 실행하지 않고 읽는다(docker create + docker cp 의 tar 머리글). 경로가 없으면 None, 읽지 못하면 _UNVERIFIED.
    왜: tmpfs 를 이미지에 있는 디렉터리 위에 올리면 Docker 가 그 디렉터리의 소유·모드를 준다(1777 이 아니다). 측정 2026-11-08 release-gate /data root 0755."""
    import subprocess, tarfile
    c = subprocess.run(["docker", "create", "--network", "none", image, "/x"], capture_output=True, text=True)
    if c.returncode != 0:
        return _UNVERIFIED
    cid = c.stdout.strip()
    try:
        p = subprocess.Popen(["docker", "cp", f"{cid}:{path}", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=p.stdout, mode="r|") as tf:
                m = next(iter(tf), None)
        except tarfile.TarError:
            m = None
        p.kill(); _, err = p.communicate()
        if m is None:
            return None if b"Could not find the file" in err or b"No such container:path" in err else _UNVERIFIED
        if not m.isdir():
            return _UNVERIFIED
        return {"mode": format(m.mode & 0o7777, "o").zfill(4), "uid": m.uid, "gid": m.gid}
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True)


def main(argv=None, labels_of=image_labels, image_dir_of=image_dir) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compose-json", required=True)
    ap.add_argument("--declarations-dir")
    ap.add_argument("--secrets-gid", default=os.environ.get("SECRETS_GID", str(os.getgid())))
    ap.add_argument("--image-dirs", help="정적 대조용: {이미지: {경로: {mode,uid,gid} 또는 null}} JSON(이미지 없이). 없으면 --declarations-dir 모드의 mode 없는 tmpfs 는 검증 불가")
    a = ap.parse_args(argv)
    offline_dirs = json.loads(pathlib.Path(a.image_dirs).read_text(encoding="utf-8")) if a.image_dirs else {}
    dir_cache = {}
    from boundary_contracts import load_schema, validator
    vci = validator("ContainerInputs")
    cfg = json.loads(sys.stdin.read() if a.compose_json == "-" else pathlib.Path(a.compose_json).read_text(encoding="utf-8"))
    decls, services, problems, job_specs = {}, [], [], {}
    for name, body in sorted((cfg.get("services") or {}).items()):
        ref = str((body or {}).get("image", ""))
        if a.declarations_dir:
            m = OURS.search(ref)
            if not m:
                continue   # 우리 이미지가 아니다(deploy 의 외부 이미지: pause, registry, util 등은 deploy 내부에서 다룬다)
            img = m.group(1)
            f = pathlib.Path(a.declarations_dir) / f"{img}.json"
            raw = f.read_text(encoding="utf-8") if f.exists() else None
            jf = pathlib.Path(a.declarations_dir) / f"{img}.jobs.json"
            job_raw = jf.read_text(encoding="utf-8") if jf.exists() else None
        else:
            lb = labels_of(ref) if ref else {}
            img = lb.get("io.openit.service")
            if not img or "io.openit.contracts.boundary" not in lb:
                if OURS.search(ref):
                    problems.append(f"{name}: 영역 이미지의 식별·계약 라벨이 없다")
                continue   # 우리 이미지가 아니다(라벨 io.openit.* 이 없다)
            raw = lb.get("io.openit.inputs")
            job_raw = lb.get("io.openit.jobs")
        if img not in decls:
            if raw is None:
                problems.append(f"{name}: 이미지 {img} 의 주입 선언이 없다")
                continue
            d = json.loads(raw)
            errs = [("/".join(map(str, e.absolute_path)) or "(최상위)") + ": " + e.validator for e in vci.iter_errors(d)]
            if errs:
                problems.append(f"{name}: 이미지 {img} 의 주입 선언이 계약 ContainerInputs 를 어긴다: {errs[:3]}")
                continue
            if d["image"] != img:
                problems.append(f"{name}: 주입 선언의 image 가 이미지 식별 라벨과 다르다")
                continue
            jobs = json.loads(job_raw) if job_raw else {"jobs": []}
            if list(validator("JobsDeclaration").iter_errors(jobs)) and job_raw:
                problems.append(f"{name}: 이미지 잡 선언이 JobsDeclaration을 어긴다")
                continue
            job_specs[img] = {job["name"]: job for job in jobs["jobs"]}
            # JobsDeclaration owns argv/config; compose them with the injection
            # declaration instead of maintaining duplicate paths in two labels.
            d = copy.deepcopy(d)
            for job_name, job in job_specs[img].items():
                if job.get("config") and job_name in d["jobs"]:
                    config = job["config"]
                    d["jobs"][job_name]["files"].append({"path": config["container_path"], "path_env": None,
                        "kind": "config", "schema": config["schema"], "directory": False, "required": True,
                        "opened_by": "start-process"})
            decls[img] = d
        try:
            job = job_specs[img].get(JOB_NAMES.get(name))
            service = facts(name, body or {}, img, decls[img], a.secrets_gid, job["argv"] if job else None)
            kind, _, profile = service["set"].partition(":")
            inputs = decls[img]["jobs" if kind == "job" else "roles"].get(profile)
            if inputs:
                schema_name = inputs["env_schema"]
                schema = load_schema(schema_name)
                environment = service["env"]
                # The legacy Ops server Env wraps its variables in `env`.
                inner = schema.get("properties", {}).get("env")
                document = environment
                if isinstance(inner, dict) and inner.get("type") == "object":
                    from openit_deploy.wiring.cli_check_config_contracts import ENV_SERVICES
                    wrap = next(wrap for contract, wrap in ENV_SERVICES.values() if contract == schema_name)
                    document = wrap(environment)
                for contract, value in [("CommonEnv", environment), (schema_name, document)]:
                    for error in validator(contract).iter_errors(value):
                        path = "/".join(map(str, error.absolute_path)) or "(최상위)"
                        problems.append(f"{name}: {contract} {path}: {error.validator}")
                if kind == "role":
                    for contract, document in typed_role_file_documents(body, inputs, cfg):
                        for error in validator(contract).iter_errors(document):
                            path = "/".join(map(str, error.absolute_path)) or "(최상위)"
                            problems.append(f"{name}: {contract} {path}: {error.validator}")
            for w in service["writable"]:   # mode 없는 tmpfs 는 이미지의 그 경로 소유·모드로 판정한다(컴포넌트 I8)
                if w["kind"] != "tmpfs" or "mode" in w:
                    continue
                if a.declarations_dir:
                    known = offline_dirs.get(img, {})
                    if w["target"] in known: w["image_dir"] = known[w["target"]]
                else:
                    key = (ref, w["target"])
                    if key not in dir_cache: dir_cache[key] = image_dir_of(ref, w["target"])
                    if dir_cache[key] is not _UNVERIFIED: w["image_dir"] = dir_cache[key]
            services.append(service)
        except FileBindingError as error:
            problems.append(f"{name}: {error}")
        except (KeyError, ValueError, OSError):
            problems.append(f"{name}: 선언한 환경 스키마·역할을 해석하지 못했다")
    if problems:
        print("\n".join("FAIL " + p for p in problems), file=sys.stderr)
        return 2
    r = call(container_inputs_check, "ContainerInputsCheckRequest", "ContainerInputsCheckResult", {"services": services, "declarations": decls})
    for v in r["violations"]:
        print(f"FAIL {v['rule']} {v['service']}: {v['detail']}")
    print(f"주입 대조: 서비스 {len(services)}개, 이미지 {len(decls)}개, 대조 {r['checked']}건, 어긋남 {len(r['violations'])}건")
    return 0 if r["status"] == "OK" else 1
