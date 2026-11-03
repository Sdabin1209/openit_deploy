#!/usr/bin/env python3
"""R6.2 (허용 목록 방식): 호출 관계 밖의 서비스 쌍은 망에서 안 닿는다. 허용되는 쌍은 compose 의 환경·설정에서 뽑은 호출 관계(`https://<서비스>`를 담은 호출자 -> 대상, 게이트웨이의 상류 포함)와
계약이 정한 호출(HTTP.md I1~I10) 중 compose 밖에서 일어나는 것(EXTRA)뿐이다. 범위는 사이드카를 둔 앱 + gateway 쌍이다(데이터베이스·감시·인증서 발급 망은 다른 점검).
알려진 위반(KNOWN)은 표에 적어 둔다: 그 쌍이 여전히 위반인지도 확인하므로(고치면 이 시험이 실패해 표에서 지우게 한다) 목록은 줄어들기만 한다. 사용: python3 scripts/test_service_pair_isolation.py"""
import copy, itertools, pathlib, sys, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_callers_trust_root as C  # noqa: E402

S = C.S
# 계약이 정한 호출 중 compose 서비스 사이에서 일어나지 않는 것(오프 컴포즈 호출자: model-lab, synthetic-data 는 compose 서비스가 아니다). 현재 없음.
EXTRA = set()
# 알려진 위반 V8: 호출 관계 없이 같은 망에 있는 쌍. 망 구조를 <서비스>-net 으로 옮기는 줄 T 1 에서 서비스별로 망을 다시 나눌 때 해소한다.
KNOWN = {
    frozenset(p): why for p, why in [
        (("admin-console", "kiosk-frontend"), "화면 두 개가 ui 망을 같이 쓴다(둘 다 게이트웨이 상류일 뿐)"),
        (("gateway", "model-serving"), "serving 망 공유(게이트웨이는 model-serving 을 부르지 않는다)"),
        (("model-registry", "question-authoring"), "release 망 공유"),
        (("model-serving", "ops-feedback-ingest"), "serving 망 공유"),
        (("ops-feedback-ingest", "release-gate"), "serving 망 공유"),
    ]
}


def scope(svcs):
    apps = {str(v["network_mode"]).split(":", 1)[1] for v in svcs.values() if str(v.get("network_mode") or "").startswith("service:")}
    return sorted(apps | {"gateway"})


def allowed(svcs):
    edges = set(EXTRA)
    for a, hits in C.callers(svcs).items():
        a = a[len("job-"):] if a.startswith("job-") else a
        for b in hits: edges.add(frozenset((a, b)))
    return edges


def violations(svcs):
    ok = allowed(svcs); out = {}
    for a, b in itertools.combinations(scope(svcs), 2):
        common = set(svcs[a].get("networks") or []) & set(svcs[b].get("networks") or [])
        if common and frozenset((a, b)) not in ok: out[frozenset((a, b))] = sorted(common)
    return out


class T(unittest.TestCase):
    def test_only_known_pairs_violate(self):
        v = violations(S)
        new = {tuple(sorted(k)): n for k, n in v.items() if k not in KNOWN}
        self.assertEqual(new, {}, "호출 관계 밖의 쌍이 같은 망에 있다(새 위반)")

    def test_known_list_has_no_stale_entries(self):
        v = violations(S)
        stale = [tuple(sorted(k)) for k in KNOWN if k not in v]
        self.assertEqual(stale, [], "고쳐진 쌍이 KNOWN 표에 남아 있다: 표에서 지운다")

    def test_allowlist_is_derived_not_empty(self):
        self.assertTrue(allowed(S), "호출 관계를 하나도 못 뽑았다")
        self.assertIn(frozenset(("survey-service", "release-gate")), allowed(S))

    def test_mutation_new_shared_network_is_caught(self):
        m = copy.deepcopy(S); m["admin-console"]["networks"] = list(m["admin-console"]["networks"]) + ["authoring"]
        self.assertTrue(any(k not in KNOWN for k in violations(m)), "일부러 admin-console 을 authoring 망에 붙였는데 새 위반이 안 잡힌다")


if __name__ == "__main__":
    unittest.main()
