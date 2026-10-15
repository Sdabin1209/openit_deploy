#!/usr/bin/env python3
"""복구한 저장소를 실제 서비스의 HTTP로 다시 읽어 검증한다(E2E 9단계)."""
import argparse, json, pathlib, sys
import boundary_contracts as bc
from boundary_contracts import canonical
from boundary_contracts.clients import HttpQuestionReader, HttpTraceIngest, HttpModelRegistry, HttpReleaseReader
ap = argparse.ArgumentParser(); ap.add_argument("--secrets"); ap.add_argument("--ports"); ap.add_argument("--work"); ap.add_argument("--run-id")
a = ap.parse_args(); P = json.loads(a.ports); W = pathlib.Path(a.work)
T = lambda n: (pathlib.Path(a.secrets) / "tokens" / n).read_text().strip()
S = json.loads((W / "state.json").read_text()); u = lambda k: f"http://127.0.0.1:{P[k]}"
qa = HttpQuestionReader(u("qa"), T("qa-read-synthetic-data"))
vs = qa.list_versions(f"qs-{a.run_id}")[0]; assert [v["version"] for v in vs] == ["1", "2"], vs
for v in vs: assert canonical.content_hash(qa.get_question_bank(v)) == v["content_hash"]
r = HttpTraceIngest(u("ops"), T("ops-ingest-survey-service")).send(S["trace_env"]); assert r["status"] == "DUPLICATE", r
mr = HttpModelRegistry(u("mr"), T("model-registry-read-release-gate")); pid = S["lora"]["LORA_A"]["id"]
m = mr.get_manifest(pid, "1"); assert m["content_hash"] == S["lora"]["LORA_A"]["content_hash"]
p = mr.open_adapter(pid, "1", dest=W / "restored-adapter"); assert canonical.directory_hash(p) == m["adapter_hash"]
ap_ = HttpReleaseReader(u("gate"), T("gate-read-survey-service")).get_active_pointer(); assert ap_ and ap_["release_id"] == S["releases"][S["qs"][0]["version"]], ap_
print("OK: 문항 2버전, Trace DUPLICATE, 모델 패키지·어댑터 해시, 활성 포인터(롤백된 릴리스)")
