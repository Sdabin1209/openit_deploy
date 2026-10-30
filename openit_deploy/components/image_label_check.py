"""컴포넌트 image_label_check: 이미지 라벨(docker inspect 의 .Config.Labels)이 계약 ImageLabels 를 따르는지 판정한다.
입력 ImageLabelCheckRequest, 출력 ImageLabelCheckResult. 계약 스키마로 검증하는 함수(validators)는 wiring 이 주입한다(스키마 정본은 계약 패키지이고 deploy 는 사본을 두지 않는다).
io.openit.jobs·io.openit.exposure 값은 JSON 문자열이라 풀어서 JobsDeclaration·Exposure 로 한 번 더 검증한다(contentSchema 는 주석이라 검증기가 강제하지 않는다)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import ImageLabelCheckRequest, ImageLabelCheckResult


INNER = (("io.openit.jobs", "JobsDeclaration"), ("io.openit.exposure", "Exposure"))


def run(request: "ImageLabelCheckRequest", *, validators: dict) -> "ImageLabelCheckResult":
    """validators: {계약 타입 이름: 문서 -> [위반 설명(위치, 메시지)]}. 값이 없는 타입은 검사하지 않는다(그 스키마가 없는 옛 계약)."""
    import json
    labels = request.get("labels") or {}   # docker inspect 는 라벨이 없으면 null 을 낸다
    errs = [f"{loc}: {msg[:160]}" if loc else msg[:200] for loc, msg in validators["ImageLabels"](labels)]
    for key, typ in INNER:
        if key in labels and typ in validators:
            try: inner = json.loads(labels[key])
            except (ValueError, TypeError): errs.append(f"{key}: JSON 이 아니다"); continue
            errs += [f"{key}/{loc}: {msg[:120]}" for loc, msg in validators[typ](inner)]
    return {"ok": not errs, "errors": errs}
