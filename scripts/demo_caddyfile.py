#!/usr/bin/env python3
"""데모 전용 gateway 설정 사본을 만든다: config/Caddyfile 의 `/config.json` 404 블록 하나만 kiosk-frontend 로 넘기게 바꾼다.
사용: demo_caddyfile.py <운영 Caddyfile> <출력 경로>
왜 사본인가: 운영 config/Caddyfile 은 /config.json 을 404 로 막는다(한 컨테이너가 모든 키오스크에 같은 토큰을 내면 기기별 토큰의 의미가 없다, scripts/kiosk-add-device.sh 머리말). 데모만 풀고 운영 파일은 그대로 둔다.
블록이 정확히 한 번 있지 않으면 실패한다(운영 설정이 바뀌었는데 사본이 조용히 틀어지는 것을 막는다)."""
import sys

OLD = '\thandle /config.json {\n\t\trespond "not found" 404\n\t}\n'
NEW = ('\thandle /config.json {   # 데모 전용: 기기 설정을 kiosk-frontend 가 CONFIG_FILE 로 낸다(test/compose.demo-kiosk.yaml)\n'
       '\t\treverse_proxy kiosk-frontend:8080 {\n\t\t\theader_up -X-Openit-User\n\t\t\theader_up -Authorization\n\t\t}\n\t}\n')


def main(argv):
    if len(argv) != 3:
        print(__doc__, file=sys.stderr); return 2
    src = open(argv[1], encoding="utf-8").read()
    if src.count(OLD) != 1:
        print(f"/config.json 404 블록이 정확히 한 번 있어야 한다(찾은 수 {src.count(OLD)}): {argv[1]}", file=sys.stderr); return 1
    open(argv[2], "w", encoding="utf-8").write(src.replace(OLD, NEW))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
