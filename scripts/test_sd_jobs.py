#!/usr/bin/env python3
"""sd_jobs.py 시험: (1) 라벨의 JobsDeclaration 을 계약 validator 로 검증해 잡을 고른다 (2) 명령 조립 (3) 실제 dataset-store 이미지(라벨 io.openit.jobs 가 있는 것)가 있으면
`import` 잡을 시험용 입력으로 실제로 돌려 게시 결과를 본다(없으면 그 시험만 건너뛴다: 통과로 세지 않고 출력에 SKIP 을 쓴다). 사용: <deploy .venv>/bin/python scripts/test_sd_jobs.py"""
import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sd_jobs
from boundary_contracts import validator

DECL = {"jobs": [{"name": "synthetic-import", "argv": ["python", "-m", "x", "import", "--config", "/config/import.json"], "idempotent": True,
                  "secret_files": ["DATASET_STORE_WRITE_TOKEN_FILE"], "config": {"container_path": "/config/import.json", "schema": "SyntheticJobConfigImport"}}]}
LABELS = {"io.openit.jobs": json.dumps(DECL)}


def find_image():
    r = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"], capture_output=True, text=True)
    for img in r.stdout.split() if r.returncode == 0 else []:
        if "dataset-store" not in img: continue
        lab = subprocess.run(["docker", "image", "inspect", img, "--format", "{{json .Config.Labels}}"], capture_output=True, text=True).stdout
        if "io.openit.jobs" in lab and "io.openit.exposure" in lab: return img
    return None


class T(unittest.TestCase):
    def test_find_job(self):
        self.assertEqual(sd_jobs.find_job(LABELS, "synthetic-import", validator)["config"]["container_path"], "/config/import.json")

    def test_find_job_errors(self):
        with self.assertRaises(AssertionError): sd_jobs.find_job({}, "synthetic-import", validator)
        with self.assertRaises(AssertionError): sd_jobs.find_job(LABELS, "nope", validator)
        bad = {"io.openit.jobs": json.dumps({"jobs": [{"name": "Bad Name", "argv": ["x"], "idempotent": True}]})}
        with self.assertRaises(AssertionError): sd_jobs.find_job(bad, "Bad Name", validator)

    def test_command(self):
        job = DECL["jobs"][0]
        c = sd_jobs.docker_cmd("docker", "img:1", job, "/w/c.json", "/w", "/sec", 1000, 1000, extra_ro=["/in"])
        s = " ".join(c)
        self.assertIn("-v /w/c.json:/config/import.json:ro", s)
        self.assertIn("/sec/tokens/dataset-store-write-synthetic-data:/run/secrets/dataset_store_write_token_file:ro", s)
        self.assertIn("-e DATASET_STORE_WRITE_TOKEN_FILE=/run/secrets/dataset_store_write_token_file", s)
        self.assertIn("-v /in:/in:ro", s)
        self.assertEqual(c[c.index("img:1"):], ["img:1"] + job["argv"])
        job2 = dict(job, secret_files=["UNKNOWN_FILE"])
        with self.assertRaises(AssertionError): sd_jobs.docker_cmd("docker", "i", job2, "/c", "/w", "/s", 1, 1)

    def test_real_import_job(self):
        img = find_image()
        if not img: self.skipTest("SKIP: io.openit.jobs 라벨이 있는 dataset-store 이미지가 없다(확인 못 함)")
        labels = json.loads(subprocess.check_output(["docker", "image", "inspect", img, "--format", "{{json .Config.Labels}}"], text=True))
        job = sd_jobs.find_job(labels, "synthetic-import", validator)
        inp = HERE.parent / "test/import-v2"
        with tempfile.TemporaryDirectory() as w:
            os.chmod(w, 0o755)
            sec = pathlib.Path(w) / "sec"; (sec / "tokens").mkdir(parents=True)
            (sec / "tokens/dataset-store-write-synthetic-data").write_text("x" * 32)   # 파일 저장소 게시라 값은 쓰이지 않는다(시험용 임의 값)
            cfg = {"dataset_id": "ds-sdjobs", "input_dir": str(inp), "survey_schema_dir": "image-env-takes-precedence",
                   "question_sets": [{"id": "qs-x", "version": "1", "content_hash": "sha256:" + "a" * 64}], "source_label": "sd-jobs-test",
                   "turn_engine_version": "0.0.0", "created_at": "2026-10-27T00:00:00Z", "tolerance": {"max_invalid_rows": 2, "max_invalid_rate": 1.0},
                   "output": {"work_dir": f"{w}/work", "store": {"kind": "file", "root": f"{w}/store"}}}
            self.assertEqual(list(validator("SyntheticJobConfigImport").iter_errors(cfg)), [])
            cp = pathlib.Path(w) / "import.json"; cp.write_text(json.dumps(cfg))
            r = subprocess.run(sd_jobs.docker_cmd("docker", img, job, str(cp), w, str(sec), os.getuid(), os.getgid(), extra_ro=[str(inp)]), capture_output=True, text=True)
            out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
            self.assertEqual(r.returncode, 0, (r.stderr + r.stdout)[-600:])
            self.assertIn(out.get("status"), ("PUBLISHED", "ALREADY_PUBLISHED"), out)
            self.assertTrue((pathlib.Path(w) / "work/import_report.json").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
