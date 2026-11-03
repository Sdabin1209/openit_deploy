#!/usr/bin/env python3
"""단독 시험: 영역 게이트웨이마다 그 서비스 이미지의 Exposure 라벨이 exposure.json 으로 나간다(계약 Exposure validator 로 확인). 라벨이 없거나 어기면 거부. 변이: 라벨 없음·위반."""
import json, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from boundary_contracts import validator  # noqa: E402
from openit_deploy.wiring import cli_gen_gateways as G  # noqa: E402

EXPO = {"service": "survey-service", "routes": [{"paths": ["/v1/sessions"], "methods": ["POST"], "auth": {"kind": "device-token"}}], "egress": ["release-gate"]}
COMPOSE = {"services": {"survey-service": {"image": "img/s"}, "survey-service-gw": {"image": "img/gw"}, "gateway": {"image": "img/x"}}}


class T(unittest.TestCase):
    def test_valid_exposure_is_written_as_is(self):
        raw = json.dumps(EXPO)
        r = G.build(COMPOSE, lambda i: {"io.openit.exposure": raw}, validator)
        self.assertEqual(r, {"survey-service": raw})
        with tempfile.TemporaryDirectory() as d:   # 파일로 나간 내용은 라벨 그대로다
            import io, contextlib
            comp = Path(d) / "c.json"; comp.write_text(json.dumps(COMPOSE))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(G.main(["--out", d, "--compose-json", str(comp)], labels_of=lambda i: {"io.openit.exposure": raw}), 0)
            self.assertEqual(json.loads((Path(d) / "survey-service" / "exposure.json").read_text()), EXPO)

    def test_missing_or_invalid_label_is_refused(self):
        with self.assertRaises(SystemExit) as e:
            G.build(COMPOSE, lambda i: {}, validator)
        self.assertIn("io.openit.exposure 가 없다", str(e.exception))
        with self.assertRaises(SystemExit) as e:
            G.build(COMPOSE, lambda i: {"io.openit.exposure": json.dumps({"routes": "x"})}, validator)
        self.assertIn("Exposure 스키마 위반", str(e.exception))

    def test_gateway_without_its_service_is_refused(self):
        with self.assertRaises(SystemExit):
            G.build({"services": {"x-gw": {"image": "i"}}}, lambda i: {}, validator)


if __name__ == "__main__":
    unittest.main()
