"""컴포넌트 db_secrets: 영역 DB 이미지가 선언한 계정(라벨 io.openit.database, 계약 DatabaseDeclaration)에서 비밀 파일 내용을 만든다(계약 3.4.10).
왜: DB 의 계정·데이터베이스·권한은 데이터 주인 영역이 안다. deploy 는 선언대로 계정마다 암호 파일(DB 컨테이너용)과 접속 URI 파일(그 계정을 쓰는 영역 컨테이너의 <url_env>)을 같은 암호로 만들어 줄 뿐이다(구조 규칙 1·4).
접속 URI: libpq 표준 URI, sslmode=verify-full(서버 인증서 이름 = db_host; 계약이 verify-full 을 요구한다). 암호는 hex 이므로 URI 인코딩이 필요 없지만 방어로 quote 한다.
난수는 만들지 않는다(passwords 로 받는다): 같은 입력에 같은 출력이라야 시험하기 쉽고 여러 번 실행해도 안전하다(D39)."""
from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from openit_deploy.types.deploy_types import DbSecretsRequest, DbSecretsResult

DEFAULT_ROOT_CA = "/etc/openit/pki/root_ca.crt"


def run(request: "DbSecretsRequest") -> "DbSecretsResult":
    decl, pw = request["declaration"], request["passwords"]
    missing = [a["name"] for a in decl["accounts"] if a["name"] not in pw]
    if missing:
        raise ValueError(f"암호가 없는 계정: {missing}")
    ca = request.get("root_ca_path", DEFAULT_ROOT_CA)
    account_files, url_files = {}, {}
    for a in decl["accounts"]:
        account_files[a["name"]] = pw[a["name"]] + "\n"
        uri = f"postgresql://{a['name']}:{quote(pw[a['name']], safe='')}@{request['db_host']}:{decl['port']}/{a['database']}?sslmode=verify-full&sslrootcert={quote(ca, safe='/')}\n"
        for env in a["url_env"]:
            if env in url_files:
                raise ValueError(f"환경 변수 {env} 를 두 계정이 쓴다")
            url_files[env] = uri
    return {"account_files": account_files, "url_files": url_files}
