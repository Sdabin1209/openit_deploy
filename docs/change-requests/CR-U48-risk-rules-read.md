# CR-U48: E2E가 survey-service 내부 파일을 읽어 위험 문구를 얻는다

> 처리됨(wo-30): 헤드가 안 A로 정했다. deploy가 `test/risk-rules.e2e.json`(계약 SurveyRiskRulesFile)을 만들어 `test/compose.risk-rules.yaml`로 `SURVEY_RISK_RULES_FILE`에 연결하고, 5f·5m·5n은 그 파일의 문구를 쓴다. `risk_phrase_from_defaults()`는 지웠다. 아래는 결정 전의 기록이다.

작성: deploy, 2026-10-30, wo-29. 상태: 제안(코드 변경 없음). 결정: 헤드.

## 지금 무엇을 하는가
`scripts/e2e_steps.py`의 `risk_phrase_from_defaults()`(단계 5f, 5m, 5n이 한 곳씩 부른다)가 `../survey-service/survey_service/risk_rules.py`를 ast로 읽어 `_PROVISIONAL` 상수에서 위험 문구 하나와 규칙 키 목록을 얻는다. 이 파일은 survey-service의 내부 구현이다. 구조 규칙 1(영역은 서로의 구조를 모른다)과 워크스페이스 규칙(읽는 것은 문진 스키마, boundary-contracts, areas.json만)을 어긴다. 그리고 파일 위치·상수 이름이 바뀌면 E2E가 영역 내부 때문에 깨진다.

## 무엇을 확인하려는가
세 가지다.
1. **발화가 위험 규칙에 걸리면 정지한다**: 위험 문구를 담은 발화 턴이 정지하고 직원 알림이 나간다(D88 U1). 5f(기록 5k)가 기본 목록으로 확인하고, 5m은 모델 서버가 멈춘 중에도 알림이 먼저 나가는지 본다.
2. **위험 문구가 없는 발화는 정상 진행한다**(5f).
3. 위험 정지 세션의 `pause_reason=RISK`, 재알림, 기기 격리(5n).
세 경우 모두 필요한 것은 "서비스가 위험으로 판정할 발화 문구 하나"뿐이다. 규칙 목록의 내용 자체를 검증하지는 않는다(5f는 `/readyz`의 `staff_alert_source.rule_count > 0`만 본다).

## 안
- **안 A (권장): E2E가 자기 규칙 파일을 주입한다.** survey-service는 이미 `SURVEY_RISK_RULES_FILE`(JSON)을 받는다(`survey_service/settings.py`, 영역이 정한 설정). deploy가 시험용 규칙 파일을 만들어 마운트하고, 그 안의 문구를 E2E가 쓴다. 문구를 영역 내부에서 읽을 필요가 없고 시험 입력을 deploy가 정한다. 필요한 것: 그 파일의 모양이 계약 스키마(예: `RiskRules`)로 있어야 deploy가 영역 내부를 보지 않고 만들 수 있다. 지금 모양은 survey-service 내부 문서에만 있을 것이다(확인 못 함). 그래서 survey-service가 모양을 계약으로 올려 달라는 요청이 따라온다. 제약: `/readyz`의 `source`가 `PROVISIONAL_DEFAULT`가 아니게 되므로 5f의 "기본 켜짐" 검사(source == PROVISIONAL_DEFAULT)는 따로 둔다(기본 목록이 켜져 있다는 사실 확인은 `/readyz` 필드로 계속 가능).
- **안 B: survey-service가 시험용 발화를 영역 API로 낸다.** 예: `/readyz`의 `staff_alert_source`에 `sample_trigger` 같은 필드를 더하거나 라벨/계약 산출물로 내보낸다. deploy는 그 값을 읽기만 한다. 단점: 운영 `/readyz`에 시험용 정보가 나가고, 계약(`/readyz` 모양)이 바뀐다.
- **안 C: 문구를 deploy 설정에 고정한다.** 영역이 기본 목록을 바꾸면 E2E가 깨진다. 값이 두 곳이 된다. 권하지 않는다.

권장 근거: A는 이미 있는 설정 경로를 쓰고(영역 코드 변경은 계약 스키마 하나), 시험 입력을 deploy가 소유하며, 영역 내부를 읽지 않는다. B는 운영 API에 시험 목적을 섞는다. 측정한 것은 없다(코드와 설정 이름을 읽은 판단).

## 요청 (헤드가 안을 정한 뒤)
- 안 A면: 계약에 위험 규칙 파일 스키마, survey-service가 그 스키마로 `SURVEY_RISK_RULES_FILE`을 검증하고 `/readyz`에 규칙 파일 출처를 보이는지 확인. 그 뒤 deploy가 `risk_phrase_from_defaults()`를 지우고 시험용 규칙 파일을 만든다(`config/`, E2E에서 마운트).
- 안 B면: survey-service와 계약 변경 요청.

## 영향 범위(deploy 쪽)
`scripts/e2e_steps.py`의 `risk_phrase_from_defaults()`와 이를 부르는 세 곳(5f, 5m, 5n), compose의 survey-service 환경(안 A일 때 규칙 파일 마운트).
