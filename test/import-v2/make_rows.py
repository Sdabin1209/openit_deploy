#!/usr/bin/env python3
"""E2E 단계 2(synthetic-data 게시기)의 시험용 입력 jsonl 6개를 만든다. 사용: .venv/bin/python test/import-v2/make_rows.py
이 데이터는 데이터셋 담당의 실제 학습 데이터가 아니다. 이 E2E를 위해 직접 만든 아주 작은 모음이다.
행 형식(human_review, scenario_id, split, messages[system,user,assistant])은 synthetic-data 문서(design.md 부록 A)의 **추정**을 따른 것이고 학습 서버 파일로 확인한 적 없다.
user/assistant 내용은 boundary-contracts v2 스키마(ActionExtractionInput/ActionExtraction, ResponseRequest/ResponseText)로 이 스크립트가 직접 검증한다.
일부러 만든 위반: lora_a_train.jsonl 에 v2 출력 위반 행 1개(action 만 있음), lora_b_val.jsonl 에 JSON 이 아닌 줄 1개 -> 위반 2행(허용치 시험용)."""
import json, pathlib
import boundary_contracts as bc

OUT = pathlib.Path(__file__).parent
SYS = "시험용 시스템 프롬프트(실제 학습 프롬프트가 아님)"
# E2E 문항 흐름(test/fake-model/question_flow.json)의 실제 칸 키를 쓴다
QS = [("Q1.D01", "Q1.D01.diagnosed", "Q1.D02"), ("Q1.D02", "Q1.D02.diagnosed", "Q1.D03"), ("Q1.D03", "Q1.D03.diagnosed", "Q1.D04"), ("Q1.D04", "Q1.D04.diagnosed", "Q1.D05")]
UTT = [("네 있어요", True), ("아니요 없어요", False)]

def a_pair(i, qid, key, nxt, utt, val, split="x"):
    utt = f"{utt} ({split} {i})"   # 분할 사이에 같은 발화+맥락이 겹치면 synthetic-data 게시기가 거부한다(누수 방지): 분할·번호를 발화에 넣어 모두 다르게 한다
    inp = {"question_id": qid, "current_question": f"시험 문항 {qid}입니다.", "user_utterance": utt, "state": {}}
    out = {"values": [{"key": key, "value": val, "precision": "exact", "status": "ANSWERED", "save": True}], "action": "NEXT", "next_item": nxt}
    bc.validator("ActionExtractionInput").validate(inp); bc.validator("ActionExtraction").validate(out)
    return inp, json.dumps(out, ensure_ascii=False)

def b_pair(i, qid, nxt, utt, val, split="x"):
    utt = f"{utt} ({split} {i})"
    inp = {"action": "NEXT", "topic": f"시험 {qid}", "user_utterance": utt, "known": f"{qid} {'있음' if val else '없음'}",
           "next": {"type": "NEXT", "question_id": nxt, "text": f"시험 문항 {nxt}입니다."}}
    out = f"{'네' if val else '아니요'}, 알겠습니다. 시험 문항 {nxt}입니다."
    bc.validator("ResponseRequest").validate(inp); bc.validator("ResponseText").validate(out)
    return inp, out

def row(split, scenario, inp, asst):
    return {"human_review": "auto_only", "scenario_id": scenario, "split": split,
            "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": json.dumps(inp, ensure_ascii=False)}, {"role": "assistant", "content": asst}]}

for role in ("a", "b"):
    for split in ("train", "val", "test"):
        lines = []
        for i, (qid, key, nxt) in enumerate(QS):
            utt, val = UTT[i % 2]
            inp, asst = (a_pair if role == "a" else b_pair)(i, *( (qid, key, nxt) if role == "a" else (qid, nxt) ), utt, val, split)
            lines.append(json.dumps(row(split, f"sc-{split}-{i}", inp, asst), ensure_ascii=False))
        if (role, split) == ("a", "train"):
            bad = row(split, "sc-train-bad", *a_pair(0, *QS[0], *UTT[0], split="bad")[:1], json.dumps({"action": "NEXT"}))
            lines.append(json.dumps(bad, ensure_ascii=False))
        if (role, split) == ("b", "val"):
            lines.append("이 줄은 JSON이 아니다(시험용 위반)")
        (OUT / f"lora_{role}_{split}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("done")
