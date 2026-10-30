"""wiring/진입: 학습 서버가 만든 진짜 LoRA 어댑터 두 개를 실제 LLM 데모용 모델 패키지(LORA_A, LORA_B)로 만든다(make-llm-package.sh --adapter-a ... 가 부른다).
출력 구조는 model-runtime make_neutral_package.py 와 같다: <OUT>/LORA_A/{adapter/,manifest.json}, LORA_B/..., SUMMARY.json (e2e_steps.py --llm-package 가 읽는다).
어댑터를 새로 만들지 않고 받은 파일을 그대로 복사한다. 어댑터 판정(거부 조건)은 컴포넌트 adapter_check 가 하고, 파일 읽기·복사·매니페스트 쓰기는 여기서 한다.
알려진 한계: 매니페스트의 serving_config 를 만들려고 model_runtime(PYTHONPATH)을 import 한다(구조 규칙 1 위반, 기존 동작을 바꾸지 않았다). 변경 요청: docs/change-requests/CR-U400-attach-package-model-runtime-import.md. 종료 코드 2: 거부."""
from __future__ import annotations
import argparse, json, shutil, struct, sys
from pathlib import Path
from types import SimpleNamespace

from openit_deploy.components import adapter_check
from openit_deploy.wiring.call import call

ROLES = ("LORA_A", "LORA_B")
IDS = {"LORA_A": "lora-a-attached", "LORA_B": "lora-b-attached"}
FILES = ("adapter_model.safetensors", "adapter_config.json")
CREATED_AT = "2026-01-01T00:00:00Z"   # 결정성을 위해 고정(만든 시각이 아니다)


def fail(msg):
    print(f"거부: {msg}", file=sys.stderr); sys.exit(2)


def adapter_facts(role, d: Path, prompt: Path) -> dict:
    """어댑터 디렉터리와 프롬프트 파일에서 판정에 필요한 사실만 읽는다."""
    has = {f: (d / f).is_file() for f in FILES}
    conf = None
    if has["adapter_config.json"]:
        try:
            x = json.loads((d / "adapter_config.json").read_text(encoding="utf-8"))
            conf = x if isinstance(x, dict) else None
        except (OSError, ValueError): conf = None
    names = None
    if has["adapter_model.safetensors"]:
        try:
            with open(d / "adapter_model.safetensors", "rb") as fh:
                n = struct.unpack("<Q", fh.read(8))[0]
                if n > 100_000_000: raise ValueError("머리말이 너무 크다")
                hdr = json.loads(fh.read(n))
            names = [k for k in hdr if k != "__metadata__"]
        except (OSError, ValueError, struct.error): names = None
    try: data = prompt.read_bytes(); text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError): fail(f"{role}: 시스템 프롬프트 파일을 읽을 수 없다: {prompt}")
    return {"role": role, "dir": str(d), "has_safetensors": has["adapter_model.safetensors"], "has_config": has["adapter_config.json"], "config": conf,
            "tensor_names": names, "prompt_path": str(prompt), "prompt_text": text}, data


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out", help="--check-only 면 쓰지 않는다"); ap.add_argument("--profile", required=True)
    ap.add_argument("--adapter-a", required=True); ap.add_argument("--adapter-b", required=True)
    ap.add_argument("--prompt-a", required=True); ap.add_argument("--prompt-b", required=True)
    ap.add_argument("--vllm-version", default="0.31.0", help="serving_config.constraint.backend_version (서빙 이미지의 vLLM 과 같아야 한다)")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--revision", default="main"); ap.add_argument("--max-tokens", type=int, default=512)
    a = ap.parse_args(argv)
    try: prof = json.loads(Path(a.profile).read_text(encoding="utf-8"))
    except (OSError, ValueError): fail(f"프로파일을 읽을 수 없다: {a.profile}")
    base = prof.get("base_model")
    if not base: fail("프로파일에 base_model 이 없다")
    max_rank = prof.get("engine", {}).get("max_lora_rank")
    ad = {"LORA_A": Path(a.adapter_a), "LORA_B": Path(a.adapter_b)}
    pr = {"LORA_A": Path(a.prompt_a), "LORA_B": Path(a.prompt_b)}
    facts, texts = [], {}
    for r in ROLES:
        f, texts[r] = adapter_facts(r, ad[r], pr[r]); facts.append(f)
    res = call(adapter_check, "AdapterCheckRequest", "AdapterCheckResult", {"base_model": base, "max_lora_rank": max_rank, "adapters": facts})
    if not res["ok"]: fail(res["rejection"])
    confs = {f["role"]: (f["config"], res["tensor_counts"][f["role"]]) for f in facts}
    if a.check_only:
        print(f"검사 통과: 두 어댑터가 {base}(순위 한도 {max_rank})에 맞는다. 텐서 모양이 기반 모델과 맞는지는 vLLM 적재 때 알게 된다(미확인)."); return
    import model_runtime as mr
    from boundary_contracts import PIPELINE_SCHEMA_VERSION, validator
    from boundary_contracts.action_rules import load_rules
    from boundary_contracts.canonical import content_hash, directory_hash, file_hash, sha256_hash
    mr.load_profile(Path(a.profile))
    out = Path(a.out)
    backend = SimpleNamespace(name="vllm", version=a.vllm_version, supported_features=frozenset(mr.DEFAULT_SUPPORTED_FEATURES))
    summary = {}
    for r in ROLES:
        d = out / r
        (d / "adapter").mkdir(parents=True, exist_ok=True)
        for f in FILES: shutil.copyfile(ad[r] / f, d / "adapter" / f)   # 그 밖의 파일은 복사하지 않는다(해시에 안 들어간다)
        (d / "adapter" / "system_prompt.txt").write_bytes(texts[r])
        cfg = mr.fake_serving_config(backend)
        cfg["decoding"] = {"constraint_mode": "constrained" if r == "LORA_A" else "none", "temperature": 0, "retry_temperature": 0.7, "seed": 1000, "max_tokens": a.max_tokens}
        m = {"pipeline_schema_version": PIPELINE_SCHEMA_VERSION, "package_id": IDS[r], "version": "attached-" + directory_hash(d / "adapter").split(":")[-1][:12], "role": r,
             "created_at": CREATED_AT, "runtime_contract_version": mr.SUPPORTED_RUNTIME_CONTRACT_VERSION,
             "base_model": {"id": base, "revision": a.revision}, "adapter_hash": directory_hash(d / "adapter"),
             "serving_config": cfg, "serving_config_hash": sha256_hash(cfg),
             "system_prompt": {"path": "system_prompt.txt", "sha256": file_hash(d / "adapter" / "system_prompt.txt")},
             "lineage": {"dataset": {"id": "attached-no-dataset", "version": "0", "content_hash": sha256_hash({"attached": True})},
                         "training_run_id": "attached-external", "action_rules_version": load_rules()["rules_version"], "model_runtime_version": mr.RUNTIME_VERSION},
             "eval_report_ref": "attached-no-eval",
             "ext": {"deploy": {"attached": True, "evaluated": False, "adapter_config_r": confs[r][0].get("r"), "lora_tensors": confs[r][1],
                                "note": "학습 서버에서 가져온 어댑터를 그대로 얹었다. 이 길은 평가하지 않았고 릴리스 후보로 승인된 것이 아니다."}}}
        m["content_hash"] = content_hash(m)
        validator("ModelPackageManifest").validate(m)
        (d / "manifest.json").write_text(json.dumps(m, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        summary[r] = {"package_id": m["package_id"], "version": m["version"], "adapter_hash": m["adapter_hash"], "content_hash": m["content_hash"]}
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1, sort_keys=True))
