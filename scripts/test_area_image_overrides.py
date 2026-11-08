#!/usr/bin/env python3
"""영역 이미지를 덮어쓰지 않는다(계약 CONVENTIONS 13절, 3.4.17): compose 가 영역 이미지의 healthcheck·command·entrypoint·user·volumes_from 을 정하지 않는다 -- 그 이미지의 HEALTHCHECK·CMD·ENTRYPOINT·USER 는 영역이 이미지에 선언한다(구조 규칙 1·4).
정적 점검(실행 안 함). 영역 이미지 = compose.yaml 에서 이미지가 `/openit/` 레지스트리 경로인 서비스(그 서비스를 겹치는 파일의 같은 이름 서비스 포함) 또는 로컬 deploy-build 이미지. pause·util·registry·postgres 같은 제3자 이미지는 대상이 아니다.
예외 둘: (1) 잡(profiles 에 jobs)의 command 는 이미지의 JobsDeclaration(io.openit.jobs)이 정한 argv 이고 scripts/test_gen_jobs.py 가 선언과 일치를 본다. (2) PENDING: 알려진 위반이고 해소 조건이 있다(아래). 위반이 해소돼 PENDING 항목이 더는 해당하지 않으면 시험이 실패한다(항목을 지우도록)."""
import glob, pathlib, sys, tempfile, unittest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
FORBIDDEN = ("healthcheck", "command", "entrypoint", "user", "volumes_from")
# 알려진 위반(대장 #7): compose.llm.yaml 의 model-serving healthcheck(타이밍 덮어쓰기). 해소 조건: model-runtime 이 GPU 이미지의 HEALTHCHECK(start_period 포함)를 이미지에 둔 버전이 기준표(lib.sh DEPLOY_MR_TAG)에 오른 뒤 이 줄을 지운다.
PENDING = set()   # 위반 없음(compose.llm.yaml 의 healthcheck 덮어쓰기는 model-runtime 0.12.6 의 이미지 HEALTHCHECK 로 대체돼 지웠다)


class L(yaml.SafeLoader): pass
for _t in ("!reset", "!override"): L.add_constructor(_t, lambda loader, node: None)


def _services(path):
    return {n: s for n, s in ((yaml.load(pathlib.Path(path).read_text(encoding="utf-8"), L) or {}).get("services") or {}).items() if isinstance(s, dict)}


def violations(root):
    root = pathlib.Path(root); base = _services(root / "compose.yaml")
    area = {n for n, s in base.items() if "/openit/" in str(s.get("image", ""))}
    out = set()
    files = sorted(glob.glob(str(root / "compose*.yaml")) + glob.glob(str(root / "test/compose*.yaml")) + glob.glob(str(root / "demo/compose*.yaml")))
    for f in files:
        rel = str(pathlib.Path(f).relative_to(root))
        for n, s in _services(f).items():
            img = str(s.get("image", ""))
            is_area = n in area if rel == "compose.yaml" else ("/openit/" in img or "deploy-build/" in img or "MODEL_SERVING_GPU_IMAGE" in img or (not img and n in area))
            if not is_area: continue
            for k in FORBIDDEN:
                if k not in s: continue
                if k == "command" and "jobs" in (s.get("profiles") or []): continue
                out.add((rel, n, k))
    return out


class T(unittest.TestCase):
    def test_no_new_overrides(self):
        v = violations(ROOT)
        self.assertEqual(sorted(v - PENDING), [], "영역 이미지의 healthcheck·command·entrypoint·user·volumes_from 을 compose 가 정했다(CONVENTIONS 13절): 이미지에 선언하게 영역에 요청한다")
        stale = PENDING - v
        self.assertEqual(sorted(stale), [], "PENDING 위반이 해소됐다: 이 시험의 PENDING 에서 지운다")
        for x in sorted(v & PENDING): print("  PENDING(알려진 위반, 해소 조건은 PENDING 주석):", x)

    def test_area_db_services_are_nonroot_shaped(self):
        """영역 DB 4개(non-root USER postgres 999:999, 선언 capabilities 빈 목록): cap_add 없음, /run tmpfs 는 uid=999,gid=999(옵션 없는 tmpfs 는 0:0 이라 999 가 못 쓴다)."""
        svc = _services(ROOT / "compose.yaml")
        for n in ("survey-db", "question-authoring-db", "ops-feedback-db", "release-gate-db"):
            self.assertNotIn("cap_add", svc[n], f"{n}: 선언 capabilities 가 빈 목록인데 cap_add 가 있다")
            self.assertIn("/run:uid=999,gid=999,mode=0755", svc[n]["tmpfs"], f"{n}: /run tmpfs 소유자")

    def test_detects_mutations(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            (d / "compose.yaml").write_text("services:\n  svc:\n    image: ${R}/openit/svc@${SVC_DIGEST}\n    healthcheck: {test: [CMD, x]}\n  other:\n    image: ${PAUSE_IMAGE}\n    user: '1:1'\n  job-x:\n    image: ${R}/openit/svc@${SVC_DIGEST}\n    profiles: [jobs]\n    command: [run-once]\n", encoding="utf-8")
            (d / "compose.over.yaml").write_text("services:\n  svc:\n    entrypoint: [sh]\n    volumes_from: [other]\n", encoding="utf-8")
            self.assertEqual(violations(d), {("compose.yaml", "svc", "healthcheck"), ("compose.over.yaml", "svc", "entrypoint"), ("compose.over.yaml", "svc", "volumes_from")})   # 제3자 user·잡 command 는 위반이 아니다


if __name__ == "__main__":
    unittest.main()
