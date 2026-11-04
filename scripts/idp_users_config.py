#!/usr/bin/env python3
"""accounts.test.conf(`<사용자> <그룹,그룹|->`)와 시험 암호 파일에서 IdentityUsersConfig(계약 3.4.16) 설정 파일을 만들고 계약 스키마로 검증한다. 암호 값은 설정에 넣지 않는다(파일 경로만, D84).
사용: idp_users_config.py --accounts F --passwords DIR --secrets-out DIR --out FILE --compose-out FILE   종료 코드 0, 1 입력 없음·계약 위반"""
import argparse, json, os, pathlib, shutil, sys

SECRET_DIR = "/run/secrets"   # compose 비밀이 파일로 오는 표준 위치(D84). 비밀 이름은 idp-user-<사용자>


def build(accounts_text: str):
    users = []
    for line in accounts_text.splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"): continue
        user = parts[0]; groups = [] if len(parts) < 2 or parts[1] == "-" else parts[1].split(",")
        users.append({"username": user, "email": f"{user}@test.invalid", "groups": groups, "password_file": f"{SECRET_DIR}/idp-user-{user}"})
    return {"users": users}


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    for k in ("accounts", "passwords", "secrets_out", "out", "compose_out"): ap.add_argument("--" + k.replace("_", "-"), required=True)
    a = ap.parse_args(argv)
    cfg = build(pathlib.Path(a.accounts).read_text(encoding="utf-8"))
    from boundary_contracts import validator
    errs = [e.message for e in validator("IdentityUsersConfig").iter_errors(cfg)][:1]
    if errs: print(f"IdentityUsersConfig 위반: {errs[0]}", file=sys.stderr); return 1
    out = pathlib.Path(a.secrets_out); out.mkdir(parents=True, exist_ok=True)
    for u in cfg["users"]:
        src = pathlib.Path(a.passwords) / f"idp-test-{u['username']}-password"
        if not src.is_file(): print(f"시험 사용자 암호 파일이 없다: {src.name}", file=sys.stderr); return 1
        dst = out / u["username"]; shutil.copyfile(src, dst); os.chmod(dst, 0o640)
    ov = {"services": {"job-identity-register-users": {"secrets": [f"idp-user-{u['username']}" for u in cfg["users"]]}},
          "secrets": {f"idp-user-{u['username']}": {"file": str((out / u["username"]).resolve())} for u in cfg["users"]}}
    pathlib.Path(a.compose_out).write_text(json.dumps(ov, ensure_ascii=False, indent=1), encoding="utf-8")   # compose 덧씌우기(JSON 은 YAML 의 부분집합): 사용자 수만큼의 비밀 파일 연결. 값은 없다
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)   # 암호 값이 없는 설정이다(경로만)
    with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(cfg, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
