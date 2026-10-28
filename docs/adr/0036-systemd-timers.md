# 0036. 주기 잡은 systemd timer가 run-job.sh로 돌린다

- 상태: 채택 (Supersedes [0010](0010-host-scheduler.md))
- 날짜: 2026-10-29

## 맥락

0010은 직접 만든 `scripts/scheduler.py`(주기 판정, flock, 상태 JSON, 제한 시간)로 잡을 돌렸다. D111은 가져다 쓸 것을 직접 만들지 않는다는 D89에 따라 이를 표준 도구로 바꾸라고 했다. 스케줄러를 부르는 쪽은 이미 systemd timer였으므로 "부르는 주체"와 "판정하는 코드"가 이중이었다.

## 결정

잡마다 `config/systemd/openit-<잡>.service`(Type=oneshot, `ExecStart`는 기존 `scripts/run-job.sh <compose 서비스>` 또는 백업 스크립트)와 `.timer`(`OnBootSec=1min`, `OnUnitActiveSec=<주기>`)를 둔다. `scheduler.py`, 그 시험, `config/jobs.yaml`, `schemas/jobs.schema.json`, 스케줄러 상태 파일을 지웠다. 개발·E2E는 `run-job.sh`를 직접 부른다. 결과·종료 코드는 journald에 남는다.

## 왜

- 표준: systemd.timer(5), systemd.service(5). `OnUnitActiveSec`은 서비스가 마지막으로 시작한 때부터의 주기라 옛 `last_start + interval_seconds`와 같은 뜻이다.
- 겹침 방지: oneshot 서비스가 실행 중이면 timer가 다시 시작하지 않는다(옛 flock과 같은 성질).
- 상태·실패 기록: `systemctl status`, `journalctl -u`가 마지막 실행·종료 코드를 남긴다. 0010이 "timer 단독으로는 남지 않는다"고 본 이유가 이 도구들로 풀린다. 실패 알림은 ADR 0037(Prometheus/Alertmanager)이 맡는다.
- 컨테이너에 docker 소켓을 주지 않는다는 0010의 근거는 그대로다(timer는 호스트에서 `docker compose run`을 부른다).

## 값의 출처

| 값 | 출처 |
| --- | --- |
| 수집기 600s, ops-feedback 3600s, 일일 잡 86400s(backup, survey-purge) | 사용자 결정 D85(표준 주기), 측정 안 함 |
| question-authoring-purge, release-gate-prune 86400s | 보존 단위가 일 단위라는 판단, 측정 안 함 |
| backup-restore-test 604800s | 시작값, 측정·표준 근거 없음 |
| `TimeoutStartSec=3600` | 옛 `scheduler.py --timeout` 기본값을 옮긴 것, 근거 없음, 측정 안 함 |
| `OnBootSec=1min` | 부팅 직후 도커가 올라올 시간을 주려는 시작값, 측정 안 함 |
| `AccuracySec=10s` | systemd 기본(1min)이 600s 주기에 비해 크므로 줄인 시작값, 측정 안 함 |

## 검토한 대안과 버리는 이유

- cron: 겹침 방지(flock)와 상태가 따로 필요하고 journald 연동이 약하다.
- 자체 스케줄러 유지: D89에 어긋난다.
- ofelia 등 docker 소켓 스케줄러: 0010과 같은 이유(호스트 권한 노출).

## 결과

- 얻는 것: 자체 코드 약 90줄과 상태 파일이 사라진다. 시험은 유닛 정적 시험(`scripts/test-systemd-units.sh`: 쌍, 주기, oneshot, 스크립트 존재, `systemd-analyze verify`)과 `run-job.sh`의 Compose 안 실행(E2E 단계 9)으로 나뉜다.
- 감수: 실제 timer가 도는 것은 이 리포 시험이 아니라 서버에서 `systemctl list-timers`로 본다(이 리포는 유닛을 설치하지 않는다). 옛 E2E의 "3초 주기에 3번 tick = 2번 실행" 시험은 systemd의 일이라 지웠다. `check_health`가 읽던 스케줄러 상태 파일이 없어져 잡 신선도 점검은 ADR 0037이 이어받는다.
- 시스템이 `systemd` 없이 도는 환경(cron)은 각 `.timer`의 주기를 `run-job.sh` 호출로 옮겨 적는다(runbook 5절).

## 되돌리는 조건

잡 사이 의존 순서·재시도가 필요해지거나 서버가 여러 대가 되면 워크플로 엔진을 검토한다(0010과 같다).
