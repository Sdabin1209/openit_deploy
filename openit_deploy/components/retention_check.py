"""컴포넌트 retention_check: 백업 보관 기간(BACKUP_RETENTION_DAYS)이 운영 데이터 보존 기간 중 가장 짧은 값 이하인지 본다(OPEN_GAPS U30, ADR 0044).
입력 RetentionCheckRequest(설정 파일 텍스트), 출력 RetentionCheckResult. 운영 DB에서 보존 기간이 지나 지운 데이터가 백업에 더 오래 남으면 보존 정책이 백업으로 우회된다.
데이터 보존 값의 출처(deploy 설정에 실제로 적힌 것만): config/*.env 의 *_RETENTION_DAYS, config/ops-feedback-job.yaml 의 retention.*_days(숫자만; "forever"는 건너뛴다), compose.yaml environment 의 숫자 *_RETENTION_DAYS.
표준 라이브러리만 쓴다."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:   # 입출력 타입은 schemas/ 에서 생성한다(types/deploy_types.py, 손으로 고치지 않는다)
    from openit_deploy.types.deploy_types import RetentionCheckRequest, RetentionCheckResult

import re


def data_retentions(sources: dict) -> dict:
    out = {}
    for f in sorted(sources.get("env_files") or (), key=lambda f: f["name"]):
        for line in f["text"].splitlines():
            m = re.match(r"^([A-Z0-9_]*RETENTION_DAYS)=(\d+)\b", line.strip())
            if m: out[f"{f['name']}:{m.group(1)}"] = int(m.group(2))
    job = sources.get("ops_job")
    if job:
        in_ret = False
        for line in job["text"].splitlines():
            if re.match(r"^retention:", line): in_ret = True; continue
            if in_ret and re.match(r"^\S", line): in_ret = False
            m = re.match(r"^\s+([a-z_]+_days):\s*(\d+)\b", line) if in_ret else None
            if m: out[f"{job['name']}:retention.{m.group(1)}"] = int(m.group(2))
    comp = sources.get("compose")
    if comp:
        for line in comp["text"].splitlines():
            m = re.match(r'''^\s+([A-Z0-9_]*RETENTION_DAYS):\s*["']?(\d+)["']?\s*(#.*)?$''', line)
            if m: out[f"{comp['name']}:{m.group(1)}"] = int(m.group(2))
    return out


def run(request: "RetentionCheckRequest") -> "RetentionCheckResult":
    vals = data_retentions(request["sources"])
    days = request["backup_days"]
    if not vals:
        return {"status": "NO_VALUES", "backup_days": days, "values_read": 0}
    lo_k = min(vals, key=vals.get)
    return {"status": "BACKUP_TOO_LONG" if days > vals[lo_k] else "OK", "backup_days": days, "values_read": len(vals),
            "shortest": {"source": lo_k, "days": vals[lo_k]}}
