#!/usr/bin/env python3
"""백업 보관 기간(BACKUP_RETENTION_DAYS)이 운영 데이터 보존 기간 중 가장 짧은 값 이하인지 본다(OPEN_GAPS U30, ADR 0044).
운영 DB에서 보존 기간이 지나 지운 데이터가 백업에 더 오래 남으면 보존 정책이 백업으로 우회된다.
데이터 보존 값의 출처(deploy 설정에 실제로 적힌 것만): config/*.env 의 *_RETENTION_DAYS, config/ops-feedback-job.yaml 의 retention.*_days(숫자만; "forever"는 건너뛴다), compose.yaml environment 의 숫자 *_RETENTION_DAYS.
사용: retention_check.py [--backup-days N | --backup-env <backup.env>] [--config-dir DIR] [--compose FILE]   종료 코드: 0 통과, 1 백업 보관이 더 길다, 2 값을 읽지 못함.
읽는 쪽 의존이 없게 표준 라이브러리만 쓴다(backup-check.sh 가 시스템 python3 로 부른다)."""
import argparse, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def data_retentions(config_dir: pathlib.Path, compose: pathlib.Path) -> dict:
    out = {}
    for f in sorted(config_dir.glob("*.env")):
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([A-Z0-9_]*RETENTION_DAYS)=(\d+)\b", line.strip())
            if m: out[f"{f.name}:{m.group(1)}"] = int(m.group(2))
    job = config_dir / "ops-feedback-job.yaml"
    if job.is_file():
        in_ret = False
        for line in job.read_text(encoding="utf-8").splitlines():
            if re.match(r"^retention:", line): in_ret = True; continue
            if in_ret and re.match(r"^\S", line): in_ret = False
            m = re.match(r"^\s+([a-z_]+_days):\s*(\d+)\b", line) if in_ret else None
            if m: out[f"{job.name}:retention.{m.group(1)}"] = int(m.group(2))
    if compose.is_file():
        for line in compose.read_text(encoding="utf-8").splitlines():
            m = re.match(r'''^\s+([A-Z0-9_]*RETENTION_DAYS):\s*["']?(\d+)["']?\s*(#.*)?$''', line)
            if m: out[f"{compose.name}:{m.group(1)}"] = int(m.group(2))
    return out


def main(argv):
    ap = argparse.ArgumentParser(); ap.add_argument("--backup-days", type=int); ap.add_argument("--backup-env")
    ap.add_argument("--config-dir", default=str(ROOT / "config")); ap.add_argument("--compose", default=str(ROOT / "compose.yaml"))
    a = ap.parse_args(argv)
    days = a.backup_days
    if days is None and a.backup_env:
        m = re.search(r"^BACKUP_RETENTION_DAYS=(\d+)", pathlib.Path(a.backup_env).read_text(encoding="utf-8"), re.M)
        days = int(m.group(1)) if m else None
    if days is None:
        print("백업 보관 일수를 읽지 못했다", file=sys.stderr); return 2
    vals = data_retentions(pathlib.Path(a.config_dir), pathlib.Path(a.compose))
    if not vals:
        print("운영 데이터 보존 일수를 하나도 읽지 못했다(설정 위치가 맞는지 확인)", file=sys.stderr); return 2
    lo_k = min(vals, key=vals.get); lo = vals[lo_k]
    print(f"백업 보관 {days}일, 운영 데이터 보존 가장 짧은 값 {lo}일 ({lo_k}); 읽은 값 {len(vals)}개")
    if days > lo:
        print(f"CRIT: 백업 보관({days}일)이 운영 데이터 보존({lo}일, {lo_k})보다 길다: 운영 DB에서 지운 데이터가 백업에 더 오래 남는다(ADR 0044). BACKUP_RETENTION_DAYS 를 {lo} 이하로 낮춘다", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
