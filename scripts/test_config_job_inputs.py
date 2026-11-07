"""정식 설치 계약으로 설정 경로 → 입력 마운트의 허용·거부를 검사한다."""
import copy
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from boundary_contracts import validator
from openit_deploy.wiring.sd_jobs import config_mount_inputs


class ConfigInputs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "input").mkdir()
        self.path = self.root / "config.json"
        self.job = {"name":"import", "argv":["/bin/job"], "idempotent":True, "config":{"container_path":"/config/import.json","schema":"SyntheticJobConfigImport"}}
        self.config = {"dataset_id":"ds-review", "input_dir":"input", "survey_schema_dir":"packaged", "question_sets":[{"id":"qs-review","version":"1","content_hash":"sha256:"+"a"*64}], "source_label":"review", "action_rules_version":"2", "tolerance":{"max_invalid_rows":0,"max_invalid_rate":0.0}, "output":{"work_dir":"results", "store":{"kind":"file","root":"store"}}}
        profile = {"env_schema":"SyntheticJobEnv", "process":{"uid":10001,"gid":10001},"files":[],"writable":[{"path":"/tmp","persist":False,"written_by":{"uid":10001,"gid":10001}}],"capabilities":[],"sysctls":{}}
        self.inputs = {"schema_version":1,"image":"dataset-store","read_only_root":True,"exec_absolute_argv":True,"role_env":None,"roles":{"default":copy.deepcopy(profile)},"jobs":{"import":dict(profile,config_paths={"/input_dir":{"access":"read","required":True},"/output/work_dir":{"access":"write","required":True},"/output/store/root":{"access":"write","required":False}})}}

    def materialize(self):
        self.path.write_text(json.dumps(self.config))
        return config_mount_inputs(self.inputs,self.job,self.path,self.root,validator=validator)

    def test_declared_relative_paths_and_permissions(self):
        result = self.materialize()
        self.assertEqual([m["target"] for m in result["mounts"]],["/config/input","/config/results","/config/store"])
        self.assertEqual([m["read_only"] for m in result["mounts"]],[True,False,False])
        self.assertEqual((self.root/"results").stat().st_mode & 0o2770,0o2770)
        self.assertTrue(result["read_only_root"])

    def test_kernel_requirements_are_not_discarded(self):
        from openit_deploy.components.job_command import run
        from openit_deploy.wiring.schema_check import check
        self.inputs['jobs']['import']['sysctls'] = {'net.ipv4.ip_unprivileged_port_start': 0}
        runtime = self.materialize()
        request = dict(docker='docker', image='image', job={'argv':['/job'], 'config':{'container_path':'/config/job.json'}}, config_path=str(self.path), work=str(self.root), secrets_dir=str(self.root), uid=os.getuid(), gid=os.getgid(), network='none', **runtime)
        check('JobCommandRequest', request)
        argv = run(request)['argv']
        self.assertEqual(argv[argv.index('--sysctl') + 1], 'net.ipv4.ip_unprivileged_port_start=0')
        request['sysctls'] = {'unknown.kernel.setting': 1}
        with self.assertRaises(ValueError):
            check('JobCommandRequest', request)

    def test_optional_file_store_path_absent_for_http_store(self):   # 계약 4.0.0: memory 저장소는 설정에서 없어졌다. http 저장소는 마운트할 경로가 없다
        self.config["output"]["store"]={"kind":"http","base_url":"https://dataset-store","token_secret":"DATASET_STORE_WRITE_TOKEN"}
        self.assertEqual(len(self.materialize()["mounts"]),2)

    def test_invalid_input_rejected_before_output_directories_created(self):
        cases=[lambda c:c.update(input_dir="missing"),lambda c:c["output"].update(work_dir="../escape"),lambda c:c["output"].update(work_dir="store"),lambda c:c.update(input_dir="."),lambda c:c["output"].update(work_dir="bad\0path")]
        original=copy.deepcopy(self.config)
        for mutate in cases:
            self.config=copy.deepcopy(original);mutate(self.config)
            with self.subTest(config=self.config):
                with self.assertRaises(ValueError):self.materialize()
                self.assertFalse((self.root/"results").exists())

    def test_missing_required_pointer_is_rejected(self):
        self.inputs["jobs"]["import"]["config_paths"]["/missing"]={"access":"read","required":True}
        with self.assertRaises(ValueError):self.materialize()

    def test_other_owner_output_directory_is_rejected(self):
        target=self.root/"results";target.mkdir()
        with patch("os.getuid",return_value=os.getuid()+1):
            with self.assertRaises(ValueError):self.materialize()


if __name__ == "__main__":unittest.main()
