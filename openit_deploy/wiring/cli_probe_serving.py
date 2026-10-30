"""wiring/진입: probe-serving.py — 떠 있는 model-serving 의 extract 와 respond 에 입력 묶음을 보내 결과를 집계한다(docs/RUN.md '추론 서버 측정 도구').
입력 파일 읽기, 토큰 파일 읽기, 데모 스택 포트 묻기(docker), 동시 호출, 출력은 여기서 하고, 서버 호출은 link_serving_probe, 집계는 serving_probe 컴포넌트가 한다.
토큰은 파일에서 읽고 값을 출력하지 않는다. 입력·모델 원문·발화는 출력하지 않는다(경로와 키워드 이름만). 종료 코드: 0 성공, 2 사용 오류, 3 서버에 닿지 못함·적재된 릴리스 없음."""
import argparse
import json
import os
import pathlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from boundary_contracts.errors import BoundaryError
from openit_deploy.components import link_serving_info, link_serving_probe, serving_probe
from openit_deploy.wiring.call import call

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXAMPLES = ROOT.parent / "boundary-contracts" / "examples"
EXAMPLE = EXAMPLES / "ExtractRequest.with-fields.json"
DEFAULT_UTTERANCES = [
    "십 년 전에 고혈압 진단을 받았어요.", "아니요 없어요.", "네 있어요.", "잘 모르겠어요.", "약은 안 먹어요.",
    "작년부터 먹고 있어요.", "아버지가 당뇨가 있으셨어요.", "하루에 한 갑 정도 피워요.", "술은 안 마셔요.", "일주일에 세 번이요.",
]


def build_inputs(path, repeat: int) -> list:
    if path:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        items = data["inputs"] if isinstance(data, dict) and "inputs" in data else (data if isinstance(data, list) else [data])
        if not items or not all(isinstance(x, dict) and {"input", "flow", "fields"} <= set(x) for x in items): raise SystemExit("입력 파일은 ExtractRequest{input, flow, fields} 객체(들)여야 한다")
    else:
        base = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        items = [{**base, "input": {**base["input"], "user_utterance": u}} for u in DEFAULT_UTTERANCES]
    return [dict(x) for _ in range(repeat) for x in items]


def respond_inputs(repeat: int) -> list:
    files = sorted(EXAMPLES.glob("ResponseRequest*.json"))
    items = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    if not items: raise SystemExit("boundary-contracts/examples 에 ResponseRequest 예제가 없다")
    return [dict(x) for _ in range(repeat) for x in items]


def demo_url(project: str, docker: str) -> str:
    """데모 스택의 model-serving 호스트 포트(Docker 배정)를 묻는다. compose 프로젝트 라벨로 컨테이너를 찾고 docker port 로 읽는다."""
    r = subprocess.run([docker, "compose", "-p", project, "port", "model-serving", "8080"], capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    if r.returncode != 0 or not out:
        r = subprocess.run([docker, "port", f"{project}-model-serving-1", "8080/tcp"], capture_output=True, text=True); out = r.stdout.strip().splitlines()
    if not out: raise SystemExit(f"model-serving 의 포트를 찾지 못했다(프로젝트 {project} 가 떠 있나? scripts/demo.sh status)")
    return "http://127.0.0.1:" + out[0].rsplit(":", 1)[1]


def _loaded_release(url: str, token: str, timeout: float):
    loaded = call(link_serving_info, "ServingInfoRequest", "ServingInfoResult", {"url": url, "token": token, "timeout": 15})["loaded"]
    return loaded[-1] if loaded else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="떠 있는 model-serving 의 extract 와 respond 에 입력 묶음을 보내 결과를 집계한다")
    ap.add_argument("--demo", action="store_true", help="데모 스택의 model-serving(포트는 Docker 배정)")
    ap.add_argument("--project", default=os.environ.get("DEMO_PROJECT", "deploy-demo")); ap.add_argument("--docker", default="docker")
    ap.add_argument("--url", default=""); ap.add_argument("--token-file", default="")
    ap.add_argument("--release-id", default=""); ap.add_argument("--inputs", default="")
    ap.add_argument("--repeat", type=int, default=3, help="입력 묶음을 몇 번 반복할지(기본 3)")
    ap.add_argument("--concurrency", type=int, default=1, help="첫 호출은 혼자 보내고, 나머지를 이 수만큼 동시에 보낸다")
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--endpoints", default="extract,respond", help="측정할 엔드포인트(쉼표): extract, respond. 기본 둘 다. respond 입력은 boundary-contracts 의 ResponseRequest 예제")
    a = ap.parse_args(argv)
    if bool(a.demo) == bool(a.url): print("--demo 또는 --url 중 하나를 준다", file=sys.stderr); return 2
    if a.repeat < 1 or a.concurrency < 1: print("--repeat, --concurrency 는 1 이상", file=sys.stderr); return 2
    tf = a.token_file or (str(ROOT / "state/demo/secrets/tokens/inference-survey-service") if a.demo else "")
    if not tf: print("--url 에는 --token-file 이 필요하다(토큰 값 하나가 든 파일)", file=sys.stderr); return 2
    try: token = pathlib.Path(tf).read_text().strip()
    except OSError as e: print(f"토큰 파일을 읽지 못했다: {tf} ({type(e).__name__})", file=sys.stderr); return 2
    if not token or token.startswith("EXTERNAL_INFERENCE_TOKEN="): print("토큰 파일은 토큰 값 하나만 담아야 한다", file=sys.stderr); return 2
    try: inputs = build_inputs(a.inputs or None, a.repeat)
    except (OSError, ValueError, SystemExit) as e: print(f"입력을 읽지 못했다: {e}", file=sys.stderr); return 2
    url = (demo_url(a.project, a.docker) if a.demo else a.url).rstrip("/")
    eps = [e for e in a.endpoints.split(",") if e]
    if not eps or any(e not in ("extract", "respond") for e in eps): print("--endpoints 는 extract, respond 중에서 쉼표로 준다", file=sys.stderr); return 2
    try:
        rel = a.release_id or _loaded_release(url, token, a.timeout)
        if not rel: print("적재된 릴리스가 없다(--release-id 로 지정하거나 적재를 기다린다)", file=sys.stderr); return 3
    except BoundaryError as e:
        print(f"서버에 닿지 못했다: {e.code}", file=sys.stderr); return 3
    print(f"== probe-serving: {url} 릴리스 {rel}, 엔드포인트 {','.join(eps)} (동시 {a.concurrency})")
    fn = lambda ep, body: call(link_serving_probe, "ServingCallRequest", "ProbeRecord",
                               {"url": url, "token": token, "release_id": rel, "endpoint": ep, "body": body, "timeout": a.timeout})
    endpoints = []
    for ep in eps:
        ins = inputs if ep == "extract" else respond_inputs(a.repeat)
        res = [fn(ep, ins[0])]
        if a.concurrency == 1: res += [fn(ep, x) for x in ins[1:]]
        else:
            with ThreadPoolExecutor(a.concurrency) as ex: res += list(ex.map(lambda x: fn(ep, x), ins[1:]))
        endpoints.append({"name": ep, "records": res})
    r = call(serving_probe, "ServingProbeRequest", "ServingProbeResult", {"endpoints": endpoints})
    for s in r["sections"]: print(s)
    print(r["table"])
    return 0
