"""wiring/진입: retention_check.py [--backup-days N | --backup-env <backup.env>] [--config-dir DIR] [--compose FILE]
종료 코드: 0 통과, 1 백업 보관이 더 길다, 2 값을 읽지 못함. 파일 읽기와 출력은 여기서 하고 판단은 컴포넌트 retention_check 가 한다."""
import argparse
import pathlib
import re
import sys

from openit_deploy.components import retention_check
from openit_deploy.wiring.call import call

ROOT = pathlib.Path(__file__).resolve().parents[2]


def read_sources(config_dir: pathlib.Path, compose: pathlib.Path) -> dict:
    job = config_dir / "ops-feedback-job.yaml"
    return {"env_files": [{"name": f.name, "text": f.read_text(encoding="utf-8")} for f in sorted(config_dir.glob("*.env"))],
            "ops_job": {"name": job.name, "text": job.read_text(encoding="utf-8")} if job.is_file() else None,
            "compose": {"name": compose.name, "text": compose.read_text(encoding="utf-8")} if compose.is_file() else None}


def main(argv) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--backup-days", type=int); ap.add_argument("--backup-env")
    ap.add_argument("--config-dir", default=str(ROOT / "config")); ap.add_argument("--compose", default=str(ROOT / "compose.yaml"))
    a = ap.parse_args(argv)
    days = a.backup_days
    if days is None and a.backup_env:
        m = re.search(r"^BACKUP_RETENTION_DAYS=(\d+)", pathlib.Path(a.backup_env).read_text(encoding="utf-8"), re.M)
        days = int(m.group(1)) if m else None
    if days is None:
        print("백업 보관 일수를 읽지 못했다", file=sys.stderr); return 2
    r = call(retention_check, "RetentionCheckRequest", "RetentionCheckResult",
             {"backup_days": days, "sources": read_sources(pathlib.Path(a.config_dir), pathlib.Path(a.compose))})
    if r["status"] == "NO_VALUES":
        print("운영 데이터 보존 일수를 하나도 읽지 못했다(설정 위치가 맞는지 확인)", file=sys.stderr); return 2
    lo = r["shortest"]
    print(f"백업 보관 {days}일, 운영 데이터 보존 가장 짧은 값 {lo['days']}일 ({lo['source']}); 읽은 값 {r['values_read']}개")
    if r["status"] == "BACKUP_TOO_LONG":
        print(f"CRIT: 백업 보관({days}일)이 운영 데이터 보존({lo['days']}일, {lo['source']})보다 길다: 운영 DB에서 지운 데이터가 백업에 더 오래 남는다(ADR 0044). BACKUP_RETENTION_DAYS 를 {lo['days']} 이하로 낮춘다", file=sys.stderr)
        return 1
    return 0
