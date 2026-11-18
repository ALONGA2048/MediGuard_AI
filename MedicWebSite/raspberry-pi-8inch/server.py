"""Offline-first touch terminal. Python 3.11+, standard library only."""
import hmac
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
# Deliberately not a shell parser: values are literal, one NAME=value per line.
for line in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines() if (ROOT / '.env').exists() else []:
    if line.strip() and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())
DB = Path(os.environ.get('POS_DB', str(ROOT / 'data' / 'pos.sqlite3')))
REMOTE = os.environ.get('POS_SYNC_URL', '')
TOKEN = os.environ.get('POS_SYNC_TOKEN', '')
DEVICE = os.environ.get('POS_DEVICE_ID', 'mediguard-pi-01')
SYNC_LOCK = threading.Lock()
LAST_SYNC = {'message': '尚未同步', 'at': None}
CATALOG = json.loads((ROOT / 'catalog.json').read_text(encoding='utf-8'))


@contextmanager
def database():
    con = sqlite3.connect(DB, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with database() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, payload TEXT NOT NULL, synced INTEGER NOT NULL DEFAULT 0, received INTEGER NOT NULL DEFAULT 0)')


def validate(payload):
    if not isinstance(payload, dict):
        raise ValueError('資料格式錯誤')
    uuid.UUID(payload.get('id', ''))
    if not isinstance(payload.get('device'), str) or not 1 <= len(payload['device']) <= 100:
        raise ValueError('裝置代號錯誤')
    datetime.fromisoformat(payload.get('created_at', ''))
    if payload.get('mode') not in ('自取', '交接'):
        raise ValueError('交付方式錯誤')
    items = payload.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError('請選擇品項')
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not isinstance(item.get('name'), str):
            raise ValueError('品項格式錯誤')
        if type(item.get('quantity')) is not int or not 1 <= item['quantity'] <= 99:
            raise ValueError('數量須為 1–99')


def save(payload, received=False):
    validate(payload)
    with database() as con:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        con.execute('INSERT OR IGNORE INTO records VALUES (?, ?, ?, ?)',
                    (payload['id'], canonical, int(received), int(received)))
        # Acquire the write transaction before comparing, including concurrent retries.
        existing = con.execute('SELECT payload FROM records WHERE id=?', (payload['id'],)).fetchone()
        if existing['payload'] != canonical:
            raise ValueError('相同紀錄 ID 的內容不一致')
    return payload['id']


def sync_once():
    if not SYNC_LOCK.acquire(blocking=False):
        return
    try:
        if not REMOTE or not TOKEN:
            LAST_SYNC.update(message='本機模式：尚未設定同步網址／Token', at=None)
            return
        with database() as con:
            rows = con.execute('SELECT id, payload FROM records WHERE synced=0 AND received=0 ORDER BY rowid LIMIT 20').fetchall()
        if not rows:
            LAST_SYNC.update(message='目前沒有待傳資料（未探測遠端連線）', at=LAST_SYNC['at'])
            return
        for row in rows:
            request = Request(REMOTE, row['payload'].encode(), {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOKEN})
            with urlopen(request, timeout=10) as response:
                ack = json.loads(response.read(65536))
            if ack.get('id') != row['id'] or ack.get('ok') is not True:
                raise ValueError('遠端未確認紀錄 ID')
            with database() as con:
                con.execute('UPDATE records SET synced=1 WHERE id=?', (row['id'],))
        LAST_SYNC.update(message='遠端已連線，待傳紀錄會持續送出', at=datetime.now(timezone.utc).isoformat())
    except Exception:
        LAST_SYNC.update(message='同步未完成：請檢查熱點、Tailscale、接收端與 Token；稍後自動重試', at=None)
    finally:
        SYNC_LOCK.release()


def sync_loop():
    while True:
        sync_once()
        time.sleep(30)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Do not log credentials or request bodies.
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
        path = self.path.split('?')[0]
        if path == '/api/status':
            with database() as con:
                pending = con.execute('SELECT count(*) FROM records WHERE synced=0 AND received=0').fetchone()[0]
            return self.reply({'device': DEVICE, 'pending': pending, 'configured': bool(REMOTE and TOKEN), 'sync': LAST_SYNC})
        if path == '/api/catalog':
            return self.reply(CATALOG)
        if path == '/api/records':
            with database() as con:
                rows = con.execute('SELECT * FROM records ORDER BY rowid DESC LIMIT 100').fetchall()
            return self.reply([dict(json.loads(r['payload']), synced=bool(r['synced']), received=bool(r['received'])) for r in rows])
        files = {'/': 'index.html', '/app.js': 'app.js', '/styles.css': 'styles.css'}
        if path not in files:
            return self.reply({'error': 'not_found'}, 404)
        name = files[path]
        body = (ROOT / 'static' / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', {'html': 'text/html; charset=utf-8', 'js': 'text/javascript; charset=utf-8', 'css': 'text/css; charset=utf-8'}[name.split('.')[-1]])
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            if self.path == '/api/receive':
                if not TOKEN or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + TOKEN):
                    return self.reply({'error': 'unauthorized'}, 401)
            elif self.path not in ('/api/records', '/api/sync'):
                return self.reply({'error': 'not_found'}, 404)
            else:
                # Browser writes require same-origin JSON; reject cross-site form submissions.
                origin = self.headers.get('Origin')
                if origin and origin != 'http://' + self.headers.get('Host', '') and origin != 'https://' + self.headers.get('Host', ''):
                    return self.reply({'error': 'origin_rejected'}, 403)
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.reply({'error': 'JSON required'}, 415)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                return self.reply({'error': 'body_size'}, 413)
            payload = json.loads(self.rfile.read(length))
            if self.path == '/api/sync':
                threading.Thread(target=sync_once, daemon=True).start()
                return self.reply({'ok': True})
            if self.path == '/api/records':
                catalog = {item['id']: item for item in CATALOG}
                for item in payload.get('items', []):
                    if item['id'] not in catalog:
                        raise ValueError('未知品項')
                    item['name'] = catalog[item['id']]['name']
                payload['device'] = DEVICE
            record_id = save(payload, received=self.path == '/api/receive')
            self.reply({'ok': True, 'id': record_id})
        except (ValueError, TypeError, KeyError, AttributeError):
            self.reply({'error': '資料格式錯誤或相同 ID 的內容不一致'}, 400)
        except sqlite3.Error:
            self.reply({'error': '資料庫寫入失敗，請保留清單並檢查磁碟'}, 503)


if __name__ == '__main__':
    initialize()
    threading.Thread(target=sync_loop, daemon=True).start()
    host = os.environ.get('POS_HOST', '127.0.0.1')
    port = int(os.environ.get('POS_PORT', '8088'))
    print(f'MediGuard 8-inch terminal: http://{host}:{port}', flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
