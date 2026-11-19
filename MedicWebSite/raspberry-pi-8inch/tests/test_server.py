import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

CAPTURE_ID = '6ce92c83-cc62-4dd8-a231-aa58a8e6c274'


class FakeHardware(server.BaseHTTPRequestHandler):
    commands = []

    def log_message(self, *_):
        pass

    def reply(self, data, code=200, mime='application/json'):
        body = json.dumps(data).encode() if isinstance(data, dict) else data
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get('Authorization') != 'Bearer test-device-secret':
            return self.reply({'success': False}, 401)
        if self.path == '/api/v1/status':
            return self.reply({'success': True, 'cameras': {'camera1': 0, 'camera2': 2}})
        if self.path.endswith('/verification'):
            return self.reply({'success': True, 'status': 'completed', 'result': {
                'outcome': 'IDENTIFIED', 'fused_result': {'final_prediction': 'REXULTI 1mg'}}})
        if self.path == '/api/v1/preview/stream?camera=1':
            return self.reply(b'--frame\r\nContent-Type: image/jpeg\r\n\r\nTESTFRAME\r\n', mime='multipart/x-mixed-replace; boundary=frame')
        if '/camera/' in self.path:
            return self.reply(b'JPEG-TEST', mime='image/jpeg')
        return self.reply({'error': 'not_found'}, 404)

    def do_POST(self):
        if self.headers.get('Authorization') != 'Bearer test-device-secret':
            return self.reply({'success': False}, 401)
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.commands.append((self.path, payload))
        if self.path == '/api/v1/commands':
            return self.reply({'success': True, 'result': {'captureId': CAPTURE_ID, 'backendUpload': {'status': 'queued'}}})
        return self.reply({'success': True})


class TerminalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = server.HARDWARE, server.DEVICE_TOKEN, server.JOBS_DIR, server.ACTIVE_REQUEST
        server.DEVICE_TOKEN = 'test-device-secret'
        server.JOBS_DIR = Path(self.temp.name) / 'requests'
        server.ACTIVE_REQUEST = None
        FakeHardware.commands = []
        self.hardware = server.ThreadingHTTPServer(('127.0.0.1', 0), FakeHardware)
        self.hw_thread = threading.Thread(target=self.hardware.serve_forever, daemon=True)
        self.hw_thread.start()
        server.HARDWARE = f'http://127.0.0.1:{self.hardware.server_port}'
        server.initialize()
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join()
        self.hardware.shutdown(); self.hardware.server_close(); self.hw_thread.join()
        server.HARDWARE, server.DEVICE_TOKEN, server.JOBS_DIR, server.ACTIVE_REQUEST = self.previous
        self.temp.cleanup()

    def post(self, route, value, origin=None):
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        with urlopen(Request(self.base + route, json.dumps(value).encode(), headers), timeout=3) as response:
            return json.load(response)

    def get(self, route):
        with urlopen(self.base + route, timeout=3) as response:
            return json.load(response)

    def await_job(self, request_id):
        for _ in range(100):
            state = self.get('/api/device/requests/' + request_id)
            if state['status'] != 'capturing':
                return state
            time.sleep(.01)
        self.fail('capture worker did not finish')

    def test_full_capture_proxy_and_duplicate_request(self):
        request_id = str(server.uuid.uuid4())
        for _ in range(2):
            self.post('/api/device/capture', {'requestId': request_id})
        state = self.await_job(request_id)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(state['result']['captureId'], CAPTURE_ID)
        self.assertEqual(len(FakeHardware.commands), 1)
        self.assertEqual(FakeHardware.commands[0][1]['payload'],
                         {'lightMode': 'white', 'brightness': 85, 'sendToServer': True})
        result = self.get(f'/api/device/captures/{CAPTURE_ID}/verification')
        self.assertEqual(result['result']['fused_result']['final_prediction'], 'REXULTI 1mg')

    def test_preview_lighting_is_fixed_and_token_stays_server_side(self):
        self.post('/api/device/preview/start', {'brightness': 1, 'lightMode': 'uv'})
        self.assertEqual(FakeHardware.commands[-1][1], {'lightMode': 'white', 'brightness': 85})
        status = self.get('/api/device/status')
        self.assertNotIn('test-device-secret', json.dumps(status))
        self.post('/api/device/preview/stop', {})

    def test_cross_origin_invalid_ids_and_old_storage_endpoints(self):
        with self.assertRaises(HTTPError) as error:
            self.post('/api/device/preview/start', {}, 'https://evil.invalid')
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            self.post('/api/device/capture', {'requestId': '../bad'})
        self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            self.post('/api/records', {})
        self.assertEqual(error.exception.code, 404)
        self.assertEqual(FakeHardware.commands, [])

    def test_stream_session_query_and_photo_proxy(self):
        with urlopen(self.base + '/api/device/preview/stream?camera=1&session=123') as response:
            self.assertIn(b'TESTFRAME', response.read())
        with urlopen(self.base + f'/api/device/captures/{CAPTURE_ID}/camera/2') as response:
            self.assertEqual(response.read(), b'JPEG-TEST')
        with self.assertRaises(HTTPError):
            urlopen(self.base + '/api/device/preview/stream?camera=2')

    def test_timeout_is_uncertain_and_never_auto_retries(self):
        request_id = str(server.uuid.uuid4())
        with patch.object(server, 'upstream_json', side_effect=TimeoutError):
            self.post('/api/device/capture', {'requestId': request_id})
            self.assertEqual(self.await_job(request_id)['status'], 'uncertain')
        self.post('/api/device/capture', {'requestId': request_id})
        self.assertEqual(FakeHardware.commands, [])

    def test_only_one_capture_can_be_inflight(self):
        server.ACTIVE_REQUEST = str(server.uuid.uuid4())
        with self.assertRaises(HTTPError) as error:
            self.post('/api/device/capture', {'requestId': str(server.uuid.uuid4())})
        self.assertEqual(error.exception.code, 409)
        with self.assertRaises(HTTPError) as error:
            self.post('/api/device/preview/stop', {})
        self.assertEqual(error.exception.code, 409)

    def test_server_error_after_capture_is_not_assumed_safe_to_repeat(self):
        request_id = str(server.uuid.uuid4())
        error = HTTPError('http://hardware.invalid', 500, 'failed', {}, None)
        with patch.object(server, 'upstream_json', side_effect=error):
            self.post('/api/device/capture', {'requestId': request_id})
            self.assertEqual(self.await_job(request_id)['status'], 'uncertain')
    def test_restart_marks_inflight_uncertain_preserving_old_data(self):
        request_id = str(server.uuid.uuid4())
        server.write_job(request_id, {'status': 'capturing'})
        old_db = Path(self.temp.name) / 'pos.sqlite3'
        old_db.write_bytes(b'PREVIOUS DATA')
        server.initialize()
        self.assertEqual(server.read_job(request_id)['status'], 'uncertain')
        self.assertEqual(old_db.read_bytes(), b'PREVIOUS DATA')

    def test_static_assets_and_secrets_not_exposed(self):
        for path in ('/', '/app.js', '/styles.css', '/workflow.js', '/vendor/zxing-browser.min.js', '/api/status'):
            with urlopen(self.base + path) as response:
                self.assertEqual(response.status, 200)
        for path in ('/.env', '/api/catalog', '/api/records', '/data/requests/anything'):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.base + path)
            self.assertEqual(error.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
