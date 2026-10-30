"""wiring: 컴포넌트 호출의 공통 모양. 입력을 스키마로 검증하고 → 컴포넌트를 부르고 → 출력도 스키마로 검증한다(내는 쪽이 검증, R7).
컴포넌트가 낸 출력을 여기서 검증하는 것은 컴포넌트 시험을 대신하는 안전망이고, 받는 컴포넌트는 다시 검증하지 않는다."""
from openit_deploy.wiring.schema_check import check


def call(component, request_type: str, result_type: str, request: dict, **injected):
    check(request_type, request)
    result = component.run(request, **injected)
    check(result_type, result)
    return result
