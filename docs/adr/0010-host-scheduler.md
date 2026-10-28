# 0010. 주기 잡은 호스트의 가벼운 스케줄러(scheduler.py tick)가 `docker compose run --rm`으로 돌린다

- 상태: 대체됨(Superseded by [0036](0036-systemd-timers.md))
- 날짜: 2026-10-28

## 맥락

영역 사이의 자동 연결은 저장소를 보고 일하는 멱등 잡이고, 잡을 언제 돌리는지는 deploy의 스케줄러가 정한다(D39). 잡은 영역마다 다른 이미지·볼륨·네트워크에서 돌아야 한다(수집기는 release-gate 이미지, 실패 사례 선별은 ops-feedback 이미지). GPU가 필요한 잡(`where: gpu-external`)은 서빙 서버 밖이다(D40).

## 결정

`scripts/scheduler.py`(`tick` 한 번 실행 후 종료, `status`, `loop`)가 `config/jobs.yaml`을 읽어 기한이 된 잡을 `docker compose run --rm`(프로필 `jobs`)으로 한 번 돌린다. 상태는 `state/scheduler.json`(잡마다 마지막 시작·종료·종료 코드). `tick`을 부르는 주체는 서버의 systemd timer 또는 cron이고 이 리포는 예시 유닛만 둔다(`config/systemd/`). 주기는 설정에만 있고 코드에 기본값이 없다(`interval_seconds`가 null이면 실행하지 않는다).

## 왜 (따른 표준과 근거)

- 최소 권한: 컨테이너에 docker 소켓을 주지 않는다. 소켓은 호스트 root 권한과 같다. 출처: docs/design.md 7절.
- 잡이 그 영역의 이미지에서 한 번 돌고 끝난다(run-to-completion). 영역은 스스로 다른 영역을 깨우지 않는다(D39).
- 멱등: 같은 잡이 실행 중이면 건너뛰고(flock), 기한 전에는 아무것도 하지 않는다. `tick`을 몇 번 불러도 안전하다. E2E 단계 9가 3초 주기 시험 잡으로 '3번 tick = 2번 실행'을 확인한다(scripts/e2e.sh).
- 상태 파일의 마지막 종료 코드와 시작 시각을 `check-health.sh`가 읽어 CRIT/WARN을 낸다(docs/runbook.md). cron이나 timer 단독으로는 이 상태가 남지 않는다(코드에서 읽은 차이).
- 주기 값(수집기 600초, ops-feedback 3600초, 백업 86400초)은 D85에서 정한 시작값이고 측정하지 않았다(docs/design.md 7절).

## 검토한 대안과 버리는 이유

- 컨테이너 안 cron/supercronic: 잡마다 다른 이미지에서 돌아야 해서 cron 컨테이너가 잡마다 이미지를 갖거나 docker를 불러야 한다(docs/design.md 7절).
- ofelia 같은 docker 소켓 스케줄러: 컨테이너에 docker 소켓을 줘야 해서 서버 권한을 넘긴다(같은 곳).
- cron/systemd timer가 잡 명령을 직접 부르기: **이 대안만을 따로 비교한 기록은 없다.** 코드에서 읽은 차이는 위(잠금, null 주기 거부, `where` 필터, 상태 파일)이며, `tick`을 부르는 주체로는 쓴다.

## 결과

- 호스트에 python과 PyYAML이 필요하다(`.venv`). 호스트 프로세스라 서버 재부팅 뒤 timer가 `tick`을 다시 부르는 설정은 운영자가 한다(이 리포는 설치하지 않는다).
- 잡 병렬 실행·재시도·의존 순서는 없다(필요가 생기면 이 결정을 다시 본다).

## 되돌리는 조건

잡이 수십 개로 늘어 의존 순서·재시도가 필요해지거나 서버가 여러 대가 되면 워크플로 엔진(예: Kubernetes CronJob)을 검토한다.
