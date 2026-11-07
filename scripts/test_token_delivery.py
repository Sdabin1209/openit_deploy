"""Token file ownership follows the certificate client's image contract, including DB names."""
import copy
import json
import pathlib
import sys
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # 파일을 직접 실행해도(자체 점검 목록) 리포의 openit_deploy 를 읽는다
from openit_deploy.wiring.token_delivery import prepare
from openit_deploy.wiring.schema_check import SchemaError


class TokenDelivery(unittest.TestCase):
    def setUp(self):
        root=pathlib.Path(__file__).resolve().parents[1]
        self.exported=json.loads((root/'schemas/examples/TokenExportData.valid.json').read_text())
        self.exported['tokens']['survey-service']='other-token'
        self.compose={'services':{name:{'image':'certificate-image','environment':{'STEP_ROLE':'cert','STEP_CERT_NAME':name,'STEP_CA_URL':'https://step-ca:9000'}} for name in self.exported['tokens']}}
        profile={'env_schema':'StepCaEnv','process':{'uid':1000,'gid':1000},'files':[],'writable':[],'capabilities':[],'sysctls':{}}
        declaration={'schema_version':1,'image':'step-ca','read_only_root':True,'exec_absolute_argv':True,'role_env':'STEP_ROLE','roles':{'cert':profile},'jobs':{}}
        self.labels={'io.openit.service':'step-ca','io.openit.revision':'abcdef1','io.openit.contracts.boundary':'v3.6.3','io.openit.contracts.survey-schema':'n/a','io.openit.inputs':json.dumps(declaration)}

    def test_db_and_application_tokens_use_declared_reader(self):
        result=prepare(self.exported,self.compose,labels_of=lambda image:self.labels)
        for name,record in result['tokens'].items():
            self.assertEqual((record['uid'],record['gid']),(1000,1000))
            self.assertEqual(record['value'],self.exported['tokens'][name])

    def test_image_identity_is_not_hardcoded(self):
        changed=copy.deepcopy(self.labels);declaration=json.loads(changed['io.openit.inputs']);declaration['roles']['cert']['process']={'uid':1777,'gid':1888};changed['io.openit.inputs']=json.dumps(declaration)
        result=prepare(self.exported,self.compose,labels_of=lambda image:changed)
        self.assertEqual(result['tokens']['survey-db']['uid'],1777)
        self.assertEqual(result['tokens']['survey-db']['gid'],1888)

    def test_unknown_client_rejected(self):
        self.compose['services'].pop('survey-db')
        with self.assertRaises(ValueError):prepare(self.exported,self.compose,labels_of=lambda image:self.labels)

    def test_path_in_token_name_rejected_before_image_inspection(self):
        self.exported['tokens']={'../escape':'opaque'}
        def no_inspection(image):self.fail('invalid transfer reached image inspection')
        with self.assertRaises(SchemaError):prepare(self.exported,self.compose,labels_of=no_inspection)

    def test_invalid_ca_content_is_rejected(self):
        self.exported['root']='not a certificate'
        with self.assertRaises(SchemaError):prepare(self.exported,self.compose,labels_of=lambda image:self.labels)

    def test_empty_token_rejected(self):
        self.exported['tokens']['survey-db']=''
        with self.assertRaises(SchemaError):prepare(self.exported,self.compose,labels_of=lambda image:self.labels)

    def test_controller_accepts_ansible_newline_framing(self):
        import base64
        import contextlib
        import io
        import tempfile
        from unittest.mock import patch
        from openit_deploy.wiring import token_delivery
        with tempfile.TemporaryDirectory() as directory:
            compose = pathlib.Path(directory) / 'compose.json'
            compose.write_text(json.dumps(self.compose))
            encoded = base64.b64encode(json.dumps(self.exported).encode()).decode() + '\n'
            output = io.StringIO()
            with patch('sys.stdin', io.StringIO(encoded)), patch.object(token_delivery, 'prepare', return_value={'prepared': True}) as prepare_call, contextlib.redirect_stdout(output):
                self.assertEqual(token_delivery.main(['--compose-json', str(compose)]), 0)
            self.assertEqual(prepare_call.call_args.args, (self.exported, self.compose))
            self.assertEqual(json.loads(base64.b64decode(output.getvalue())), {'prepared': True})

    def test_remote_accepts_ansible_newline_framing(self):
        import base64
        import contextlib
        import io
        from unittest.mock import patch
        from openit_deploy.wiring import put_tokens
        delivery = prepare(self.exported, self.compose, labels_of=lambda image: self.labels)
        framed = base64.b64encode(json.dumps(delivery).encode()).decode() + '\n'
        output = io.StringIO()
        with patch('sys.stdin', io.StringIO(framed)), patch.object(put_tokens, 'write_delivery', return_value={'tokens_written': 2, 'root_written': True}) as writer, contextlib.redirect_stdout(output):
            self.assertEqual(put_tokens.main(), 0)
        writer.assert_called_once_with(delivery)
        self.assertEqual(json.loads(output.getvalue()), {'tokens_written': 2, 'root_written': True})
        for token in self.exported['tokens'].values():
            self.assertNotIn(token, output.getvalue())

    def test_ansible_sends_only_prepared_delivery(self):
        root=pathlib.Path(__file__).resolve().parents[1]
        import yaml
        tasks=yaml.safe_load((root/'ansible/stage.yml').read_text())
        producer=next(t for t in tasks if t.get('register')=='token_delivery')
        consumer=next(t for t in tasks if '이 서버의 토큰 볼륨에 쓰기' in t['name'])
        self.assertTrue(producer['no_log'])
        self.assertEqual(producer['delegate_to'],'localhost')
        self.assertEqual(consumer['ansible.builtin.shell'].count('python /p.py'),1)
        self.assertIn('token_delivery.stdout',consumer['args']['stdin'])
        self.assertTrue(consumer['no_log'])



