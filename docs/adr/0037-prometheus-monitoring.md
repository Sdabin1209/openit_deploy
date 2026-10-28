# 0037. 상태 감시는 Prometheus + blackbox_exporter + json_exporter + node_exporter + Alertmanager

- 상태: 채택
- 날짜: 2026-10-29

## 맥락

`scripts/check_health.py`(약 130줄)는 디스크 사용률, 스케줄러 상태 파일의 잡 실패·지연, 외부 감시 대상과 서비스 `/readyz` 응답, release-gate 판정 루프, 백업 나이를 한 번 읽고 OK/WARN/CRIT 종료 코드를 냈다. 직접 만든 감시기이고, 알림 수단과 이력(그래프)이 없다. D111은 이를 표준 도구로 바꾸라고 했다.

## 결정

`compose.monitoring.yaml`로 5개 컨테이너를 둔다(이미지는 `scripts/lock-third-party.sh`가 digest로 고정): Prometheus v3.5.0, Alertmanager v0.28.1, blackbox_exporter v0.27.0, json_exporter v0.7.0, node_exporter v1.9.1. 경보 규칙은 `config/prometheus/rules/openit.yml`, 시험은 `promtool test rules`다. `check_health.py`, `check-health.sh`, 그 시험, `config/external-monitor.example.yaml`, check-health systemd 유닛을 지웠다.

옛 조건과 새 경보의 대응은 runbook 5-1절 표다. 임계값은 옛 점검 값 그대로다(디스크 80/90%, 판정 루프 실패 1/3회·900초, 잡 지연 주기의 2배+60초, 탐침 제한 시간 5초).

## 왜

- 표준: Prometheus 문서의 blackbox 탐침(`/probe` + relabel), node_exporter filesystem·textfile collector(배치 잡 결과는 textfile이 문서가 권하는 방식), Alertmanager 라우팅, `promtool test rules`(규칙 단위 시험).
- json_exporter: 판정 루프 필드(연속 실패 횟수, 마지막 실행 시각, 인증 실패)는 숫자 비교가 필요해 blackbox 본문 정규식으로 옮길 수 없다. `/readyz`가 503이어도 본문을 읽도록 `valid_status_codes: [200, 503]`이다.
- 주기 잡 결과: systemd 서비스의 `ExecStopPost=scripts/job-metrics.sh <잡> <주기>`가 textfile(.prom)을 원자적으로 쓴다. `.timer`의 주기와 같은 값을 `test-systemd-units.sh`가 대조한다.

## 값의 출처

| 값 | 출처 |
| --- | --- |
| 디스크 80/90%, 판정 루프 실패 1/3회, 900초, 잡 2배+60초, 탐침 제한 5초, 백업 2일(= 일일 백업의 2배) | 옛 `check_health.py`의 값을 그대로 옮김(옛 값도 "헤드가 정한 표준 관행의 시작값", 측정 안 함) |
| `scrape_interval`/`evaluation_interval` 1m, 보존 15d | Prometheus 기본값, 측정 안 함 |
| `for:` ProbeDown 2m, 디스크 5m, 나머지 0m | 시작값. 옛 점검은 순간값이었고 스크랩 떨림으로 울리지 않게 둔 것, 측정 안 함 |
| 컨테이너 자원 한도(512m/0.5cpu 등) | 시작값, 측정 안 함(ADR 0023과 같은 처지) |
| Alertmanager `group_wait`/`group_interval`/`repeat_interval` | Alertmanager 기본값 |

## 검토한 대안과 버리는 이유

- 자체 감시기 유지: D89에 어긋나고 이력·알림이 없다.
- Zabbix/Nagios/Grafana Agent: 단일 서버에서 컨테이너 몇 개로 끝나는 Prometheus 계열이 compose 구성과 `promtool` 시험이 가장 가깝다. 다른 도구와 비교 측정은 하지 않았다.
- Pushgateway로 잡 결과: 호스트 systemd 잡이 푸시해야 하고 오래된 지표가 남는다. textfile이 더 단순하다.
- cAdvisor/Docker 소켓: 컨테이너에 docker 소켓을 주지 않는 원칙(ADR 0010·0036) 때문에 쓰지 않는다. 컨테이너 생존은 `/healthz`·`/readyz` 탐침으로 본다.

## 결과

- 얻는 것: 지표 이력, Alertmanager 화면/API, 규칙 단위 시험, 자체 코드 약 130줄 삭제.
- 감수: 상시 컨테이너 5개(메모리 한도 합 약 1GB, 측정 안 함). 옛 점검과 다른 점(runbook 5-1절): 백업 파일 나이를 직접 보지 않고 잡의 마지막 성공 시각으로 본다, 평문 백업 경고는 restic(3단계) 도입으로 의미가 없어진다, `last_run_at` null은 경보가 없다, gateway HTTPS 탐침은 서버 밖 감시의 몫이다.
- node_exporter는 호스트 `/`를 읽기 전용으로 마운트한다(`--path.rootfs`). 기본 `/:/host:ro`에서는 하위 마운트(별도 디스크)가 보이지 않는다. `/`가 shared인 리눅스 서버에서는 `NODE_EXPORTER_ROOT_MOUNT=/:/host:ro,rslave`로 하위 마운트까지 본다(WSL/Docker Desktop에서 rslave는 "not a shared mount"로 거부됨을 확인했다).
- 알림 수단(수신자)은 사용자 결정 대기라 Alertmanager에 수신자가 없다. 경보는 화면/API에서만 보인다.
- 서버 전체 중단은 이 스택도 같이 죽는다. 서버 밖 감시(D10)는 별개다(`external-targets.yml`에 같은 탐침을 거는 자리).

## 되돌리는 조건

단일 서버 운영자가 Prometheus 스택을 운영할 수 없다고 판단되면 감시 범위를 줄이는 새 결정(D111의 되돌리는 조건).
