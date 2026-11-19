"""Lightweight prescription verification UI and local hardware API proxy."""
import json
import os
from pathlib import Path
import re
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent
for line in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines() if (ROOT / '.env').exists() else []:
    if line.strip() and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())
HARDWARE = os.environ.get('POS_HARDWARE_URL', 'http://127.0.0.1:5000').rstrip('/')
DEVICE_TOKEN = os.environ.get('MEDILENS_DEVICE_TOKEN', '')
JOBS_DIR = Path(os.environ.get('POS_REQUEST_DIR', str(ROOT / 'data' / 'requests')))
CAPTURE_TIMEOUT = 120
MAX_JSON = 1024 * 1024
LOCK = threading.RLock()
ACTIVE_REQUEST = None
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = build_opener(ProxyHandler({}), NoRedirect())


def initialize():
    address = urlsplit(HARDWARE)
    if address.scheme not in ('http', 'https') or not address.hostname or address.username or address.password or address.query or address.fragment:
        raise ValueError('POS_HARDWARE_URL 必須是無帳密與查詢參數的 HTTP(S) 位址。')
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    # Never automatically repeat a capture after a proxy restart.
    for path in JOBS_DIR.glob('*.json'):
        if not re.fullmatch(UUID, path.stem):
            continue
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
            if state.get('status') == 'capturing':
                write_job(path.stem, {'status': 'uncertain', 'error': '服務曾重新啟動；請先確認上次拍攝結果，避免重複送出。'})
        except (OSError, ValueError):
            continue


def upstream(path, payload=None, timeout=10):
    headers = {'Accept': 'application/json'}
    if DEVICE_TOKEN:
        headers['Authorization'] = 'Bearer ' + DEVICE_TOKEN
    body = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(payload).encode()
    return OPENER.open(Request(HARDWARE + '/api/v1' + path, body, headers), timeout=timeout)


def upstream_json(path, payload=None, timeout=10):
    with upstream(path, payload, timeout) as response:
        body = response.read(MAX_JSON + 1)
        if len(body) > MAX_JSON:
            raise ValueError('upstream_response_too_large')
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError('invalid_upstream_response')
        return value


def write_job(request_id, state):
    state = dict(state, requestId=request_id, updatedAt=datetime.now(timezone.utc).isoformat())
    with LOCK:
        target = JOBS_DIR / (request_id + '.json')
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        temporary.replace(target)
    return state


def read_job(request_id):
    with LOCK:
        path = JOBS_DIR / (request_id + '.json')
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None


def capture_worker(request_id):
    global ACTIVE_REQUEST
    try:
        result = upstream_json('/commands', {
            'commandId': request_id, 'deviceId': 'medibox-01', 'type': 'capture',
            'payload': {'lightMode': 'white', 'brightness': 85, 'sendToServer': True},
        }, timeout=CAPTURE_TIMEOUT)
        if result.get('success') is False or not result.get('result', {}).get('captureId'):
            write_job(request_id, {'status': 'failed', 'error': '拍攝未完成，請檢查鏡頭與硬體服務。'})
        else:
            write_job(request_id, {'status': 'completed', 'result': result['result']})
    except HTTPError as error:
        certain_rejection = error.code in (400, 401, 403, 409)
        write_job(request_id, {'status': 'failed' if certain_rejection else 'uncertain',
                              'error': '硬體服務拒絕或未確認拍攝，請先檢查硬體日誌。'})
    except Exception:
        # A timeout does not prove that the hardware failed to save/send the pair.
        write_job(request_id, {'status': 'uncertain', 'error': '未收到拍攝確認；請先檢查硬體紀錄，勿直接重複拍攝。'})
    finally:
        with LOCK:
            ACTIVE_REQUEST = None


