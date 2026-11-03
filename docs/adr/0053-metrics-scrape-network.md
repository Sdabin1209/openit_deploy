# 0053. 소요 시간 지표 수집: monitoring 네트워크 하나에 두 서비스만 붙인다

- 상태: 채택 (U71, 2026-11-03)
- 날짜: 2026-11-03

## 맥락

계약 METRICS.md "운영 소요 시간 지표"가 survey-service(`openit_turn_duration_seconds`, `openit_model_call_duration_seconds`)와 model-runtime(`openit_model_engine_duration_seconds`, `openit_model_queue_wait_seconds`, `openit_next_item_overridden_total`)의 지표 이름을 정했고, 두 서비스는 내부망 `GET /metrics`(인증 없음, gateway에는 denied)로 낸다. 수집과 경보는 deploy 소관이다. 환자 턴 p95 2초 목표(D125)는 요청을 끊는 값이 아니라 경보로만 본다(ADR 0051).

수집을 처음 붙였을 때 "네트워크 불일치"로 되돌린 기록은 이 리포지토리의 커밋 이력과 문서에서 찾지 못했다(확인하지 못했다). 구조에서 알 수 있는 불일치 원인은 두 가지다. (1) Prometheus는 `monitoring` 네트워크에만 있고 두 서비스는 `serving` 등에만 있어 서로 닿지 않는다. (2) 감시 겹침 파일(`compose.monitoring.yaml`)에서 서비스의 `networks:`를 더하면, 그 파일만 쓰는 시험(`test-monitoring.sh`의 가짜 서비스 구성)과 외부 추론 모드(제품 안에 model-serving이 없다)에서 이미지 없는 빈 서비스 정의가 생기거나 대상이 없어진다.

## 결정

- `compose.yaml`이 `monitoring` 네트워크를 정의하고 survey-service와 model-serving만 붙인다. 겹침 파일의 `monitoring`(Prometheus 등)과 같은 이름이라 합쳐진다. 겹침 파일에서 서비스를 건드리지 않는다.
- Prometheus 수집 작업 둘: `survey-service-metrics`(고정 대상), `model-serving-metrics`(파일 대상 `inference-metrics-targets.yml`; 외부 추론 모드는 빈 목록 `PROMETHEUS_INFERENCE_METRICS_TARGETS=no-local-inference-targets.yml`, e2e.sh가 정한다).
- gateway는 `monitoring`에 붙지 않고 Caddyfile은 `/metrics`를 열지 않는다(공개 노출 없음).
- 경보(`config/prometheus/rules/openit.yml`): 환자 턴 p95 > 2초 5분(목표 D125), 모델 호출 p95 합 > 1.5초 5분, next_item 덮어쓰기 1시간 증가, 수집 대상 down 5분. `promtool test rules`로 경계를 시험한다.

## 왜

- 서비스 정의는 한 파일(compose.yaml)에 있고 네트워크 가입도 거기서 읽힌다. 겹침 파일이 다른 서비스를 고치지 않아 위 (2)가 사라진다.
- 전용 네트워크 하나는 Prometheus가 두 서비스의 `/metrics`에만 닿게 하는 가장 좁은 길이다. `serving`에 Prometheus를 붙이면 탐침 용도의 접근이 모든 serving 서비스로 넓어진다.
- 임계값 2초와 1.5초는 계약 METRICS.md의 목표 값이고, `for: 5m`·1시간 창은 시작값이며 측정하지 않았다.

## 검토한 대안과 버리는 이유

- Prometheus를 `serving`에 붙인다: 위와 같이 닿는 범위가 넓다.
- 겹침 파일에서 두 서비스에 `networks`를 더한다: 위 (2).
- 서비스가 지표를 푸시한다: 계약이 `/metrics` 노출로 정했다.

## 결과

- 얻는 것: 목표 초과·모델 호출 지연·next_item 덮어쓰기 증가를 경보로 본다. 수집이 끊기면 알린다.
- 감수하는 것: 감시 스택 컨테이너 전부(blackbox, json, node, alertmanager)가 같은 네트워크라 survey-service/model-serving의 `/metrics`에 닿을 수 있다(인증 없는 읽기 전용 지표). 모델 호출 합의 p95는 구할 수 없어 op별 p95의 합(상한 근사)으로 본다. next_item 경보는 계약 목표가 "추세 관찰"이라 임계값 없이 증가 여부만 본다. 알림 수신자는 아직 없다(alertmanager.yml).
- 확인하지 못한 것: 실제 두 서비스가 내는 지표 이름·라벨은 계약 문서로만 맞췄다(E2E 안 돌림).

## 되돌리는 조건

지표 수집을 서비스별 사이드카나 외부 수집기로 옮기면 대체한다.
