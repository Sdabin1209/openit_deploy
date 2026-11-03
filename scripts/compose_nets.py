"""정적 시험용 도우미(ADR 0060): 서비스가 붙은 망의 목록. network_mode: service:<X> 인 서비스(앱·사이드카)는 <X>(= <서비스>-net, pause)의 망을 쓴다."""


def nets(svcs, name):
    s = svcs[name]
    mode = str(s.get("network_mode") or "")
    if mode.startswith("service:"):
        s = svcs[mode.split(":", 1)[1]]
    n = s.get("networks") or []
    return sorted(n.keys() if isinstance(n, dict) else n)
