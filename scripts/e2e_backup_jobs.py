#!/usr/bin/env python3
"""영역 백업·복구 잡을 돌리고 결과(BackupJobResult)로 판정한다(RUNTIME R10.1, DATA_OWNERSHIP, 계약 3.4.16).
사용: e2e_backup_jobs.py backup|restore [--project P] [--areas a,b,...]
왜 deploy 가 데이터를 꺼내지 않는가: 데이터마다 주인 영역이 있고 백업·복구는 주인의 잡이다(구조 규칙 1·6). deploy 는 잡 서비스(compose job-*)를 한 번 돌리고, 잡이 마지막 줄에 낸 BackupJobResult 를 계약 스키마로 검증해 status 를 본다.
복구한 데이터가 맞는지는 이 도구가 아니라 공개 API 로 다시 읽는 e2e_verify_restore.py 가 본다.
종료 코드 0: 모든 잡 status ok, 1: 하나라도 아니다(어느 잡이 어떻게였는지 말한다), 2: 사용 오류. 잡의 출력 전체는 남기지 않고 마지막 줄의 요약(status·snapshot_id·bytes)만 낸다(비밀 값이 없는 필드)."""
import argparse, json, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
# 영역 -> compose 잡 서비스 이름 뒤쪽(job-<이름>-backup / -restore). 잡 이름은 영역이 선언하고 compose 서비스 이름은 deploy 가 정한다(gen-jobs.py JOB_NAMES)
AREAS = {"survey-service": "survey", "question-authoring": "question-authoring", "ops-feedback": "ops-feedback", "release-gate": "release-gate",
         "model-lab": "model-registry", "synthetic-data": "dataset-store",
         "public-ingress": "gateway", "step-ca": "pki", "identity-db": "identity-db"}   # platform 의 데이터 주인 잡: gateway-data(공개 입구), pki-ca(인증기관)
NO_E2E_RESTORE = {"public-ingress", "step-ca"}
# E2E 의 복구는 영역 데이터 볼륨을 지우고 스택을 다시 올린 뒤 돌린다. 인증기관·공개 입구는 지우면 루트가 새로 만들어져(복구 전에 이미 발급이 일어난다) 이 흐름으로는 복구를 검증할 수 없어 복구 잡을 이 도구의 기본 목록에서 뺀다(--areas 로 지정하면 돌린다). 백업 잡은 모두 돈다


def last_json_line(text: str):
    for line in reversed([l.strip() for l in text.splitlines() if l.strip()]):
        if line.startswith("{"):
            try: return json.loads(line)
            except ValueError: return None
    return None


def judge(kind: str, area: str, rc: int, out: str, check) -> str | None:
    """None 이면 통과, 아니면 실패 이유."""
    res = last_json_line(out)
    if res is None: return f"{area} {kind}: 마지막 줄에 BackupJobResult 가 없다(종료 코드 {rc})"
    errs = check(res)
    if errs: return f"{area} {kind}: BackupJobResult 가 계약을 어긴다: {errs}"
    if res.get("status") != "ok": return f"{area} {kind}: status={res.get('status')} 종료 코드 {rc} 오류={str(res.get('error'))[:120]}"
    if rc != 0: return f"{area} {kind}: status 는 ok 인데 종료 코드가 {rc} 이다"
    return None


def main(argv, runner=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("kind", choices=["backup", "restore"]); ap.add_argument("--project", default=os.environ.get("DEPLOY_PROJECT", "deploy"))
    ap.add_argument("--areas", default=None)
    a = ap.parse_args(argv)
    if a.areas is None: a.areas = ",".join(k for k in AREAS if a.kind == "backup" or k not in NO_E2E_RESTORE)
    from boundary_contracts import validator
    from child_env import child_env  # R9.1: 하위 프로세스는 최소 환경만(scripts/child_env.py). 왜 함수 안: 진입점 문장 수 상한(SHIM_MAX_STATEMENTS)을 지킨다(codex C2 검토, 2026-11-09)
    v = validator("BackupJobResult")
    check = lambda r: [e.message for e in v.iter_errors(r)][:1]
    run = runner or (lambda svc: subprocess.run(["bash", str(ROOT / "scripts/run-job.sh"), svc], capture_output=True, text=True, env=child_env(DEPLOY_PROJECT=a.project)))
    bad = []
    for area in a.areas.split(","):
        if area not in AREAS: print(f"모르는 영역: {area}", file=sys.stderr); return 2
        svc = f"job-{AREAS[area]}-{a.kind}"
        r = run(svc)
        why = judge(a.kind, area, r.returncode, r.stdout or "", check)
        res = last_json_line(r.stdout or "") or {}
        print(f"  {'FAIL' if why else 'ok  '} {area} {a.kind}: status={res.get('status')} snapshot={res.get('snapshot_id')} bytes={res.get('bytes')}" + (f"  <- {why}" if why else ""))
        if why: bad.append(why)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
