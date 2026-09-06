"""Exercise firmware signing bodies directly, without importing hardware drivers."""
import ast
import binascii
import hashlib
import hmac
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_functions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in functions} != set(names):
        raise AssertionError('Firmware/gateway contract function was removed or renamed')
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), namespace)


class TestFirmwareHmacSourceContract(unittest.TestCase):
    def check_firmware(self, filename, device, features):
        secret = 'test-only-signing-contract-key'
        firmware = {'uhashlib': hashlib, 'ubinascii': binascii,
                    'DEVICE_ID': device, 'DEVICE_SECRET': secret}
        load_functions(ROOT/'firmware'/filename,
                       ['hmac_sha256', 'format_py_float', 'canonical_json', 'build_and_sign'], firmware)
        gateway = {'json': json, 'hmac': hmac, 'hashlib': hashlib,
                   'DEVICE_REGISTRY': {device: {'secret': secret}},
                   'verify_signature_with_rotation': lambda *args: False}
        load_functions(ROOT/'src/gateway.py', ['verify_signature'], gateway)
        for nonce in (None, 'abc123'):
            with self.subTest(firmware=filename, nonce=nonce):
                envelope = json.loads(firmware['build_and_sign'](features, 3, 14, 1780000000000, nonce))
                self.assertTrue(gateway['verify_signature'](device, envelope['payload'], envelope['signature']))
                changed = dict(envelope['payload'])
                changed[next(iter(features))] += 1
                self.assertFalse(gateway['verify_signature'](device, changed, envelope['signature']))

    def test_sw420_actual_signing_matches_gateway(self):
        self.check_firmware('main_sw420.py', 'esp32-vib-002',
                            {'trigger_rate': 15.625, 'duty_cycle': 0.125,
                             'burst_max_ms': 32.0, 'inter_event_cv': 0.0})

    def test_mpu6050_actual_signing_matches_gateway(self):
        self.check_firmware('main.py', 'esp32-vib-001',
                            {'rms': 1.0125, 'peak': 0.125, 'crest_factor': 0.1235,
                             'kurtosis': -1.0, 'dominant_freq': 15.625})


if __name__ == '__main__':
    unittest.main()
