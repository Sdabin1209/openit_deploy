#!/usr/bin/env python3
"""제품 compose 에 시험용 문이 없다는 정적 점검(E2E 샌드박스 원칙, docs/adr/0050-e2e-sandbox.md). 실행 없이 파일만 읽는다.
  (가) 호스트 포트(ports:)는 gateway 와 compose.inference.yaml 의 model-serving 만 낼 수 있다(다른 서비스는 내부 네트워크 안에서만 닿는다).
  (나) MODEL_RUNTIME_ALLOW_FAKE 는 compose.yaml 과 운영 overlay(compose.external-inference.yaml)에 없다(가짜 백엔드는 시험 구성에서만 켠다).
  (다) compose.test.yaml 이 없다(제품 위에 시험용 문을 덮어쓰는 파일이 없어야 한다).
대상: 리포의 모든 compose*.yaml 과 test/**/*.yaml, demo/**/*.yaml. 종료 코드 0 통과, 1 위반(파일과 서비스를 출력).
"""
import pathlib, re, sys

import yaml

ROOT = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parents[1]
PORT_OK = {("compose.yaml", "gateway"), ("compose.inference.yaml", "model-serving"), ("compose.step-ca-publish.yaml", "step-ca")}   # step-ca 게시는 서버를 나눌 때만 더하는 overlay(ADR 0060)
# 운영자용 관찰 면(헤드 결정 2026-11-01): 시험용 문이 아니라 운영자가 보는 화면·도구다. 파일·서비스를 이름으로 허용하고, 바인드가 127.0.0.1 이어야 한다(조건 검사).
#  - compose.monitoring.yaml prometheus, alertmanager: 운영자 관찰 UI. 127.0.0.1 바인드 필수.
#  - compose.registry.yaml registry: 빌드·게시용 임시 레지스트리(D24), 제품이 아닌 별도 프로젝트. 호스트(docker push)가 닿아야 존재 이유가 있다. 127.0.0.1 바인드가 기본이어야 한다.
EXEMPT = {("compose.registry.yaml", "registry"): "운영자 관찰/게시 면(별도 프로젝트, 빌드·게시용 레지스트리, D24)",
          ("compose.monitoring.yaml", "prometheus"): "운영자 관찰 UI",
          ("compose.monitoring.yaml", "alertmanager"): "운영자 관찰 UI"}
# MODEL_RUNTIME_ALLOW_FAKE 를 가져도 되는 파일(이유). 제품 compose.yaml 과 운영 overlay 에는 없어야 한다(NO_FAKE).
FAKE_OK = {"compose.inference.yaml": "다른 호스트 역할의 추론 서버 파일: 선택 변수 INFERENCE_ALLOW_FAKE 로만 켠다(기본 꺼짐)",
           "test/compose.fake-model.yaml": "그 추론 서버(별도 프로젝트)에만 겹치는 시험 overlay",
           "demo/compose.demo-mimic.yaml": "데모는 제품의 운영 모드(up.sh demo)이고 모델 자리만 모방 백엔드로 바꾼다(헤드 결정 2026-11-01). 시험(E2E)용이 아니라 demo/ 에 둔다"}
NO_FAKE = ("compose.yaml", "compose.external-inference.yaml")


def load(p: pathlib.Path) -> dict:
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    return d if isinstance(d, dict) else {}


def main() -> int:
    bad = []
    files = sorted(ROOT.glob("compose*.yaml")) + sorted((ROOT / "test").rglob("*.yaml")) + sorted((ROOT / "demo").rglob("*.yaml"))
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        try:
            doc = load(p)
        except yaml.YAMLError as e:
            bad.append(f"{rel}: YAML 을 읽지 못했다 ({type(e).__name__})"); continue
        for name, svc in (doc.get("services") or {}).items():
            if isinstance(svc, dict) and svc.get("ports") and (rel, name) in EXEMPT:
                if not all("127.0.0.1" in str(x) for x in svc["ports"]):
                    bad.append(f"(가) {rel}: 서비스 {name} 의 호스트 포트가 127.0.0.1 바인드가 아니다 (허용 조건: 운영자 관찰 면은 127.0.0.1 필수): {svc['ports']}")
                else:
                    print(f"허용 {rel}:{name} -- {EXEMPT[(rel, name)]}")
            elif isinstance(svc, dict) and svc.get("ports") and (rel, name) not in PORT_OK:
                bad.append(f"(가) {rel}: 서비스 {name} 가 호스트 포트를 게시한다 (허용: gateway, compose.inference.yaml 의 model-serving)")
        if re.search(r"MODEL_RUNTIME_ALLOW_FAKE", p.read_text(encoding="utf-8")):
            if rel in NO_FAKE or rel not in FAKE_OK:
                bad.append(f"(나) {rel}: MODEL_RUNTIME_ALLOW_FAKE 가 있다 (제품·운영 overlay 에는 없어야 하고, 허용 목록 밖의 파일도 안 된다)")
            else:
                print(f"허용 {rel}: ALLOW_FAKE -- {FAKE_OK[rel]}")
    if (ROOT / "compose.test.yaml").exists():
        bad.append("(다) compose.test.yaml 이 있다: 제품 위에 시험용 문(내부 서비스 포트, 시험 네트워크, 가짜 백엔드)을 덮어쓰는 파일이다")
    for b in bad:
        print("FAIL " + b)
    if not bad:
        print(f"OK 제품 compose 에 시험용 문이 없다 (점검한 파일 {len(files)}개)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
