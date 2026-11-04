"""wiring/진입: gen-db-secrets.py (--image 이미지 | --declaration 파일) --db-host 호스트 --accounts-dir 폴더 --urls-dir 폴더
영역 DB 이미지의 라벨 io.openit.database(계약 DatabaseDeclaration)대로 계정 암호 파일(DB 컨테이너의 DB_ACCOUNT_SECRETS_DIR 에 줄 폴더)과 접속 URI 파일(영역 컨테이너의 <url_env> 에 줄 폴더, 파일 이름 = 환경 변수 이름)을 만든다.
이미 있는 계정 암호 파일은 그대로 쓴다(멱등: 다시 실행해도 암호가 바뀌지 않는다. 바꾸려면 파일을 지운다). 값은 출력하지 않고 파일 이름만 알린다(D84).
종료 코드 0 성공, 1 선언 없음·위반."""
import argparse
import json
import os
import pathlib
import secrets
import sys

from openit_deploy.components import db_secrets
from openit_deploy.wiring.call import call
from openit_deploy.wiring.cli_gen_jobs import image_labels


def load_declaration(args, labels_of=image_labels) -> dict:
    if args.declaration:
        raw = pathlib.Path(args.declaration).read_text(encoding="utf-8")
    else:
        raw = labels_of(args.image).get("io.openit.database")
        if raw is None:
            raise SystemExit(f"이미지에 라벨 io.openit.database 가 없다(영역이 DB 를 선언하지 않았다): {args.image}")
    decl = json.loads(raw)
    from boundary_contracts import validator
    errs = [e.message for e in validator("DatabaseDeclaration").iter_errors(decl)][:1]
    if errs:
        raise SystemExit(f"DatabaseDeclaration 스키마 위반: {errs[0]}")
    return decl


def _write(path: pathlib.Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # 비밀: 만들 때부터 600
    with os.fdopen(fd, "w") as f:
        f.write(text)


def main(argv, labels_of=image_labels) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--image"); g.add_argument("--declaration")
    ap.add_argument("--db-host", required=True); ap.add_argument("--accounts-dir", required=True); ap.add_argument("--urls-dir", required=True)
    a = ap.parse_args(argv)
    decl = load_declaration(a, labels_of)
    adir, udir = pathlib.Path(a.accounts_dir), pathlib.Path(a.urls_dir)
    passwords = {}
    for acct in decl["accounts"]:
        f = adir / acct["name"]
        passwords[acct["name"]] = f.read_text(encoding="utf-8").strip() if f.is_file() and f.stat().st_size else secrets.token_hex(24)
    res = call(db_secrets, "DbSecretsRequest", "DbSecretsResult", {"db_host": a.db_host, "declaration": decl, "passwords": passwords})
    for name, body in res["account_files"].items():
        _write(adir / name, body)
    for env, body in res["url_files"].items():
        _write(udir / env, body)
    print(f"계정 {len(res['account_files'])}개, 접속 파일 {len(res['url_files'])}개: {', '.join(sorted(res['url_files']))}")
    return 0
