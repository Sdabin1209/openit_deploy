#!/usr/bin/env python3
"""같은 망 클라이언트 컨테이너 안에서 도는 한 번짜리 HTTP/TCP 탐침(표준 라이브러리만). scripts/client-probe.sh 가 UTIL 이미지에 마운트해 돌린다.
왜 컨테이너 밖 파일인가: deploy 는 실행 중인 영역 컨테이너 안으로 들어가지 않는다(구조 규칙 1·6, CONVENTIONS 13절). 영역 사이의 도달은 출발 영역과 같은 망에 붙은 클라이언트가 그 영역 게이트웨이(https://<서비스>)로 부르는 것으로 본다.
모드: body URL        -> 본문을 그대로 낸다(HTTP 오류면 종료 1)
      code URL        -> '<상태> <본문>' 한 줄(HTTP 오류도 상태로 낸다, 연결 실패면 종료 1)
      http URL SECS   -> ok(본문이 ok 로 시작하거나 JSON status==ok) / bad(응답은 왔으나 다르다) / unreachable(연결 실패·시간 초과·이름 안 풀림)
      tcp HOST PORT SECS -> ok / unreachable"""
import json, socket, sys, urllib.error, urllib.request


def main(argv):
    mode, a = argv[0], argv[1:]
    if mode == "body":
        sys.stdout.write(urllib.request.urlopen(a[0], timeout=5).read().decode()); return 0
    if mode == "code":
        try:
            r = urllib.request.urlopen(a[0], timeout=5); print(r.status, r.read().decode())
        except urllib.error.HTTPError as e:
            print(e.code, e.read().decode())
        return 0
    if mode == "http":
        try:
            b = urllib.request.urlopen(a[0], timeout=float(a[1])).read().decode()
        except urllib.error.HTTPError:
            print("bad"); return 0
        except (urllib.error.URLError, OSError):
            print("unreachable"); return 0
        try: good = b.strip().startswith("ok") or json.loads(b).get("status") == "ok"
        except ValueError: good = False
        print("ok" if good else "bad"); return 0
    if mode == "tcp":
        try: socket.create_connection((a[0], int(a[1])), timeout=float(a[2])); print("ok")
        except OSError: print("unreachable")
        return 0
    print("모르는 모드: " + mode, file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
