"""wiring/진입: gen-gateways.py --out 폴더 [--compose-json 파일|-]  — compose 의 영역 게이트웨이(<서비스>-gw)마다 그 서비스 이미지의 라벨 io.openit.exposure 를 <폴더>/<서비스>/exposure.json 으로 쓴다.
영역 게이트웨이 이미지(platform)가 시작할 때 그 파일에서 자기 설정을 만든다. deploy 는 설정을 만들지 않는다. 라벨이 없거나 계약을 어기면 종료 코드 1."""
import argparse
import json
import pathlib
import sys

from openit_deploy.components import gateway_exposure
from openit_deploy.wiring.call import call
from openit_deploy.wiring.cli_gen_jobs import image_labels


def build(compose: dict, labels_of, validator_of) -> dict:
    out, problems = {}, []
    for gw in sorted(n for n in compose["services"] if n.endswith("-gw")):
        svc = gw[:-3]
        if svc not in compose["services"]:
            problems.append(f"{gw}: 짝이 되는 서비스 {svc} 가 compose 에 없다")
            continue
        labels = labels_of(compose["services"][svc]["image"])
        errs = []
        if "io.openit.exposure" in labels:
            errs = [e.message for e in validator_of("Exposure").iter_errors(json.loads(labels["io.openit.exposure"]))][:1]
        r = call(gateway_exposure, "GatewayExposureRequest", "GatewayExposureResult", {"service": svc, "labels": labels, "declaration_errors": errs})
        if r["status"] != "OK":
            problems.append(r["message"])
        else:
            out[svc] = r["exposure_json"]
    if problems:
        raise SystemExit("\n".join(problems))
    return out


def main(argv, labels_of=image_labels) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--compose-json", default="-")
    a = ap.parse_args(argv)
    raw = sys.stdin.read() if a.compose_json == "-" else pathlib.Path(a.compose_json).read_text(encoding="utf-8")
    from boundary_contracts import validator
    res = build(json.loads(raw), labels_of, validator)
    for svc, body in res.items():
        for d, name in ((pathlib.Path(a.out) / svc, "exposure.json"), (pathlib.Path(a.out) / "exposures", svc + ".json")):   # 앞: 영역 게이트웨이용, 뒤: 공개 입구가 읽는 모든 영역의 선언 폴더
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / f".{name}.tmp"; tmp.write_text(body + "\n", encoding="utf-8"); tmp.chmod(0o644); tmp.replace(d / name)   # 같은 폴더에서 rename: 읽는 쪽이 쓰는 도중 파일을 보지 않는다
    print(a.out)
    return 0
