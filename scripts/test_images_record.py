"""images_record.py 시험: 서비스 한 줄씩 합치기, 목록 밖 줄 정리, 겹친 쓰기에서 줄이 사라지지 않음, 임시 파일이 남지 않음.
왜 이 시험: 2026-11-08 두 빌드가 겹쳐 build/images.env 가 21줄 중 4줄만 남았다(전체 빌드의 rm + sed -i/>> 경쟁)."""
import multiprocessing, os, pathlib, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import images_record as R


def _set(args):
    path, svc = args
    R.main([path, "set", svc, f"deploy-build/{svc}:abc", "abc", "bc=v1,mr=v2"])


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.p = os.path.join(self.tmp.name, "build", "images.env")

    def tearDown(self): self.tmp.cleanup()

    def rows(self): return pathlib.Path(self.p).read_text().splitlines()

    def test_set_replaces_only_that_service(self):
        R.main([self.p, "set", "a", "img-a:1", "c1"]); R.main([self.p, "set", "b", "img-b:1", "c1"])
        R.main([self.p, "set", "a", "img-a:2", "c2"])
        self.assertEqual(self.rows(), ["a img-a:2 c2", "b img-b:1 c1"])   # 부분 빌드가 다른 줄을 지우지 않는다

    def test_keep_drops_unlisted_only(self):
        for s in ("a", "b", "model-serving-gpu"): R.main([self.p, "set", s, f"img-{s}:1", "c"])
        R.main([self.p, "keep", "a", "b"])
        self.assertEqual([r.split()[0] for r in self.rows()], ["a", "b"])

    def test_concurrent_writers_lose_nothing(self):
        svcs = [f"s{i}" for i in range(24)]
        with multiprocessing.get_context("fork").Pool(8) as pool: pool.map(_set, [(self.p, s) for s in svcs])
        self.assertEqual(sorted(r.split()[0] for r in self.rows()), sorted(svcs))
        left = [f for f in os.listdir(os.path.dirname(self.p)) if f.startswith(".images.env.")]
        self.assertEqual(left, [], "임시 파일이 남았다")

    def test_usage_error(self):
        r = subprocess.run([sys.executable, str(HERE / "images_record.py"), self.p, "bogus"], capture_output=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
