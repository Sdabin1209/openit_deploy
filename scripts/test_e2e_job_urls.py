#!/usr/bin/env python3
"""잡 컨테이너에 넘기는 dataset-store 주소는 호스트 주소(127.0.0.1·localhost, URL("ds"))가 아니다: 잡은 dataset-store 이미지 안에서 docker run 으로 돌아 컨테이너 안의 127.0.0.1 은 자기 자신이다(단계 7d 의 잡 HTTP 게시 실패 75).
정적 시험(e2e_steps.py 는 import 하면 환경 준비가 돈다): (1) {"kind": "http", "base_url": ...} 설정의 base_url 이 URL(...) 호출이나 127.0.0.1·localhost 문자열이 아니다
(2) 저장소가 http 인 잡은 compose 네트워크(datasets)에 붙인다(run_import 가 network 를 고른다). 사용: python3 scripts/test_e2e_job_urls.py"""
import ast, pathlib, unittest

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


if __name__ == "__main__":
    unittest.main()
