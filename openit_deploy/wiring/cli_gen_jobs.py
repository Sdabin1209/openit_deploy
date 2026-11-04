"""wiring/진입: gen-jobs.py --out 파일 [--compose-json 파일|-]  — compose 의 잡 서비스(job-*)마다 이미지 라벨 io.openit.jobs(계약 JobsDeclaration)에서 command 와 시간 한도를 만든 compose 덧씌우기 파일을 쓴다(S10).
compose.yaml 에는 잡의 command 가 없다: `python -m <모듈>` 같은 영역 내부 구조를 deploy 가 적지 않는다(구조 규칙 1). 덧씌우기 파일은 JSON 이다(JSON 은 YAML 의 부분집합이라 compose 가 읽는다).
계약 검증(JobsDeclaration)은 여기서 하고 컴포넌트(job_overlay)에는 결과만 넘긴다. 선언이 없거나 이름이 없으면 종료 코드 1 로 이유를 말한다(짐작하지 않는다)."""
import argparse
import json
import pathlib
import subprocess
import sys

from openit_deploy.components import job_overlay
from openit_deploy.wiring.call import call

# compose 잡 서비스 -> 이미지 라벨 안의 잡 이름. 잡 이름은 영역이 선언한다(영역이 바꾸면 여기 한 곳이 바뀐다). 여기 없는 job-* 서비스는 거부한다
# 선언에 config 가 있는 잡이 마운트할 호스트 쪽 설정 파일(deploy 가 정한다. 컨테이너 안 경로는 영역이 선언한다)
CONFIG_SOURCES = {"job-ops-feedback": "${OPS_JOB_CONFIG:-./config/ops-feedback-job.yaml}",
                  "job-identity-register-users": "${IDENTITY_USERS_CONFIG:-./state/identity-users.json}"}
JOB_NAMES = {"job-survey-purge": "session-purge", "job-question-authoring-purge": "purge", "job-release-gate-prune": "prune",
             "job-release-gate-collect": "collect", "job-ops-feedback": "ops-feedback-job",
             "job-survey-backup": "backup", "job-question-authoring-backup": "backup", "job-release-gate-backup": "backup", "job-ops-feedback-backup": "ops-feedback-backup",
             "job-model-registry-backup": "backup", "job-dataset-store-backup": "dataset-backup",
             "job-gateway-backup": "gateway-backup", "job-pki-backup": "pki-backup", "job-gateway-restore": "gateway-restore", "job-pki-restore": "pki-restore",
             # 복구 잡(RUNTIME R10.1): 사람이 필요할 때 돌린다. 주기가 없어 TIMERS 에 없다
             "job-survey-restore": "restore", "job-question-authoring-restore": "restore", "job-release-gate-restore": "restore", "job-ops-feedback-restore": "ops-feedback-restore",
             "job-model-registry-restore": "restore", "job-dataset-store-restore": "dataset-restore",
             # 상시 서비스의 일회성 선행 서비스(depends_on service_completed_successfully)도 명령은 이미지 선언에서 온다
             "ops-feedback-migrate": "ops-feedback-migrate",
             "job-identity-register-users": "register-users"}


# compose 잡 서비스 -> 그 잡을 띄우는 타이머 파일(config/systemd). 주기는 타이머의 OnUnitActiveSec 이고 잡의 시간 상한은 그 주기보다 짧아야 한다(RUNTIME R9.3: 상한이 주기 이상이면 겹침 방지가 다음 주기를 막는다)
TIMERS = {"job-survey-purge": "openit-survey-purge", "job-question-authoring-purge": "openit-question-authoring-purge", "job-release-gate-prune": "openit-release-gate-prune",
          "job-release-gate-collect": "openit-release-gate-collector", "job-ops-feedback": "openit-ops-feedback-job",
          "job-survey-backup": "openit-survey-backup", "job-question-authoring-backup": "openit-question-authoring-backup", "job-release-gate-backup": "openit-release-gate-backup", "job-ops-feedback-backup": "openit-ops-feedback-backup",
          "job-model-registry-backup": "openit-model-registry-backup", "job-dataset-store-backup": "openit-dataset-store-backup",
          "job-gateway-backup": "openit-gateway-backup", "job-pki-backup": "openit-pki-backup"}
SYSTEMD = pathlib.Path(__file__).resolve().parents[2] / "config" / "systemd"


def period_seconds(svc: str):
    """deploy 가 정한 기본 주기(config/systemd 타이머의 OnUnitActiveSec). 없으면 None"""
    import re
    m = re.search(r"^OnUnitActiveSec=(\d+)s", (SYSTEMD / f"{TIMERS[svc]}.timer").read_text(encoding="utf-8"), re.M)
    return int(m.group(1)) if m else None


