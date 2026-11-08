#!/usr/bin/env python3
"""정적 시험(RUNTIME R10.1, CommonEnv OPENIT_BACKUP_*): 영역 백업 잡 배선.
(1) 영역마다 백업 잡이 영역 pod 안에서 돈다(영역 게이트웨이 loopback 출구). (2) OPENIT_BACKUP_URL 은 https 이고 영역마다 다른 경로다.
(3) 자격·저장소 암호 비밀 이름이 영역마다 다르고 자기 영역의 잡만 마운트한다(다른 영역의 자격으로 남의 저장소에 못 간다). (4) 백업 저장소는 영역별 전용 망에만 붙고 영역끼리 같은 망을 쓰지 않는다.
(5) 저장소의 htpasswd 는 저장소만 읽는다. 변이 확인: 자격 비밀을 두 영역이 공유하게 바꾸면 실패한다."""
import copy, re, subprocess, sys, unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
S0 = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
AREAS = {"survey": ("job-survey-backup", "survey-service"), "qa": ("job-question-authoring-backup", "question-authoring"),
         "ops": ("job-ops-feedback-backup", "ops-feedback"), "gate": ("job-release-gate-backup", "release-gate"),
         "models": ("job-model-registry-backup", "model-registry"), "datasets": ("job-dataset-store-backup", "dataset-store"),
         "gateway": ("job-gateway-backup", None), "pki": ("job-pki-backup", None), "identity": ("job-identity-db-backup", None)}   # None = 영역 pod 가 아니라 백업 저장소 전용 망(backup-<키>)에 직접 붙는 잡(공개 입구, 인증기관)


