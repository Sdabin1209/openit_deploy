"""컴포넌트 config_contract_check: deploy 가 컨테이너에 주입하거나 배치하는 설정·환경 문서가 계약 스키마를 따르는지 판정한다(R7: 만드는 쪽이 내보내기 전에 검증). 입력 ConfigContractCheckRequest, 출력 ConfigContractCheckResult.
계약 스키마로 검증하는 함수(validators: 스키마 이름 -> 문서 -> [(위치, 메시지)])는 wiring 이 계약 패키지로 만들어 주입한다. 스키마가 없는 이름은 건너뛰지 않고 위반(NO_SCHEMA)으로 센다. 문서의 값(비밀일 수 있다)은 결과에 싣지 않고 위치와 검증기 이름만 싣는다."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import ConfigContractCheckRequest, ConfigContractCheckResult


def run(request: "ConfigContractCheckRequest", *, validators: dict) -> "ConfigContractCheckResult":
    violations = []
    for d in request["documents"]:
        v = validators.get(d["schema"])
        if v is None:
            violations.append({"label": d["label"], "schema": d["schema"], "where": "(스키마)", "message": "NO_SCHEMA: 기준 계약에 이 스키마가 없다"})
            continue
        for where, msg in v(d["document"]):
            violations.append({"label": d["label"], "schema": d["schema"], "where": where or "(최상위)", "message": msg})
    return {"checked": len(request["documents"]), "violations": violations, "ok": not violations}
