import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class TerminalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = (server.DB, server.REMOTE, server.TOKEN)
        server.DB = Path(self.temp.name) / 'test.sqlite3'
        server.TOKEN = 'test-secret-only'
        server.initialize()
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.http.server_port)
        self.payload = {'id':'6ce92c83-cc62-4dd8-a231-aa58a8e6c274','device':'pi-test','created_at':'2026-11-17T00:00:00+00:00','mode':'自取','items':[{'id':'demo-01','name':'REXULTI 1mg','quantity':2}]}

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        server.DB, server.REMOTE, server.TOKEN = self.previous
        self.temp.cleanup()

    def post(self, route, payload, token=None, origin=None):
        headers = {'Content-Type':'application/json'}
        if token: headers['Authorization'] = 'Bearer ' + token
        if origin: headers['Origin'] = origin
        with urlopen(Request(self.base + route, json.dumps(payload).encode(), headers), timeout=3) as response:
            return json.load(response)

    def test_retries_do_not_duplicate_and_conflicts_rejected(self):
        for _ in range(2): self.post('/api/records', self.payload)
        with server.database() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM records').fetchone()[0], 1)
        changed = copy.deepcopy(self.payload)
        changed['items'][0]['quantity'] = 3
        with self.assertRaises(HTTPError) as error: self.post('/api/records', changed)
        self.assertEqual(error.exception.code, 400)

    def test_receiver_auth_and_no_resend(self):
        with self.assertRaises(HTTPError) as error: self.post('/api/receive', self.payload)
        self.assertEqual(error.exception.code, 401)
        for _ in range(2): self.post('/api/receive', self.payload, server.TOKEN)
        with server.database() as con:
            row = con.execute('SELECT * FROM records').fetchone()
            self.assertEqual((row['synced'], row['received']), (1, 1))

    def test_bad_quantity_and_cross_site_rejected(self):
        self.payload['items'][0]['quantity'] = True
        with self.assertRaises(HTTPError) as error: self.post('/api/records', self.payload)
        self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error: self.post('/api/sync', {}, origin='https://evil.invalid')
        self.assertEqual(error.exception.code, 403)

    def test_offline_persistence_then_ack(self):
        server.save(self.payload)
        server.REMOTE = 'http://127.0.0.1:1/api/receive'
        server.sync_once()
        with server.database() as con:
            self.assertEqual(con.execute('SELECT synced FROM records').fetchone()[0], 0)
        # A fake remote returning the correct acknowledgment.
        class Receiver(server.BaseHTTPRequestHandler):
            def do_POST(inner):
                payload = json.loads(inner.rfile.read(int(inner.headers['Content-Length'])))
                inner.send_response(200)
                inner.end_headers()
                inner.wfile.write(json.dumps({'ok':True,'id':payload['id']}).encode())
            def log_message(*args): pass
        remote = server.ThreadingHTTPServer(('127.0.0.1',0), Receiver)
        thread = threading.Thread(target=remote.serve_forever,daemon=True)
        thread.start()
        try:
            server.REMOTE = f'http://127.0.0.1:{remote.server_port}/api/receive'
            server.sync_once()
            with server.database() as con:
                self.assertEqual(con.execute('SELECT synced FROM records').fetchone()[0], 1)
        finally:
            remote.shutdown(); remote.server_close(); thread.join()

    def test_static_assets_and_secrets_not_exposed(self):
        for path in ('/', '/app.js', '/styles.css', '/api/catalog', '/api/status'):
            with urlopen(self.base + path) as response: self.assertEqual(response.status, 200)
        with self.assertRaises(HTTPError) as error: urlopen(self.base + '/.env')
        self.assertEqual(error.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
