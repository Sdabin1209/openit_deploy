"""Collect token I/O, bind the actual certificate-client identity, and validate before transfer."""
import argparse
import base64
import json
import os
import pathlib
import subprocess
import sys

from boundary_contracts import validator
from openit_deploy.wiring.schema_check import check


def image_labels(image):
    # Only public image metadata, never Config.Env or an entire container inspect.
    environment = dict(os.environ)
    if not environment.get('DOCKER_CONFIG'):
        config = pathlib.Path(__file__).resolve().parents[2] / 'state/docker-config'
        config.mkdir(parents=True, exist_ok=True)
        settings = config / 'config.json'
        try:
            with settings.open('x') as output:
                output.write('{}\n')
        except FileExistsError:
            pass
        environment['DOCKER_CONFIG'] = str(config)
    result = subprocess.run(['docker', 'image', 'inspect', image, '--format', '{{json .Config.Labels}}'],
                            capture_output=True, text=True, check=True, timeout=30, env=environment)
    return json.loads(result.stdout)


def prepare(exported, compose, *, labels_of=image_labels):
    check('TokenExportData', exported)
    required = set(exported['tokens'])
    owners, cache = {}, {}
    for service in compose['services'].values():
        environment = service.get('environment') or {}
        name = environment.get('STEP_CERT_NAME')
        if environment.get('STEP_ROLE') != 'cert' or name not in required:
            continue
        validator('StepCaEnv').validate(environment)
        image = service['image']
        if image not in cache:
            labels = labels_of(image)
            validator('ImageLabels').validate(labels)
            declaration = json.loads(labels['io.openit.inputs'])
            validator('ContainerInputs').validate(declaration)
            if declaration['image'] != labels['io.openit.service'] or declaration['role_env'] != 'STEP_ROLE':
                raise ValueError('certificate-client image identity does not match its declared role')
            cache[image] = declaration
        process = cache[image]['roles']['cert']['process']
        if name in owners and owners[name] != process:
            raise ValueError('certificate clients for the same token disagree on their process identity')
        owners[name] = process
    if set(owners) != required:
        raise ValueError('token has no declared certificate client in the target configuration')
    delivery = {'root': exported['root'], 'tokens': {
        name: {'value': value, 'uid': owners[name]['uid'], 'gid': owners[name]['gid']}
        for name, value in exported['tokens'].items()}}
    check('TokenDeliveryRequest', delivery)
    return delivery


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compose-json', required=True)
    args = parser.parse_args(argv)
    try:
        exported = json.loads(base64.b64decode(sys.stdin.read().strip(), validate=True))
        compose = json.loads(pathlib.Path(args.compose_json).read_text())
        delivery = prepare(exported, compose)
    except Exception as error:
        # Input includes opaque secrets: exception messages may contain their values.
        print(f'token delivery failed: {type(error).__name__}', file=sys.stderr)
        return 1
    print(base64.b64encode(json.dumps(delivery).encode()).decode())
    return 0
