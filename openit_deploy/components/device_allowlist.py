"""컴포넌트 device_allowlist: 기기 인증서 허용 목록(계약 DeviceAllowlist, PUBLIC_API F절, D136) 한 번의 고침을 판정한다. 입력 DeviceAllowlistEditRequest, 출력 DeviceAllowlistEditResult.
파일·잠금은 모른다: 지금 목록 문서(current)와 명령을 받아 쓸 새 문서(WRITE) / 출력할 줄(PRINT) / 있음·없음(YES·NO) / 할 일 없음(NOOP) / 거부(REJECTED, 이유 한 줄)를 낸다.
잠금(fcntl.flock)·원자적 교체(임시 파일 + fsync + os.replace)·권한은 wiring/cli_device_allowlist.py 가 한다(ADR 0069).
왜 이 모양인가:
- 쓰기 전에 계약 패키지의 검증기로 검증하고(R7: 만드는 쪽이 검증한다), 어기면 REJECTED 를 내서 파일을 바꾸지 않게 한다. 같은 기기 ID 는 한 항목으로 합친다(계약: device_id 중복은 입구가 시작을 거부한다).
- 일련번호는 RFC 5280 4.1.2.2 대로 양의 정수를 앞자리 0 없는 소문자 16진수로 맞춘다(계약 DeviceAllowlist.serials 형식)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import DeviceAllowlistEditRequest, DeviceAllowlistEditResult

import re

from boundary_contracts import validator

SERIAL = re.compile(r"^[0-9a-fA-F]{1,40}$")   # 계약 DeviceAllowlist: 최대 20옥텟 = 16진수 40자리


class Rejected(Exception):
    pass


def norm_serial(s: str) -> str:
    """RFC 5280 4.1.2.2: 일련번호는 양의 정수. 앞자리 0 없는 소문자 16진수로 맞춘다(계약 DeviceAllowlist.serials 형식)."""
    if not SERIAL.match(s): raise Rejected(f"일련번호 형식 오류(16진수 1~40자리): {s!r}")
    s = s.lower().lstrip("0")
    if not s: raise Rejected("일련번호 0 은 허용하지 않는다(RFC 5280: 양의 정수)")
    return s


def contract_errors(doc: dict) -> list:
    errs = [f"/{'/'.join(map(str, e.path))}: {e.validator} 위반" for e in validator("DeviceAllowlist").iter_errors(doc)]
    ids = [d["device_id"] for d in doc.get("devices", [])]
    if len(ids) != len(set(ids)): errs.append("device_id 가 겹친다")
    return errs


def _write(doc: dict) -> "DeviceAllowlistEditResult":
    errs = contract_errors(doc)
    if errs:
        return {"status": "REJECTED", "message": "기기 허용 목록이 계약 DeviceAllowlist 를 어긴다: " + "; ".join(errs)}
    return {"status": "WRITE", "doc": doc}


def run(request: "DeviceAllowlistEditRequest") -> "DeviceAllowlistEditResult":
    cmd, cur = request["command"], request["current"]
    if cmd == "init":
        return {"status": "NOOP"} if request["exists"] else _write({"schema_version": 1, "devices": []})
    devs = {x["device_id"]: x for x in cur["devices"]} if "devices" in cur else {}
    did = request.get("device_id")
    try:
        if cmd == "add":
            ser = norm_serial(request["serial"])
            e = devs.setdefault(did, {"device_id": did, "serials": []})
            if ser not in e["serials"]: e["serials"].append(ser)
        elif cmd == "remove-serial":
            ser = norm_serial(request["serial"])
            if did not in devs or ser not in devs[did]["serials"]: raise Rejected(f"없는 일련번호: {did}")
            devs[did]["serials"].remove(ser)
            if not devs[did]["serials"]: del devs[did]   # 계약: serials 는 1개 이상. 마지막 일련번호를 빼면 기기가 폐기된 것이다
        elif cmd == "remove":
            devs.pop(did, None)
        elif cmd == "has":
            return {"status": "YES" if did in devs else "NO"}
        elif cmd == "list":
            return {"status": "PRINT", "lines": sorted(devs)}
        elif cmd == "serials":
            return {"status": "PRINT", "lines": list(devs.get(did, {"serials": []})["serials"])}
    except Rejected as e:
        return {"status": "REJECTED", "message": str(e)}
    return _write({"schema_version": 1, "devices": [devs[k] for k in sorted(devs)]})
