import ast
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class HardwareReuseTests(unittest.TestCase):
    def test_wrapper_imports_original_with_lcd_disabled(self):
        spec = importlib.util.spec_from_file_location('kiosk_hw', ROOT / 'hardware_service.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'hardware.py'
            source.write_text('import os\nlcd_enabled=os.environ["MEDILENS_LCD_ENABLED"]\n', encoding='utf-8')
            with patch.dict(os.environ, {'MEDILENS_HARDWARE_SOURCE': str(source), 'MEDILENS_LCD_ENABLED': 'true'}):
                loaded = module.load_hardware()
                self.assertEqual(loaded.lcd_enabled, 'false')
                self.assertEqual(os.environ['MEDILENS_LISTEN_HOST'], '127.0.0.1')
            sys.modules.pop('mediguard_original_hardware', None)

    def test_original_uploader_keeps_front_back_mapping(self):
        source = ROOT.parent / 'raspberry_pi/hardware.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'forward_capture_to_backend')
        states, uploads = [], []

        def post(url, **kwargs):
            uploads.append((url, kwargs['files']['front_image'][1].read(), kwargs['files']['back_image'][1].read()))
            return types.SimpleNamespace(ok=True, json=lambda: {'verification_id': 'test-result'})

        namespace = {'Path': Path, 'BACKEND_UPLOAD_URL': 'http://server.invalid/api/v1/verifications',
                     'BACKEND_UPLOAD_TOKEN': 'secret',
                     'write_verification_state': lambda capture_id, state: states.append(state)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {'requests': types.SimpleNamespace(post=post)}):
            front, back = Path(directory) / 'front.jpg', Path(directory) / 'back.jpg'
            front.write_bytes(b'front-camera-1'); back.write_bytes(b'back-camera-2')
            namespace['forward_capture_to_backend']('capture-id', front, back)
        self.assertEqual(uploads[0][1:], (b'front-camera-1', b'back-camera-2'))
        self.assertEqual(states[-1]['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