class TokenFileNames(unittest.TestCase):
    """계약 3.6.5: 토큰 하나는 STEP_TOKENS_DIR/<이름>.ott. 251바이트 이름(상한)도 원자적으로 쓸 수 있다(임시 이름이 대상 길이에 기대지 않는다)."""
    def test_longest_contract_name_is_written_atomically(self):
        import os, tempfile
        from openit_deploy.wiring import put_tokens
        name = ".".join(["a" * 63] * 3 + ["b" * 59])   # 251바이트(계약 DnsName 상한)
        self.assertEqual(len((name + ".ott").encode()), 255)
        with tempfile.TemporaryDirectory() as t:
            r, k = pathlib.Path(t) / "r", pathlib.Path(t) / "t"; r.mkdir(); k.mkdir()
            uid, gid = 4321, 4321   # 소유자 변경은 컨테이너 안 root 가 한다: 여기서는 요청한 소유자만 기록해 확인한다(이 시험의 대상은 이름 길이)
            from unittest.mock import patch
            calls = []
            with patch.object(put_tokens.os, "fchown", lambda fd, u, g: calls.append((u, g))):
                out = put_tokens.write_delivery({"root": "-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n", "tokens": {name: {"value": "tok", "uid": uid, "gid": gid}}}, root_dir=str(r), token_dir=str(k))
            self.assertEqual(out["tokens_written"], 1)
            self.assertIn((4321, 4321), calls)
            self.assertEqual((k / (name + ".ott")).read_text(), "tok")
            self.assertEqual(sorted(p.name for p in k.iterdir()), [name + ".ott"])   # 임시 파일이 남지 않는다

    def test_name_beyond_contract_limit_is_rejected_by_the_contract(self):
        from boundary_contracts import validator
        self.assertFalse(validator("StepCaEnv").is_valid({"STEP_ROLE": "cert", "STEP_CERT_NAME": ".".join(["a" * 63] * 3 + ["b" * 61])}))


if __name__ == '__main__':
    unittest.main()
