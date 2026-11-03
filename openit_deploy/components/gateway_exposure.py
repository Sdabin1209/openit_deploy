"""컴포넌트 gateway_exposure: 영역 이미지의 라벨 io.openit.exposure(계약 Exposure)를 영역 게이트웨이에 마운트할 파일 내용으로 꺼낸다. 입력 GatewayExposureRequest, 출력 GatewayExposureResult.
왜 deploy 가 내용을 해석하지 않나: 경로·상류·허용 목록을 설정으로 바꾸는 일은 platform 의 영역 게이트웨이 이미지가 한다(진입점이 /etc/openit/exposure.json 을 읽는다). deploy 는 영역이 낸 선언을 그대로 건넬 뿐이다(구조 규칙 1).
선언이 계약을 따르는지는 내는 쪽(wiring)이 계약 validator 로 확인해 위반 목록을 넘긴다."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import GatewayExposureRequest, GatewayExposureResult


def run(request: "GatewayExposureRequest") -> "GatewayExposureResult":
    labels = request["labels"]
    if "io.openit.exposure" not in labels:
        return {"status": "NO_EXPOSURE_LABEL", "message": f"{request['service']} 이미지에 라벨 io.openit.exposure 가 없다(영역이 노출을 선언하지 않았다)"}
    if request.get("declaration_errors"):
        return {"status": "INVALID_EXPOSURE", "message": f"{request['service']}: Exposure 스키마 위반: {request['declaration_errors'][0]}"}
    return {"status": "OK", "exposure_json": labels["io.openit.exposure"]}
