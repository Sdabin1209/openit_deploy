#!/usr/bin/env python3
"""제품 compose 에 시험용 문이 없다는 정적 점검(E2E 샌드박스 원칙, docs/adr/0050-e2e-sandbox.md). 실행 없이 파일만 읽는다.
  (가) 호스트 포트(ports:)는 gateway 와 compose.inference.yaml 의 model-serving 만 낼 수 있다(다른 서비스는 내부 네트워크 안에서만 닿는다).
  (나) MODEL_RUNTIME_ALLOW_FAKE 는 compose.yaml 과 운영 overlay(compose.external-inference.yaml)에 없다(가짜 백엔드는 시험 구성에서만 켠다).
  (다) compose.test.yaml 이 없다(제품 위에 시험용 문을 덮어쓰는 파일이 없어야 한다).
대상: 리포의 모든 compose*.yaml 과 test/**/*.yaml. 종료 코드 0 통과, 1 위반(파일과 서비스를 출력).
"""
import pathlib, re, sys

import yaml

ROOT = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parents[1]
PORT_OK = {("compose.yaml", "gateway"), ("compose.inference.yaml", "model-serving")}
# 제품 밖의 별도 프로젝트와 아직 결정되지 않은 예외. 예외는 조용히 통과하지 않고 매번 출력한다(열린 것: 헤드 결정).
#  - compose.registry.yaml: 빌드·게시용 임시 레지스트리(D24)는 제품 스택이 아니라 별도 프로젝트다. 호스트(docker push)가 닿아야 존재 이유가 있다.
#  - compose.monitoring.yaml: 감시 스택(prometheus, alertmanager) 호스트 포트 2개. 운영자 화면인지 시험용 문인지 결정되지 않았다(check-monitoring-live.sh 가 읽는다).
EXEMPT = {("compose.registry.yaml", "registry"): "별도 프로젝트(빌드·게시용 레지스트리, D24)",
          ("compose.monitoring.yaml", "prometheus"): "미결정: 감시 스택 포트(헤드 결정 필요)",
          ("compose.monitoring.yaml", "alertmanager"): "미결정: 감시 스택 포트(헤드 결정 필요)"}
# 왜 gateway 만: 외부 입구는 gateway 하나다(D11). 추론 서버는 다른 호스트 역할이라 자기 compose 가 자기 포트를 낸다(D72)
NO_FAKE = ("compose.yaml", "compose.external-inference.yaml")


def load(p: pathlib.Path) -> dict:
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    return d if isinstance(d, dict) else {}


def main() -> int:
    bad = []
    files = sorted(ROOT.glob("compose*.yaml")) + sorted((ROOT / "test").rglob("*.yaml"))
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        try:
            doc = load(p)
        except yaml.YAMLError as e:
            bad.append(f"{rel}: YAML 을 읽지 못했다 ({type(e).__name__})"); continue
        for name, svc in (doc.get("services") or {}).items():
            if isinstance(svc, dict) and svc.get("ports") and (rel, name) in EXEMPT:
                print(f"예외 {rel}:{name} -- {EXEMPT[(rel, name)]}")
            elif isinstance(svc, dict) and svc.get("ports") and (rel, name) not in PORT_OK:
                bad.append(f"(가) {rel}: 서비스 {name} 가 호스트 포트를 게시한다 (허용: gateway, compose.inference.yaml 의 model-serving)")
        if rel in NO_FAKE and re.search(r"MODEL_RUNTIME_ALLOW_FAKE", p.read_text(encoding="utf-8")):
            bad.append(f"(나) {rel}: MODEL_RUNTIME_ALLOW_FAKE 가 있다 (가짜 백엔드는 시험 구성에서만)")
    if (ROOT / "compose.test.yaml").exists():
        bad.append("(다) compose.test.yaml 이 있다: 제품 위에 시험용 문(내부 서비스 포트, 시험 네트워크, 가짜 백엔드)을 덮어쓰는 파일이다")
    for b in bad:
        print("FAIL " + b)
    if not bad:
        print(f"OK 제품 compose 에 시험용 문이 없다 (점검한 파일 {len(files)}개)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
