# 서버에서 도는 일회성 컨테이너 안(파이썬 표준 라이브러리만): 표준 입력의 JSON({root, tokens:{이름: 토큰}})을 볼륨에 쓴다.
# 루트 인증서(공개) -> /r/root_ca.crt (644). 일회용 토큰 -> /t/<이름>.ott (640, 소유자는 그 인증서 컨테이너의 uid: 영역 DB(<서비스>-db) 999, 나머지 1000).
# 프로비저너 비밀은 여기 오지 않는다(토큰만). 값은 출력하지 않는다.
import base64, json, os, sys
d = json.loads(base64.b64decode(sys.stdin.read()))   # base64: Ansible 이 JSON 문자열을 구조로 바꾸지 않게 한다
open("/r/root_ca.crt", "w").write(d["root"]); os.chmod("/r/root_ca.crt", 0o644)
for n, t in d["tokens"].items():
    path = "/t/%s.ott" % n
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(fd, "w") as f:
        f.write(t)
    uid = 999 if n.endswith("-db") else 1000
    os.chown(path, uid, uid); os.chmod(path, 0o640)
print("tokens", len(d["tokens"]))
