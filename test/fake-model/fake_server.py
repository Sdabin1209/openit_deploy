"""시험 전용 가짜 모델 서버 진입점(E2E·데모의 fake 백엔드용). 운영 구성에 넣지 않는다(test/compose.fake-model.yaml 로만 붙는다).

model-runtime v0.6.1 의 서버를 그대로 쓰고(적재·해시·시스템 프롬프트 검사·HTTP 면은 실제 코드), FakeBackend 의 고정 출력만 바꾼다.
기본 고정 출력({"action":"NEXT","next_item":"END","values":[]})은 첫 문항에서도 END 로 건너뛰므로 turn-engine validate_extraction 이
NEXT_ITEM_MISMATCH/SKIP_ORDER_MISMATCH 로 반려하고 서비스의 모든 턴이 실패한다(v2 구조에서 확인). 이 출력은 입력 문항 기준으로 유효하다:
- LORA_A: ActionExtraction. action=NEXT, values=[], next_item = 문항 순서에서 입력 question_id 의 다음 문항(마지막이면 END).
  값을 추출하지 않으므로 어떤 답도 저장하지 않는다(모델 성능 시험이 아니다). 출력은 입력만으로 정해지는 고정 함수다.
- LORA_B: 문장 "(가짜 응답)" (기본값과 같다).
문항 순서는 학습 데이터셋 v2 의 31개 문항(survey-service 문진 스키마 data/question_flow.json 과 같은 순서)의 시험용 사본이다.
달라지면 E2E 가 실패해 알려 준다."""
import json
import re

import model_runtime.backends as backends
from model_runtime import server

ORDER = ["Q1.D01", "Q1.D02", "Q1.D03", "Q1.D04", "Q1.D05", "Q1.D06", "Q1.D07", "Q1.D08", "Q1.D09", "Q1.D10", "Q1.D11",
         "Q2.D01", "Q2.D02", "Q2.D03", "Q2.D04", "Q2.D05", "Q3", "Q4", "Q4_1", "Q5", "Q5_1", "Q6", "Q6_1", "Q7", "Q7_1", "Q7_2",
         "Q8_1", "Q8_2", "Q9_1", "Q9_2", "Q10"]
_USER_START = '{"current_question"'   # A 의 user 메시지는 입력 객체를 직렬화한 것이고 최상위 키가 알파벳 순이라 current_question 으로 시작한다(prompt-4)


def responder(req):
    if req.role != "LORA_A":
        return "(가짜 응답)"
    i = req.prompt.rfind(_USER_START)
    m = re.search(r'"question_id": "([^"]+)"', req.prompt[i:] if i >= 0 else req.prompt)
    qid = m.group(1) if m else None
    nxt = ORDER[ORDER.index(qid) + 1] if qid in ORDER and ORDER.index(qid) + 1 < len(ORDER) else "END"
    return json.dumps({"action": "NEXT", "next_item": nxt, "values": []}, ensure_ascii=False)


backends._default_responder = responder
server.main()
