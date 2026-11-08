"""E2E 단언의 순수 함수. 서비스를 부르지 않고 입력(이미 읽어 온 값)만 판단하므로 일부러 틀린 값으로 실패하는지 자체 시험할 수 있다
(scripts/test_e2e_asserts.py). 환경 변수·토큰은 다루지 않는다."""


def check_fake_extraction(out, key, value, next_item, label=""):
    """가짜 A 출력이 기대한 한 칸 값과 다음 문항을 담았는지(model-runtime 0.7.1 규칙). 틀리면 AssertionError."""
    exp = [{"key": key, "precision": "exact", "save": True, "status": "ANSWERED", "value": value}]
    assert out.get("action") == "NEXT", f"{label} action 이 NEXT 가 아니다: {out}"
    assert out.get("values") == exp, f"{label} values 가 기대와 다르다: {out.get('values')} != {exp}"
    assert isinstance(out["values"][0]["value"], bool) == isinstance(value, bool), f"{label} 값 타입이 다르다: {out['values']}"
    assert out.get("next_item") == next_item, f"{label} next_item {out.get('next_item')} != {next_item} (건너뛰기 규칙)"
    return True


def check_out_of_range_reask(out, item, key, label=""):
    """범위 밖 값이 서버(model-runtime 0.10.0, 계약 2.4.0 value_rules)에서 데이터셋 정답 모양 REASK/OUT_OF_RANGE 로 바뀌었는지.
    같은 문항을 다시 묻고(next_item=item), 그 칸은 저장하지 않는 UNCLEAR(save false, value null)이며 reason·targets 가 범위 밖을 가리킨다. 틀리면 AssertionError."""
    assert out.get("action") == "REASK", f"{label} action 이 REASK 가 아니다: {out}"
    assert out.get("reason") == "OUT_OF_RANGE", f"{label} reason 이 OUT_OF_RANGE 가 아니다: {out}"
    assert out.get("next_item") == item, f"{label} 같은 문항을 다시 묻지 않는다: {out.get('next_item')} != {item}"
    assert out.get("targets") == [key], f"{label} targets 가 {[key]} 가 아니다: {out.get('targets')}"
    assert out.get("values") == [{"key": key, "precision": "unspecified", "save": False, "status": "UNCLEAR", "value": None}], f"{label} values 가 저장하지 않는 UNCLEAR 가 아니다: {out.get('values')}"
    return True


FAKE_TEXT = "(가짜 응답)"   # 추론 서버 fake 백엔드의 고정 응답 문장(계약 밖 시험 값: fake 백엔드를 정하는 model-runtime 의 시험 구성)


def server_text_ok(text, backend, expect=None):
    """응답 문장이 추론 서버(model-serving)가 낸 것임을 백엔드별로 본다. fake 는 출력이 고정이라 FAKE_TEXT 가 든다(expect 는 쓰지 않는다).
    그 밖의 백엔드(데모의 mimic)는 사람이 읽는 문장을 만들고 문장 틀은 model-runtime 이 정하므로, 틀은 단정하지 않고 서비스가 문진표에서 서버에 준 값을 대조한다:
    expect(문진표가 정한 다음 문항 문장)가 응답에 들어 있어야 한다. expect 가 없는 턴(되묻기·정정·직원 호출)은 비어 있지 않고 fake 의 고정 문장이 아님만 본다.
    서버를 거쳤다는 증명은 문장이 아니라 호출 쪽 /readyz inference.calls 증가(check_turns_clean)와 서버 /v1/info backend 가 맡는다."""
    t = str(text or "")
    if backend == "fake": return FAKE_TEXT in t
    return bool(t.strip()) and FAKE_TEXT not in t and (expect is None or expect in t)


def check_first_answer(first_q, want, vals, backend, flow_slots, response_text, next_sentence, label=""):
    """문진표 첫 문항의 첫 답 검증. 값이 저장돼 있으면 그 키가 문진표의 첫 문항(want)이어야 한다. 예외(값 없음)는 시험 입력에서 독립적으로 정한다:
    fake 가 아닌 백엔드이고 문진표의 첫 문항이 흐름 파일 slots 에 없을 때만, 값이 없어야 하고 응답에 문진표의 다음 문항 문장이 들어 있어야 한다.
    칸이 있는 첫 문항(A 의 Q1.D01)의 값이 비면 실패한다(결과가 비었다는 이유로 면제하지 않는다)."""
    assert first_q.startswith(want), (f"{label} 문진표의 첫 문항이 {want} 가 아니다", first_q)
    if backend != "fake" and first_q not in flow_slots:
        assert not vals, (f"{label} 흐름 파일에 칸이 없는 첫 문항 {first_q} 인데 값이 저장됐다", [v["key"] for v in vals])
        assert next_sentence in str(response_text), (f"{label} 칸 없는 첫 문항 뒤 응답에 문진표의 다음 문항 문장이 없다", next_sentence, str(response_text)[:160])
        return "slotless"
    assert vals and vals[0]["key"].startswith(want), (f"{label} 첫 문항이 {want} 가 아니다(저장된 값 없음 또는 다른 키)", [v["key"] for v in vals][:3])
    return "valued"


def check_turns_clean(replies, ready_before, ready_after, backend="fake", expects=None):
    """값이 나오는 턴들이 서비스의 검증·저장을 통과했는지. 각 응답에 실패 신호가 없고, 추론 호출이 턴마다 늘었으며,
    추론 실패·출력 형식 위반·재시도가 늘지 않았고, Trace 가 턴마다 전송 대기열에 들어갔는지(/readyz 숫자만 본다)."""
    n = len(replies)
    for i, r in enumerate(replies, 1):
        assert r.get("turn_failure_signal") is None, f"턴 {i} 에 실패 신호가 있다(검증·저장 실패): {r.get('turn_failure_signal')}"
        assert server_text_ok(r.get("response_text"), backend, (expects or {}).get(i - 1)), f"턴 {i} 응답이 model-serving({backend}) 문장이 아니다(기대 {((expects or {}).get(i - 1) or '')[:40]!r}): {str(r.get('response_text'))[:120]}"
    bi, ai = ready_before.get("inference") or {}, ready_after.get("inference") or {}
    assert ai.get("calls", 0) - bi.get("calls", 0) >= n, f"추론 호출이 턴 수만큼 늘지 않았다: {bi.get('calls')} -> {ai.get('calls')}"
    for k in ("failures", "output_invalid", "retries", "timeouts", "outcome_fallback"):
        assert ai.get(k, 0) == bi.get(k, 0), f"추론 {k} 가 늘었다: {bi.get(k)} -> {ai.get(k)}"
    so, sa = ready_before["trace_outbox"]["sent"], ready_after["trace_outbox"]["sent"]
    assert sa - so >= n, f"Trace 전송이 턴 수만큼 늘지 않았다: {so} -> {sa} (턴 {n})"
    return True


def check_unchanged(before, after, services):
    """서비스별 컨테이너 시작 시각(StartedAt)이 같고 ID 도 같은지. before/after: {서비스: (id, started_at)}."""
    for s in services:
        assert s in before and s in after, f"{s} 컨테이너를 찾지 못했다"
        assert before[s] == after[s], f"{s} 컨테이너가 바뀌었다(재시작·재생성): {before[s]} -> {after[s]}"
    return True


def check_release_loaded(status, release_id):
    """model-serving GET /v1/releases/{id} 응답이 새 릴리스의 LOADED 인지."""
    assert status.get("release_id") == release_id and status.get("state") == "LOADED" and not status.get("error"), f"새 릴리스가 LOADED 가 아니다: {status}"
    return True
