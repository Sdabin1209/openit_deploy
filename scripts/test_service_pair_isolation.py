#!/usr/bin/env python3
"""R6.2 양방향(허용 목록 방식): (1) 호출 관계 밖의 쌍은 공통 망이 없다. (2) 반대로 호출 관계 안의 모든 쌍은 공통 망이 있다(망을 나누다 필요한 길을 끊지 않았는지).
(2)의 범위: compose 환경·설정에서 뽑은 호출(서비스·잡 -> 대상, 게이트웨이 상류), 서비스 -> postgres(DSN 비밀이 있는 앱), 인증서 컨테이너 -> step-ca, 그리고 compose 밖에서 도는 호출자의 길(synthetic-data 잡 -> question-authoring I1·ops-feedback-ingest I7, dataset-store I2: E2E 가 잡을 붙이는 망 authoring·datasets).
(1)은 이렇다: 호출 관계 밖의 서비스 쌍은 망에서 안 닿는다. 허용되는 쌍은 compose 의 환경·설정에서 뽑은 호출 관계(`https://<서비스>`를 담은 호출자 -> 대상, 게이트웨이의 상류 포함)와
계약이 정한 호출(HTTP.md I1~I10) 중 compose 밖에서 일어나는 것(EXTRA)뿐이다. 범위는 사이드카를 둔 앱 + gateway 쌍이다(데이터베이스·감시·인증서 발급 망은 다른 점검).
예외 표는 없다: 허용 목록 밖의 쌍이 하나라도 공통 망을 가지면 실패한다(V8 로 드러난 5쌍은 망을 나눠 해소했다). 사용: python3 scripts/test_service_pair_isolation.py"""
import copy, itertools, pathlib, sys, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_callers_trust_root as C  # noqa: E402
from compose_nets import nets  # noqa: E402   # network_mode 를 따라가 앱의 망(= <서비스>-net 의 망)을 돌려준다

S = C.S
# 계약이 정한 호출 중 compose 서비스 사이에서 일어나지 않는 것(오프 컴포즈 호출자: model-lab, synthetic-data 는 compose 서비스가 아니다). 현재 없음.
EXTRA = set()
DB_OF = {"survey": "survey-db", "qa": "question-authoring-db", "ops_log": "ops-feedback-db", "ops_failure": "ops-feedback-db", "gate": "release-gate-db", "keycloak": "keycloak-db"}   # DB 계정 -> 영역 DB 서비스


def scope(svcs):
    apps = {n[:-4] for n in svcs if n.endswith("-tls")}   # TLS 종단을 둔 앱(<서비스>-tls 의 <서비스>)
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
        common = set(nets(svcs, a)) & set(nets(svcs, b))
        if common and frozenset((a, b)) not in ok: out[frozenset((a, b))] = sorted(common)
    return out


# compose 밖에서 도는 호출자(잡을 이 망에 붙여 돌린다, e2e_steps.py SD_RUN_NETWORK·DS_JOB_NETWORK): 망 이름 -> 그 망에 있어야 하는 대상들(계약 I1·I7·I2)
OFF_COMPOSE_RUNNERS = {"authoring": ["question-authoring", "ops-feedback-ingest"], "datasets": ["dataset-store"]}


def missing_paths(svcs):
    """호출 관계 안인데 공통 망이 없는 쌍(양방향 점검의 위반)."""
    miss = []
    for a, hits in C.callers(svcs).items():
        cmd = " ".join(str(x) for x in (svcs[a].get("command") or []))
        if a.startswith("job-") and ("purge" in a or "prune" in a): continue   # 이름으로 정한다: 잡 명령은 이미지 라벨에서 오므로 compose 의 command 로는 알 수 없다(S10)   # 보존 정리 잡은 서버와 같은 환경(R7.2)을 받을 뿐 DB 밖의 서비스를 부르지 않는다
        for b in hits:
            if b in svcs and not (set(nets(svcs, a)) & set(nets(svcs, b))): miss.append((a, b, "호출"))
    for n, sv in svcs.items():
        for x in (sv.get("secrets") or []):   # 영역마다 자기 DB 컨테이너: DSN 비밀(db-<계정>-dsn)을 가진 서비스는 그 계정의 DB 와 공통 망이 있어야 한다
            if str(x).startswith("db-") and str(x).endswith("-dsn") and not n.startswith("job-"):
                db = DB_OF.get(str(x)[3:].replace("-app-dsn", "").replace("-dsn", "").replace("-", "_"))
                if db in svcs and not (set(nets(svcs, n)) & set(nets(svcs, db))): miss.append((n, db, "DSN"))
        if n.endswith("-cert") and "step-ca" in svcs and not (set(nets(svcs, n)) & set(nets(svcs, "step-ca"))): miss.append((n, "step-ca", "인증서 발급"))
    for net, targets in OFF_COMPOSE_RUNNERS.items():
        for t in targets:
            if net not in nets(svcs, t): miss.append((f"(compose 밖 호출자 @{net})", t, "계약 I1·I7·I2"))
    return miss


class T(unittest.TestCase):
    def test_every_call_relation_has_a_common_network(self):
        self.assertEqual(missing_paths(S), [], "호출 관계 안인데 공통 망이 없다(망을 나누다 필요한 길을 끊었다)")

    def test_changed_pairs_are_connected(self):
        # 이번에 망을 나눈 쌍을 이름으로 못박는다(계약 호출: release-gate->QA I1, release-gate->registry I3, survey->ops I6, ops job->gate I4, gateway->각 상류)
        want = [("release-gate", "question-authoring"), ("release-gate", "model-registry"), ("survey-service", "ops-feedback-ingest"), ("survey-service", "release-gate"),
                ("survey-service", "model-serving"), ("model-serving", "release-gate"), ("job-ops-feedback", "release-gate"), ("job-release-gate-collect", "question-authoring"),
                ("job-release-gate-collect", "model-registry"), ("question-authoring", "ops-feedback-ingest"), ("gateway", "kiosk-frontend"), ("gateway", "admin-console")]
        bad = [w for w in want if not (set(nets(S, w[0])) & set(nets(S, w[1])))]
        self.assertEqual(bad, [], "바꾼 쌍이 공통 망을 잃었다")

    def test_mutation_removing_a_path_is_caught(self):
        m = copy.deepcopy(S); m["release-gate-net"]["networks"] = {k: v for k, v in m["release-gate-net"]["networks"].items() if k != "release-qa"}   # release-gate 를 release-qa 에서 뺀다
        self.assertTrue(any(x[0] == "release-gate" and x[1] == "question-authoring" for x in missing_paths(m)), "필요한 길을 끊었는데 안 잡힌다")

    def test_no_pair_outside_the_call_relations_shares_a_network(self):
        v = {tuple(sorted(k)): n for k, n in violations(S).items()}
        self.assertEqual(v, {}, "호출 관계 밖의 쌍이 같은 망에 있다")

    def test_allowlist_is_derived_not_empty(self):
        self.assertTrue(allowed(S), "호출 관계를 하나도 못 뽑았다")
        self.assertIn(frozenset(("survey-service", "release-gate")), allowed(S))

    def test_mutation_new_shared_network_is_caught(self):
        m = copy.deepcopy(S); m["admin-console-net"]["networks"] = list(m["admin-console-net"]["networks"]) + ["authoring"]   # 공간 소유자에 망을 더한다
        self.assertTrue(violations(m), "일부러 admin-console 을 authoring 망에 붙였는데 위반이 안 잡힌다")


if __name__ == "__main__":
    unittest.main()
