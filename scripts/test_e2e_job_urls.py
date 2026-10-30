#!/usr/bin/env python3
"""잡 컨테이너에 넘기는 dataset-store 주소는 호스트 주소(127.0.0.1·localhost, URL("ds"))가 아니다: 잡은 dataset-store 이미지 안에서 docker run 으로 돌아 컨테이너 안의 127.0.0.1 은 자기 자신이다(단계 7d 의 잡 HTTP 게시 실패 75).
정적 시험(e2e_steps.py 는 import 하면 환경 준비가 돈다): (1) {"kind": "http", "base_url": ...} 설정의 base_url 이 URL(...) 호출이나 127.0.0.1·localhost 문자열이 아니다
(2) 저장소가 http 인 잡은 compose 네트워크(datasets)에 붙인다(run_import 가 network 를 고른다).
(3) 컨테이너에서 도는 잡의 설정에 들어가는 모든 base_url 이 서비스 이름 주소이고, 잡 네트워크가 compose.yaml 에서 그 서비스들이 실제로 붙은 네트워크이며, 주소의 포트가 compose 헬스체크의 컨테이너 포트와 같다.
(4) deploy 전체에 `--network host`·network="host"·기본 네트워크(호출자가 고르지 않는 값)가 없다: Docker Desktop 에서 host 네트워크는 호스트의 127.0.0.1 게시 포트에 닿지 못한다. 사용: <deploy .venv>/bin/python scripts/test_e2e_job_urls.py"""
import ast, pathlib, re, subprocess, unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (pathlib.Path(__file__).resolve().parent / "e2e_steps.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)


class T(unittest.TestCase):
    def test_http_store_base_url_is_not_a_host_address(self):
        found = []
        for n in ast.walk(TREE):
            if isinstance(n, ast.Dict):
                d = {k.value: v for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant)}
                if isinstance(d.get("kind"), ast.Constant) and d["kind"].value == "http" and "base_url" in d:
                    found.append((n.lineno, ast.unparse(d["base_url"])))
        self.assertTrue(found, "kind=http 저장소 설정을 찾지 못했다(시험이 낡았다)")
        for ln, v in found:
            self.assertNotRegex(v, r"URL\(|127\.0\.0\.1|localhost", f"행 {ln}: 잡에 넘기는 base_url 이 호스트 주소다: {v}")

    def test_service_name_url_constant(self):
        self.assertIn('DS_JOB_URL = "http://dataset-store:8080"', SRC)

    def test_http_store_jobs_join_compose_network(self):
        self.assertIn('network=net', SRC)
        self.assertIn('f"{a.project}_datasets"', SRC)
        self.assertIn('store_root.get("kind") == "http"', SRC)

    def test_every_job_base_url_is_service_name(self):
        urls = {}
        for n in ast.walk(TREE):
            if isinstance(n, ast.Dict):
                d = {k.value: v for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant)}
                if "base_url" in d: urls[n.lineno] = ast.unparse(d["base_url"])
        self.assertGreaterEqual(len(urls), 3, "잡 설정의 base_url 을 찾지 못했다")
        for ln, v in urls.items():
            self.assertNotRegex(v, r"URL\(|127\.0\.0\.1|localhost", f"행 {ln}: 잡 설정의 base_url 이 호스트 주소다: {v}")

    def test_job_networks_and_ports_match_compose(self):
        comp = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
        consts = dict(re.findall(r'^(SD_QA_JOB_URL|SD_OPS_JOB_URL|DS_JOB_URL) = "(http://[a-z-]+:\d+)"', SRC, re.M))
        self.assertEqual(sorted(consts), ["DS_JOB_URL", "SD_OPS_JOB_URL", "SD_QA_JOB_URL"])
        nets = {k: re.search(r'^%s = lambda: f"\{a\.project\}_([a-z-]+)"' % k, SRC, re.M).group(1) for k in ("SD_RUN_NETWORK", "DS_JOB_NETWORK")}
        for const, url in consts.items():
            host, port = re.fullmatch(r"http://([a-z-]+):(\d+)", url).groups()
            self.assertIn(host, comp, f"{const}: compose 에 서비스 {host} 가 없다")
            hc = " ".join(comp[host].get("healthcheck", {}).get("test", []))
            self.assertIn(f":{port}/", hc, f"{const}: 포트 {port} 가 {host} 컨테이너 포트(헬스체크)와 다르다")
            net = nets["DS_JOB_NETWORK"] if const == "DS_JOB_URL" else nets["SD_RUN_NETWORK"]
            self.assertIn(net, comp[host]["networks"], f"{const}: 잡 네트워크 {net} 에 {host} 가 붙어 있지 않다")

    def test_no_host_network_or_default_network_anywhere(self):
        files = subprocess.run(["git", "ls-files", "scripts"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        bad = []
        for f in files:
            if not f.endswith((".py", ".sh")) or pathlib.Path(f).name.startswith("test") or f.endswith("test_e2e_job_urls.py"): continue
            for i, l in enumerate((ROOT / f).read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r'--network[ =]host|network="host"|network=\'host\'|net=host', l) or re.search(r'def (docker_cmd|run_job)\(.*network\s*=\s*["\']', l):
                    bad.append(f"{f}:{i}")
        self.assertEqual(bad, [], f"host/기본 네트워크가 남아 있다: {bad}")


if __name__ == "__main__":
    unittest.main()
