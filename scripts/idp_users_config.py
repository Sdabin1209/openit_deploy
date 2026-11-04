#!/usr/bin/env python3
"""accounts.test.conf(`<사용자> <그룹,그룹|->`)와 시험 암호 파일에서 IdentityUsersConfig(계약 3.4.16) 설정 파일을 만들고 계약 스키마로 검증한다. 암호 값은 설정에 넣지 않는다(파일 경로만, D84).
사용: idp_users_config.py --accounts F --passwords DIR --secrets-out DIR --out FILE   종료 코드 0, 1 입력 없음·계약 위반"""
import argparse, json, os, pathlib, shutil, sys

CONTAINER_DIR = "/run/idp-users"   # compose.yaml job-identity-register-users 가 시험 암호 폴더를 마운트하는 곳


def build(accounts_text: str):
    users = []
    for line in accounts_text.splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"): continue
        user = parts[0]; groups = [] if len(parts) < 2 or parts[1] == "-" else parts[1].split(",")
        users.append({"username": user, "email": f"{user}@test.invalid", "groups": groups, "password_file": f"{CONTAINER_DIR}/{user}"})
    return {"users": users}


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    for k in ("accounts", "passwords", "secrets_out", "out"): ap.add_argument("--" + k.replace("_", "-"), required=True)
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
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)   # 암호 값이 없는 설정이다(경로만)
    with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(cfg, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
