#!/usr/bin/env python3
"""중립 LoRA 패키지(make_neutral_package.py 결과)의 시스템 프롬프트 자리표시자를 데모 입력 파일로 바꾸고 해시를 다시 계산한다.
model-runtime 의 make_neutral_package.py 는 프롬프트 파일을 인자로 받지 않는다(v0.6.1). 패키지 규칙(ModelPackageManifest.system_prompt, D75)은 그대로 지킨다:
어댑터 디렉터리 안의 파일이 adapter_hash 에 들어가므로 파일을 바꾸면 adapter_hash -> content_hash 순으로 다시 계산한다. 서빙 설정과 그 해시는 건드리지 않는다.
사용: apply_system_prompts.py <패키지 폴더> <LORA_A 프롬프트 파일> <LORA_B 프롬프트 파일> [--turn-engine-version 0.3.0]
--turn-engine-version: 매니페스트 lineage 에 적는 값(중립 패키지는 'none'이라 게이트 CONTRACT_COMPAT 가 반려한다. 게이트 기준 값으로 맞춘다).
이 프롬프트는 학습 서버 데이터의 system 메시지를 model-lab 리포의 prompts/ 에서 복사한 데모 입력이다. 학습된 어댑터와 짝이 되는지는 이 PC에서 확인하지 못했다."""
import argparse, json, pathlib, sys
from boundary_contracts.canonical import content_hash, directory_hash, file_hash

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("pkg"); ap.add_argument("prompt_a"); ap.add_argument("prompt_b"); ap.add_argument("--turn-engine-version", default="")
a = ap.parse_args()
root = pathlib.Path(a.pkg); summary = json.loads((root / "SUMMARY.json").read_text())
for role, src in (("LORA_A", a.prompt_a), ("LORA_B", a.prompt_b)):
    d = root / role; mf = json.loads((d / "manifest.json").read_text())
    data = pathlib.Path(src).read_bytes()
    assert data.strip(), f"{src} 가 비어 있다"
    (d / "adapter" / mf["system_prompt"]["path"]).write_bytes(data)
    mf["system_prompt"]["sha256"] = file_hash(d / "adapter" / mf["system_prompt"]["path"])
    mf["adapter_hash"] = directory_hash(d / "adapter")
    if a.turn_engine_version: mf["lineage"]["turn_engine_version"] = a.turn_engine_version
    mf.pop("content_hash", None); mf["content_hash"] = content_hash(mf)
    (d / "manifest.json").write_text(json.dumps(mf, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    summary[role].update(adapter_hash=mf["adapter_hash"], content_hash=mf["content_hash"], system_prompt_sha256=mf["system_prompt"]["sha256"])
(root / "SUMMARY.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
print(json.dumps({r: summary[r]["system_prompt_sha256"] for r in ("LORA_A", "LORA_B")}))
