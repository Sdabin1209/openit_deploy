"""컴포넌트 caddyfile_demo: 운영 Caddyfile 텍스트에서 `/config.json` 404 블록 하나만 kiosk-frontend 로 넘기게 바꾼 데모용 사본 텍스트를 만든다.
입력 CaddyfileDemoRequest, 출력 CaddyfileDemoResult. 왜 사본인가: 운영 config/Caddyfile 은 /config.json 을 404 로 막는다(한 컨테이너가 모든 키오스크에 같은 토큰을 내면 기기별 토큰의 의미가 없다, scripts/kiosk-add-device.sh 머리말). 데모만 풀고 운영 파일은 그대로 둔다.
블록이 정확히 한 번 있지 않으면 사본을 만들지 않는다(운영 설정이 바뀌었는데 사본이 조용히 틀어지는 것을 막는다): 결과 status=BLOCK_NOT_UNIQUE 와 찾은 수."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import CaddyfileDemoRequest, CaddyfileDemoResult


OLD = '\thandle /config.json {\n\t\trespond "not found" 404\n\t}\n'
NEW = ('\thandle /config.json {   # 데모 전용: 기기 설정을 kiosk-frontend 가 CONFIG_FILE 로 낸다(test/compose.demo-kiosk.yaml)\n'
       '\t\treverse_proxy kiosk-frontend:8080 {\n\t\t\theader_up -X-Openit-User\n\t\t\theader_up -Authorization\n\t\t}\n\t}\n')


def run(request: "CaddyfileDemoRequest") -> "CaddyfileDemoResult":
    n = request["caddyfile"].count(OLD)
    if n != 1:
        return {"status": "BLOCK_NOT_UNIQUE", "found": n}
    return {"status": "OK", "found": 1, "demo_caddyfile": request["caddyfile"].replace(OLD, NEW)}
