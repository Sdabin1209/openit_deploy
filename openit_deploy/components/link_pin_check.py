"""컴포넌트 link_pin_check: 각 영역의 잠금 파일에 적힌 openit-link 태그가 기준표(DEPLOY_LINK_TAG)와 같은지 대조한다. 입력 LinkPinCheckRequest, 출력 LinkPinCheckResult.
정본: 영역 이미지의 link 버전은 라벨이 아니라 각 영역의 잠금 파일이다(헤드 결정 U59, ADR 0046). 읽는 줄: (1) 주석이 아닌 줄의 `openit-link @ git+...@vX.Y.Z` 또는 `openit_link ... @vX.Y.Z` (requirements*.txt, *.lock), (2) Dockerfile 의 `ARG LINK_VERSION=vX.Y.Z`.
판정: 영역의 모든 핀이 기준과 같으면 MATCH, 하나라도 다르면 DIFF(어긋난 파일·태그를 낸다), 핀이 없으면 NO_PIN(link 를 쓰지 않거나 위치를 알 수 없다: 통과로 세지 않고 따로 센다). 파일 읽기(영역 main 브랜치의 git 내용)는 wiring 이 한다."""
from __future__ import annotations

import re

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import LinkPinCheckRequest, LinkPinCheckResult

PIN_LINE = re.compile(r"openit[-_]link\b[^#\n]*@(v\d+\.\d+\.\d+)\b", re.I)   # `openit-link @ git+ssh://...@vX` 와 `git+ssh://.../openit_link.git@vX` 두 모양
ARG_LINE = re.compile(r"^\s*ARG\s+LINK_VERSION\s*=\s*(v\d+\.\d+\.\d+)\b")


def pins_in(text: str) -> list:
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"): continue
        m = PIN_LINE.search(line) or ARG_LINE.match(line)
        if m: out.append(m.group(1))
    return out


def run(request: "LinkPinCheckRequest") -> "LinkPinCheckResult":
    want, areas = request["expected_tag"], []
    for a in request["areas"]:
        pins = [{"path": f["path"], "tag": t} for f in a["files"] for t in pins_in(f["text"])]
        status = "NO_PIN" if not pins else "MATCH" if all(p["tag"] == want for p in pins) else "DIFF"
        areas.append({"area": a["name"], "status": status, "pins": pins})
    n = lambda s: sum(1 for a in areas if a["status"] == s)
    return {"expected_tag": want, "areas": areas, "match": n("MATCH"), "diff": n("DIFF"), "no_pin": n("NO_PIN"), "status": "DIFF" if n("DIFF") else "MATCH" if n("MATCH") else "NO_PIN"}
