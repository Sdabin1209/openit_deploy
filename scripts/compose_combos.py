#!/usr/bin/env python3
"""지원하는 compose 조합 목록과 프로필 의존 점검(정적). 사용: compose_combos.py list | deps
list: 한 줄에 조합 하나(compose 파일 상대 경로를 공백으로). 기본·단독 overlay·스크립트가 COMPOSE_EXTRA="..." 로 쓰는 조합을 스크립트에서 뽑는다.
deps: 모든 조합을 합친 설정에서 "프로필로 꺼지는 서비스에 depends_on(필수)하는 서비스"의 프로필이 같은지 본다. 어긋나면 그 프로필이 꺼질 때 compose 가 거부한다(외부 추론 모드 사고)."""
import pathlib, re, sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALONE = ["compose.inference.yaml", "compose.registry.yaml"]   # 이 파일만으로 띄운다(다른 호스트의 추론 서버, 서버 안 로컬 레지스트리): compose.yaml 과 합치지 않는다
SINGLES = ["compose.external-inference.yaml", "compose.monitoring.yaml", "compose.backup-target.yaml",
           "test/compose.sandbox.yaml", "test/compose.fake-model.yaml", "test/compose.risk-rules.yaml", "demo/compose.demo-mimic.yaml"]


def combos():
    out = [[]]
    out += [[f] for f in SINGLES if (ROOT / f).exists()]
    for f in sorted((ROOT / "scripts").glob("*.sh")) + [ROOT / "docs/RUN.md"]:
        for m in re.finditer(r'COMPOSE_EXTRA="([^"]*)"', f.read_text(encoding="utf-8")):
            parts = [x.replace("$DEPLOY_ROOT/", "") for x in m.group(1).split()]
            if parts and all(re.fullmatch(r"[A-Za-z0-9_./-]+\.yaml", x) and (ROOT / x).exists() for x in parts) and parts not in out:
                out.append(parts)
    return out


def deps_problems():
    bad = []
    for combo in combos():
        merged = {}
        for f in ["compose.yaml", *combo]:
            for k, v in (yaml.safe_load((ROOT / f).read_text(encoding="utf-8")).get("services") or {}).items():
                merged.setdefault(k, {}).update({kk: vv for kk, vv in (v or {}).items() if kk in ("profiles", "depends_on", "network_mode")})
        for n, s in merged.items():
            deps = s.get("depends_on") or {}
            names = list(deps) if isinstance(deps, (dict, list)) else []
            nm = str(s.get("network_mode") or "")
            if nm.startswith("service:"): names.append(nm.split(":", 1)[1])
            for d in names:
                dp = set((merged.get(d) or {}).get("profiles") or [])
                req = deps.get(d, {}).get("required", True) if isinstance(deps, dict) and isinstance(deps.get(d), dict) else True
                if dp and req and not dp <= set(s.get("profiles") or []):
                    bad.append(f"[{' '.join(combo) or '기본'}] {n} 가 프로필 {sorted(dp)} 의 {d} 에 의존하는데 자기는 그 프로필이 아니다")
    return bad


if __name__ == "__main__":
    if sys.argv[1:] == ["list"]:
        for f in ALONE: print("ALONE " + f)
        for c in combos(): print(" ".join(c))
    elif sys.argv[1:] == ["deps"]:
        b = deps_problems()
        print("\n".join(b)) if b else print(f"통과: 조합 {len(combos())}개에서 프로필 의존이 어긋나지 않는다")
        sys.exit(1 if b else 0)
    else:
        sys.exit("사용: compose_combos.py list|deps")
