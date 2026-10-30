"""컴포넌트 adapter_check: 학습 서버에서 가져온 LoRA 어댑터 한 쌍(LORA_A, LORA_B)이 프로파일의 기반 모델·순위 한도에 얹을 수 있는지 판정한다. 입력 AdapterCheckRequest, 출력 AdapterCheckResult.
거부 조건(하나라도 어기면 패키지를 만들지 않는다): 어댑터 디렉터리에 adapter_model.safetensors 와 adapter_config.json 이 없다 / safetensors 머리말이 깨졌다 / LoRA 텐서(lora_A, lora_B)가 없다 /
adapter_config.json 의 base_model_name_or_path 가 프로파일의 base_model 과 다르다(다른 기반 모델의 어댑터는 얹을 수 없다) / 순위 r 이 정수가 아니거나 프로파일의 max_lora_rank 를 넘는다 / 시스템 프롬프트가 비어 있다.
파일 읽기(바깥 자원)는 wiring 이 하고 그 사실(facts)만 받는다. 텐서 모양이 기반 모델과 맞는지는 vLLM 적재 때 알게 된다(이 컴포넌트는 알지 못한다)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import AdapterCheckRequest, AdapterCheckResult



def _check(a: dict, base: str, max_rank):
    role = a["role"]
    for f, present in (("adapter_model.safetensors", a["has_safetensors"]), ("adapter_config.json", a["has_config"])):
        if not present: return f"{role}: 어댑터 디렉터리 {a['dir']} 에 {f} 가 없다"
    conf = a["config"]
    if conf is None: return f"{role}: adapter_config.json 을 읽을 수 없다"
    got = conf.get("base_model_name_or_path")
    if got != base:
        return f"{role}: 어댑터의 base_model_name_or_path({got!r})가 프로파일의 기반 모델({base!r})과 다르다. 다른 기반 모델로 학습한 어댑터는 얹을 수 없다"
    r = conf.get("r")
    if not isinstance(r, int) or isinstance(r, bool) or (max_rank is not None and r > max_rank):
        return f"{role}: 어댑터 순위 r={r!r} 이 프로파일의 max_lora_rank({max_rank})를 넘거나 정수가 아니다"
    names = a["tensor_names"]
    if names is None: return f"{role}: adapter_model.safetensors 머리말을 읽을 수 없다"
    if not any("lora_A" in k for k in names) or not any("lora_B" in k for k in names):
        return f"{role}: safetensors 에 lora_A/lora_B 텐서가 없다"
    if not a["prompt_text"].strip(): return f"{role}: 시스템 프롬프트 파일이 비어 있다: {a['prompt_path']}"
    return None


def run(request: "AdapterCheckRequest") -> "AdapterCheckResult":
    for a in request["adapters"]:
        why = _check(a, request["base_model"], request.get("max_lora_rank"))
        if why: return {"ok": False, "rejection": why}
    return {"ok": True, "tensor_counts": {a["role"]: len(a["tensor_names"]) for a in request["adapters"]}}
