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


# survey-service 가 되묻기·확인 연속 정지에 쓰는 실효 한도(graph.py _reask_cap, survey-service ADR-0014·0020): /readyz 의 reask_limit({"active", "max_consecutive"})와
# 활성 문항 세트 session_settings 의 ask_limit·confirm_limit·unrecognized_streak_limit 중 1 이상 정수인 값들의 **최솟값**이다(문항 세트가 정한 값이 있으면 그것이 서비스 한도를 낮춘다).
# 서비스 한도가 꺼져 있으면(active false) 문항 세트 값만으로 정해진다. 둘 다 없으면 0(한도 없음).
REASK_AUTHORED_KEYS = ("ask_limit", "confirm_limit", "unrecognized_streak_limit")


def effective_reask_cap(reask_limit, session_settings) -> int:
    cap = reask_limit.get("max_consecutive", 0) if isinstance(reask_limit, dict) and reask_limit.get("active") is True else 0
    authored = [session_settings.get(k) for k in REASK_AUTHORED_KEYS]
    authored = [a for a in authored if isinstance(a, int) and not isinstance(a, bool) and a >= 1]
    return min(authored + ([cap] if cap > 0 else [])) if authored else cap
