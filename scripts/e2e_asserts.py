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


def check_turns_clean(replies, ready_before, ready_after):
    """값이 나오는 턴들이 서비스의 검증·저장을 통과했는지. 각 응답에 실패 신호가 없고, 추론 호출이 턴마다 늘었으며,
    추론 실패·출력 형식 위반·재시도가 늘지 않았고, Trace 가 턴마다 전송 대기열에 들어갔는지(/readyz 숫자만 본다)."""
    n = len(replies)
    for i, r in enumerate(replies, 1):
        assert r.get("turn_failure_signal") is None, f"턴 {i} 에 실패 신호가 있다(검증·저장 실패): {r.get('turn_failure_signal')}"
        assert "(가짜 응답)" in str(r.get("response_text")), f"턴 {i} 응답이 model-serving 가짜 B 문장이 아니다: {str(r.get('response_text'))[:80]}"
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
