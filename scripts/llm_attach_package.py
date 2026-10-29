#!/usr/bin/env python3
"""학습 서버가 만든 진짜 LoRA 어댑터 두 개를 실제 LLM 데모용 모델 패키지(LORA_A, LORA_B)로 만든다(make-llm-package.sh --adapter-a ... 가 부른다).
출력 구조는 model-runtime make_neutral_package.py 와 같다: <OUT>/LORA_A/{adapter/,manifest.json}, LORA_B/..., SUMMARY.json (e2e_steps.py --llm-package 가 읽는다).
어댑터를 새로 만들지 않고 받은 파일을 그대로 복사한다. 거부 조건(하나라도 어기면 아무것도 쓰지 않고 종료 코드 2):
  - 어댑터 디렉터리에 adapter_model.safetensors 와 adapter_config.json 이 없다 / safetensors 머리말이 깨졌다 / LoRA 텐서가 없다
  - adapter_config.json 의 base_model_name_or_path 가 프로파일의 base_model 과 다르다 (다른 기반 모델의 어댑터는 얹을 수 없다)
  - 어댑터 순위 r 이 프로파일 engine.max_lora_rank 를 넘는다
  - 시스템 프롬프트 파일이 비었거나 UTF-8 이 아니다
확인하지 못하는 것: 텐서 모양이 기반 모델의 차원과 맞는지(vLLM 이 적재할 때 알게 된다), 학습 품질. 이 길은 평가하지 않는다.
--check-only: 위 검사만 하고(표준 라이브러리만 쓴다: model-runtime·boundary_contracts 를 불러오지 않는다) 아무것도 쓰지 않는다. 이미지 빌드 전에 빨리 거부하려고 demo.sh 가 먼저 부른다.
호출: PYTHONPATH 에 model-runtime 의 src 가 있고 boundary_contracts 가 설치된 python 으로.
"""
from __future__ import annotations
import argparse, json, shutil, struct, sys
from pathlib import Path
from types import SimpleNamespace

ROLES = ("LORA_A", "LORA_B")
IDS = {"LORA_A": "lora-a-attached", "LORA_B": "lora-b-attached"}
FILES = ("adapter_model.safetensors", "adapter_config.json")
CREATED_AT = "2026-01-01T00:00:00Z"   # 결정성을 위해 고정(만든 시각이 아니다)


def fail(msg):
    print(f"거부: {msg}", file=sys.stderr); sys.exit(2)


def check_adapter(role, d: Path, base: str, max_rank):
    for f in FILES:
        if not (d / f).is_file(): fail(f"{role}: 어댑터 디렉터리 {d} 에 {f} 가 없다")
    try:
        conf = json.loads((d / "adapter_config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError): fail(f"{role}: adapter_config.json 을 읽을 수 없다")
    if not isinstance(conf, dict): fail(f"{role}: adapter_config.json 의 최상위는 객체여야 한다")
    got = conf.get("base_model_name_or_path")
    if got != base:
        fail(f"{role}: 어댑터의 base_model_name_or_path({got!r})가 프로파일의 기반 모델({base!r})과 다르다. 다른 기반 모델로 학습한 어댑터는 얹을 수 없다")
    r = conf.get("r")
    if not isinstance(r, int) or (max_rank is not None and r > max_rank):
        fail(f"{role}: 어댑터 순위 r={r!r} 이 프로파일의 max_lora_rank({max_rank})를 넘거나 정수가 아니다")
    try:
        with open(d / "adapter_model.safetensors", "rb") as fh:
            n = struct.unpack("<Q", fh.read(8))[0]
            if n > 100_000_000: raise ValueError("머리말이 너무 크다")
            hdr = json.loads(fh.read(n))
    except (OSError, ValueError, struct.error) as e:
        fail(f"{role}: adapter_model.safetensors 머리말을 읽을 수 없다({type(e).__name__})")
    names = [k for k in hdr if k != "__metadata__"]
    if not any("lora_A" in k for k in names) or not any("lora_B" in k for k in names):
        fail(f"{role}: safetensors 에 lora_A/lora_B 텐서가 없다")
    return conf, len(names)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", help="--check-only 면 쓰지 않는다"); ap.add_argument("--profile", required=True)
    ap.add_argument("--adapter-a", required=True); ap.add_argument("--adapter-b", required=True)
    ap.add_argument("--prompt-a", required=True); ap.add_argument("--prompt-b", required=True)
    ap.add_argument("--vllm-version", default="0.31.0", help="serving_config.constraint.backend_version (서빙 이미지의 vLLM 과 같아야 한다)")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--revision", default="main"); ap.add_argument("--max-tokens", type=int, default=512)
    a = ap.parse_args()
    try: prof = json.loads(Path(a.profile).read_text(encoding="utf-8"))
    except (OSError, ValueError): fail(f"프로파일을 읽을 수 없다: {a.profile}")
    base = prof.get("base_model")
    if not base: fail("프로파일에 base_model 이 없다")
    max_rank = prof.get("engine", {}).get("max_lora_rank")
    ad = {"LORA_A": Path(a.adapter_a), "LORA_B": Path(a.adapter_b)}
    pr = {"LORA_A": Path(a.prompt_a), "LORA_B": Path(a.prompt_b)}
    confs, texts = {}, {}
    for r in ROLES:
        confs[r] = check_adapter(r, ad[r], base, max_rank)
        try: data = pr[r].read_bytes(); t = data.decode("utf-8")
        except (OSError, UnicodeDecodeError): fail(f"{r}: 시스템 프롬프트 파일을 읽을 수 없다: {pr[r]}")
        if not t.strip(): fail(f"{r}: 시스템 프롬프트 파일이 비어 있다: {pr[r]}")
        texts[r] = data
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


if __name__ == "__main__":
    main()