def start_capture(request_id):
    global ACTIVE_REQUEST
    with LOCK:
        existing = read_job(request_id)
        if existing:
            return existing, 200
        if ACTIVE_REQUEST:
            return {'error': '另一個拍攝作業仍在進行。'}, 409
        state = write_job(request_id, {'status': 'capturing'})
        ACTIVE_REQUEST = request_id
        threading.Thread(target=capture_worker, args=(request_id,), daemon=True).start()
        return state, 202


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, value, code=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            self.get()
        except HTTPError as error:
            self.reply({'error': '硬體服務未就緒或拒絕請求。'}, error.code if 400 <= error.code < 600 else 502)
        except (URLError, TimeoutError, OSError, ValueError):
            try:
                self.reply({'error': '無法連線至鏡頭服務，請檢查 mediguard-hardware。'}, 502)
            except OSError:
                pass

    def get(self):
        path = urlsplit(self.path).path
        if path == '/api/status':
            return self.reply({'ok': True, 'mode': 'prescription-verification'})
        if path == '/api/device/status':
            return self.reply(upstream_json('/status'))
        match = re.fullmatch('/api/device/requests/(' + UUID + ')', path)
        if match:
            state = read_job(match[1])
            return self.reply(state or {'error': '找不到拍攝作業。'}, 200 if state else 404)
        match = re.fullmatch('/api/device/captures/(' + UUID + ')/verification', path)
        if match:
            return self.reply(upstream_json('/captures/' + match[1] + '/verification'))
        match = re.fullmatch('/api/device/captures/(' + UUID + ')/camera/([12])', path)
        if match:
            return self.proxy_media('/captures/' + match[1] + '/camera/' + match[2], 'image/jpeg')
        if path == '/api/device/preview/stream':
            if parse_qs(urlsplit(self.path).query).get('camera', ['1']) != ['1']:
                return self.reply({'error': 'invalid_camera_id'}, 400)
            return self.proxy_media('/preview/stream?camera=1', 'multipart/x-mixed-replace; boundary=frame')
        files = {'/': 'index.html', '/app.js': 'app.js', '/workflow.js': 'workflow.js',
                 '/styles.css': 'styles.css', '/vendor/zxing-browser.min.js': 'vendor/zxing-browser.min.js',
                 '/vendor/LICENSE-ZXing-browser.txt': 'vendor/LICENSE-ZXing-browser.txt',
                 '/vendor/LICENSE-ZXing-library.txt': 'vendor/LICENSE-ZXing-library.txt'}
        if path not in files:
            return self.reply({'error': 'not_found'}, 404)
        name = files[path]
        body = (ROOT / 'static' / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', {'html': 'text/html; charset=utf-8', 'js': 'text/javascript; charset=utf-8',
                                        'css': 'text/css; charset=utf-8', 'txt': 'text/plain; charset=utf-8'}[name.split('.')[-1]])
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def proxy_media(self, path, content_type):
        with upstream(path) as response:
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            try:
                while True:
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (OSError, TimeoutError):
                return

    def do_POST(self):
        try:
            origin = self.headers.get('Origin')
            if origin and origin not in ('http://' + self.headers.get('Host', ''), 'https://' + self.headers.get('Host', '')):
                return self.reply({'error': 'origin_rejected'}, 403)
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.reply({'error': 'JSON required'}, 415)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                return self.reply({'error': 'body_size'}, 413)
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('invalid JSON')
            if self.path == '/api/device/preview/start':
                with LOCK:
                    if ACTIVE_REQUEST:
                        return self.reply({'error': '拍攝中，請稍候。'}, 409)
                    return self.reply(upstream_json('/preview/start', {'lightMode': 'white', 'brightness': 85}))
            if self.path == '/api/device/preview/stop':
                with LOCK:
                    if ACTIVE_REQUEST:
                        return self.reply({'error': '拍攝中，暫時不能停止鏡頭。'}, 409)
                    return self.reply(upstream_json('/preview/stop', {}))
            if self.path == '/api/device/capture':
                request_id = payload.get('requestId', '')
                if not isinstance(request_id, str) or not re.fullmatch(UUID, request_id):
                    raise ValueError('request ID required')
                state, code = start_capture(request_id)
                return self.reply(state, code)
            self.reply({'error': 'not_found'}, 404)
        except HTTPError:
            self.reply({'error': '硬體服務拒絕操作，請檢查設定與鏡頭。'}, 502)
        except (URLError, TimeoutError, OSError):
            self.reply({'error': '硬體服務無法連線，請檢查 mediguard-hardware。'}, 502)
        except (ValueError, TypeError):
            self.reply({'error': '資料格式錯誤。'}, 400)


if __name__ == '__main__':
    os.umask(0o077)
    initialize()
    host, port = os.environ.get('POS_HOST', '127.0.0.1'), int(os.environ.get('POS_PORT', '8088'))
    print(f'MediGuard verification kiosk: http://{host}:{port}', flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