def check(S):
    errs = []
    creds = {}
    for key, (job, pod) in AREAS.items():
        j = S.get(job)
        if not j:
            errs.append(f"{job}: 백업 잡이 없다"); continue
        if pod and j.get("network_mode") != f"service:{pod}-net":
            errs.append(f"{job}: 영역 pod({pod}-net) 안에서 돌지 않는다")
        if not pod and (f"backup-{key}" not in (j.get("networks") or []) or len(j.get("networks") or []) > 2 or j.get("network_mode")):
            errs.append(f"{job}: 백업 저장소 전용 망(backup-{key})에만 붙어야 한다: {j.get('networks')}")
        env = j.get("environment") or {}
        if not str(env.get("OPENIT_BACKUP_URL", "")).startswith("https://backup-store/" + key + "/"):
            errs.append(f"{job}: OPENIT_BACKUP_URL 이 https://backup-store/{key}/ 가 아니다")
        if pod and env.get("OPENIT_EGRESS_PROXY") != "http://127.0.0.1:3128":
            errs.append(f"{job}: OPENIT_EGRESS_PROXY 가 loopback 출구가 아니다")
        sec = [x if isinstance(x, str) else x.get("source") for x in j.get("secrets", [])]
        mine = {x for x in sec if x.startswith("backup-")}
        if mine != {f"backup-{key}-credentials", f"backup-{key}-repo-password"}:
            errs.append(f"{job}: 자기 영역의 자격·저장소 암호만 받아야 한다: {sorted(mine)}")
        for ev in ("OPENIT_BACKUP_CREDENTIALS_FILE", "OPENIT_BACKUP_REPO_PASSWORD_FILE"):
            f = str(env.get(ev, ""))
            if not f.startswith("/run/secrets/backup-" + key + "-"):
                errs.append(f"{job}: {ev} 가 자기 영역 비밀이 아니다: {f}")
        creds[key] = mine
    allv = [v for m in creds.values() for v in m]
    if len(allv) != len(set(allv)):
        errs.append("영역끼리 자격·저장소 암호를 공유한다")
    bs = S.get("backup-store") or {}
    nets = set((bs.get("networks") or {}).keys())
    if nets != {f"backup-{k}" for k in AREAS}:
        errs.append(f"backup-store 의 망이 영역별 전용 망 9개가 아니다: {sorted(nets)}")
    for key, (job, pod) in AREAS.items():
        if not pod: continue
        pn = set((S.get(f"{pod}-net", {}).get("networks") or {}).keys())
        if f"backup-{key}" not in pn:
            errs.append(f"{pod}-net 에 backup-{key} 망이 없다")
        others = {f"backup-{k}" for k in AREAS if k != key}
        if pn & others:
            errs.append(f"{pod}-net 이 다른 영역의 백업 망을 쓴다")
    bsec = {(x if isinstance(x, str) else x.get("source")) for x in bs.get("secrets", [])}
    if bsec != {f"backup-{k}-credentials" for k in AREAS}:
        errs.append(f"저장소는 영역 자격 파일 9개(/run/secrets/areas/<영역>)만 받는다: {sorted(bsec)}")
    for k in AREAS:
        readers = [n for n, sv in S.items() if any((x if isinstance(x, str) else x.get("source")) == f"backup-{k}-credentials" for x in sv.get("secrets", []))]
        if sorted(readers) != sorted([AREAS[k][0], AREAS[k][0].replace("-backup", "-restore"), "backup-store"]):
            errs.append(f"{k} 자격을 읽는 서비스가 그 영역 백업·복구 잡과 저장소뿐이 아니다: {readers}")
    # 잡이 영역 데이터 볼륨을 필요로 하면(이미지 잡 선언 needs, ContainerInputs writable persist) 서비스와 같은 볼륨을 같은 경로에 둔다.
    # 2026-11-08 E2E 단계 9: job-release-gate-backup 이 gate-data 대신 tmpfs /data(root 755)를 받아 비root 잡이 PermissionError, 묶음 파일도 빠졌다
    for job in ("job-release-gate-backup", "job-release-gate-restore"):
        j = S.get(job) or {}
        if "gate-data:/data" not in (j.get("volumes") or []) or "/data" in (j.get("tmpfs") or []):
            errs.append(f"{job}: 릴리스 묶음 볼륨 gate-data 를 /data 에 두어야 한다(tmpfs /data 금지)")
    cmd = bs.get("command") or []
    if "--append-only" in cmd:
        errs.append("백업 저장소는 append-only 가 아니다(영역 백업 잡이 forget --prune 으로 보존을 지킨다)")
    for sv in ("survey-service", "question-authoring", "ops-feedback", "release-gate", "model-registry", "dataset-store"):
        if S.get(f"{sv}-gw", {}).get("user") is not None:
            errs.append(f"{sv}-gw: 이미지가 선언한 사용자를 deploy 가 바꾸지 않는다")
        if "user" in S.get(f"{sv}-cert", {}):
            errs.append(f"{sv}-cert: 이미지가 선언한 사용자를 deploy 가 바꾸지 않는다(3.4.17)")
        if "10100" not in str(S.get(f"{sv}-gw", {}).get("group_add")):
            errs.append(f"{sv}-gw: 인증서를 읽는 컨테이너는 STEP_CERT_GID 보조 그룹이 있어야 한다")
    return errs


class T(unittest.TestCase):
    def test_wiring_is_clean(self):
        self.assertEqual(check(S0), [])

    def test_mutation_shared_credentials_is_caught(self):
        m = copy.deepcopy(S0)
        m["job-qa-backup" if False else "job-question-authoring-backup"]["secrets"] = [x if "backup-qa" not in x else x.replace("backup-qa", "backup-survey") for x in m["job-question-authoring-backup"]["secrets"]]
        self.assertTrue(check(m), "일부러 qa 잡에 survey 자격을 줬는데 못 잡았다")

    def test_mutation_append_only_is_caught(self):
        m = copy.deepcopy(S0); m["backup-store"]["command"] = ["--append-only"]
        self.assertTrue(check(m))

    def test_mutation_gateway_user_override_is_caught(self):
        m = copy.deepcopy(S0); m["survey-service-gw"]["user"] = "1000:1000"
        self.assertTrue(check(m))

    def test_mutation_shared_network_is_caught(self):
        m = copy.deepcopy(S0)
        m["survey-service-net"]["networks"]["backup-qa"] = {}
        self.assertTrue(check(m))

    def test_mutation_gate_backup_tmpfs_data_is_caught(self):
        m = copy.deepcopy(S0)
        m["job-release-gate-backup"]["volumes"] = ["pki-root:/etc/openit/pki:ro"]; m["job-release-gate-backup"]["tmpfs"] = ["/tmp", "/data"]
        self.assertTrue(check(m))


if __name__ == "__main__":
    unittest.main()