def check_r93(result: dict):
    """RUNTIME R9.3: 시간 상한은 실행 주기보다 짧아야 한다. 어기면 거부한다(주기를 만드는 규칙이 빠지면 여기서 걸린다)"""
    bad = [f"{svc}: 시간 상한 {v['x-openit-timeout-seconds']}초가 실행 주기 {v['x-openit-period-seconds']}초 이상이다(R9.3)" for svc, v in result["services"].items()
           if v["x-openit-timeout-seconds"] >= v["x-openit-period-seconds"]]
    if bad: raise SystemExit("\n".join(bad))


def derived_units(svc: str, timeout: int, period: int) -> dict:
    """영역이 선언한 시간 상한과 규칙으로 정한 주기로 만든 systemd 유닛 사본(config/systemd 의 기본 유닛에서): {파일 이름: 내용}"""
    import re
    base = TIMERS[svc]
    tm = (SYSTEMD / f"{base}.timer").read_text(encoding="utf-8")
    sv = (SYSTEMD / f"{base}.service").read_text(encoding="utf-8")
    tm = re.sub(r"^OnUnitActiveSec=\d+s", f"OnUnitActiveSec={period}s", tm, flags=re.M)
    sv = re.sub(r"^TimeoutStartSec=\d+", f"TimeoutStartSec={timeout}", sv, flags=re.M)
    sv = re.sub(r"(job-metrics\.sh \S+) \d+", rf"\1 {period}", sv)
    return {f"{base}.timer": tm, f"{base}.service": sv}


def image_labels(image: str) -> dict:
    """docker 로 이미지 라벨을 읽는다. 로컬에 없으면 받는다(compose run 이 받는 것과 같은 이미지)."""
    r = subprocess.run(["docker", "image", "inspect", image, "--format", "{{json .Config.Labels}}"], capture_output=True, text=True)
    if r.returncode != 0:
        p = subprocess.run(["docker", "pull", "-q", image], capture_output=True, text=True)
        if p.returncode != 0:
            raise SystemExit(f"이미지를 받을 수 없다: {image}")
        r = subprocess.run(["docker", "image", "inspect", image, "--format", "{{json .Config.Labels}}"], capture_output=True, text=True)
    return json.loads(r.stdout) or {}


def build(compose: dict, labels_of, validator_of) -> dict:
    jobs, problems = [], []
    for svc, body in sorted(compose["services"].items()):
        if not svc.startswith("job-") and svc not in JOB_NAMES:
            continue
        name = JOB_NAMES.get(svc)
        if name is None:
            problems.append(f"{svc}: JOB_NAMES 에 잡 이름이 없다")
            continue
        raw = labels_of(body["image"]).get("io.openit.jobs")
        if raw is None:
            problems.append(f"{svc}: 이미지에 라벨 io.openit.jobs 가 없다(영역이 잡을 선언하지 않았다)")
            continue
        decl = json.loads(raw)
        errs = [e.message for e in validator_of("JobsDeclaration").iter_errors(decl)][:1]
        if errs:
            problems.append(f"{svc}: JobsDeclaration 스키마 위반: {errs[0]}")
            continue
        job = next((j for j in decl["jobs"] if j["name"] == name), None)
        if job is None:
            problems.append(f"{svc}: 선언에 잡 {name} 가 없다: {[j['name'] for j in decl['jobs']]}")
            continue
        base = period_seconds(svc) if svc in TIMERS else None
        jobs.append({"compose_service": svc, "declared": job, **({"base_period_seconds": base} if base else {}), **({"config_source": CONFIG_SOURCES[svc]} if svc in CONFIG_SOURCES else {})})
    if problems:
        raise SystemExit("\n".join(problems))
    res = call(job_overlay, "JobOverlayRequest", "JobOverlayResult", {"jobs": jobs})
    check_r93(res)
    return res


def main(argv, labels_of=image_labels) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--compose-json", default="-")
    a = ap.parse_args(argv)
    raw = sys.stdin.read() if a.compose_json == "-" else pathlib.Path(a.compose_json).read_text(encoding="utf-8")
    from boundary_contracts import validator
    compose = json.loads(raw)
    if not any(n.startswith("job-") for n in compose["services"]):
        return 0   # 잡 서비스가 없는 배치(서버를 나눈 한 쪽, 시험용 작은 compose)는 덧씌울 것이 없다
    res = build(compose, labels_of, validator)
    out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    udir = out.parent / "systemd"; udir.mkdir(exist_ok=True)   # 선언한 상한과 규칙으로 정한 주기로 만든 유닛 사본(설치는 배포 몫: config/systemd 는 기본값이다)
    for svc, v in res["services"].items():
        if svc in TIMERS:
            for name, body in derived_units(svc, v["x-openit-timeout-seconds"], v["x-openit-period-seconds"]).items():
                (udir / name).write_text(body, encoding="utf-8")
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(out)
    return 0
