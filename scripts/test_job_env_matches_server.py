#!/usr/bin/env python3
"""R7.2 / 12-Factor XII: 일회성 관리 잡은 상시 서버와 같은 환경·비밀·신뢰로 실행한다. 서버와 갈라지면 계약 Env 선언이 잡을 거부한다(3차 E2E).
잡 목록과 짝(잡 -> 서버)은 compose.yaml 에서 뽑는다(고정 목록 없음): job-* 서비스마다 **같은 이미지**를 쓰는 상시 서버(일회성 migrate 제외)가 짝이다.
(1) env_file 이 있는 잡은 서버와 environment·secrets·env_file 이 완전히 같다. (2) job-ops-feedback 은 별도 프로그램(ops_feedback.job)이라 완전히 같을 수 없다:
같은 이름의 환경 변수는 같은 값이고, 서버에 없는 키(게이트 토큰·비식별 salt)만 잡에 더 있다. (3) 신뢰(SSL_CERT_FILE)와 루트 마운트는 모든 잡이 서버와 같다.
(4) check_config_contracts 는 완전히 같은 짝의 잡도 서버와 같은 Env 스키마로 검사한다. 사용: python3 scripts/test_job_env_matches_server.py"""
import pathlib, sys, unittest, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
S = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
ONESHOT = {n for n, s in S.items() if n.endswith("-migrate") or n in ("pki-root", "pki-tokens")}


def pairs():
    out = {}
    for j, js in S.items():
        if not j.startswith("job-"): continue
        if "OPENIT_BACKUP_URL" in (js.get("environment") or {}): continue   # 백업 잡은 서버와 다른 프로그램이다(자격·저장소 암호를 받고 영역 pod 안에서 돈다): test_backup_wiring.py 가 본다
        cands = [n for n, x in S.items() if not n.startswith("job-") and n not in ONESHOT and x.get("image") == js.get("image")]
        out[j] = sorted(set(cands))
    return out


STRICT_EXCEPTIONS = {"job-identity-register-users": "별도 프로그램(사용자 등록 잡 register-users): 관리 암호 파일과 루트만 받고 IdP 서버의 다른 환경은 필요 없다(계약 JobsDeclaration, 3.4.16)", "job-ops-feedback": "별도 프로그램(ops_feedback.job): 게이트 토큰·비식별 salt 가 더 필요하고 서버 토큰은 필요 없다"}


class T(unittest.TestCase):
    def test_every_job_has_exactly_one_server_with_the_same_image(self):
        P = pairs()
        self.assertTrue(P)
        bad = {j: c for j, c in P.items() if len(c) != 1}
        self.assertEqual(bad, {}, "잡마다 같은 이미지를 쓰는 상시 서버가 하나여야 짝을 정할 수 있다")

    def test_strict_pairs_have_the_same_env_secrets_and_trust(self):
        for j, (sv,) in pairs().items():
            if j in STRICT_EXCEPTIONS: continue
            self.assertEqual(S[j].get("environment"), S[sv].get("environment"), j)
            self.assertEqual(S[j].get("secrets"), S[sv].get("secrets"), j)
            self.assertEqual(S[j].get("env_file"), S[sv].get("env_file"), j)

    def test_exception_pair_shares_common_keys_and_trust(self):
        P = pairs()
        for j in STRICT_EXCEPTIONS:
            self.assertIn(j, P, "예외 표의 잡이 compose 에 없다")
            (sv,) = P[j]
            je, se = S[j].get("environment") or {}, S[sv].get("environment") or {}
            diff = {k: (je[k], se[k]) for k in je.keys() & se.keys() if je[k] != se[k]}
            self.assertEqual(diff, {}, f"{j}: 서버와 같은 이름의 환경 변수는 같은 값이어야 한다(예외 사유: {STRICT_EXCEPTIONS[j]})")
            self.assertEqual(je.get("SSL_CERT_FILE"), se.get("SSL_CERT_FILE"))
            jv = [str(v) for v in S[j].get("volumes") or [] if "pki-root" in str(v)]
            self.assertTrue(jv, "잡이 루트 인증서 볼륨을 마운트하지 않는다")

    def test_every_job_trusts_the_same_root_as_its_server(self):
        for j, (sv,) in pairs().items():
            self.assertEqual((S[j].get("environment") or {}).get("SSL_CERT_FILE"), (S[sv].get("environment") or {}).get("SSL_CERT_FILE"), j)
            self.assertEqual(any("pki-root" in str(v) for v in S[j].get("volumes") or []), any("pki-root" in str(v) for v in S[sv].get("volumes") or []), j)

    def test_contract_check_covers_strict_jobs(self):
        from openit_deploy.wiring.cli_check_config_contracts import ENV_SERVICES
        for j, (sv,) in pairs().items():
            if j in STRICT_EXCEPTIONS: continue
            self.assertIn(j, ENV_SERVICES, f"{j} 가 계약 Env 검사 대상(ENV_SERVICES)에 없다")
            self.assertEqual(ENV_SERVICES[j][0], ENV_SERVICES[sv][0], j)

    def test_mutation_detected(self):
        # 변이 확인: 메모리 사본에서 잡 환경을 바꾸면 비교가 어긋난다(작업 트리 파일은 건드리지 않는다)
        import copy
        m = copy.deepcopy(S); j = "job-survey-purge"; sv = pairs()[j][0]
        m[j]["environment"] = dict(m[j].get("environment") or {}, SURVEY_X="1")
        self.assertNotEqual(m[j].get("environment"), m[sv].get("environment"))


if __name__ == "__main__":
    unittest.main()
