#!/usr/bin/env python3
import http.server
from socketserver import ThreadingMixIn
import json
import os
import datetime
import secrets
from urllib.parse import urlparse

import db

BASE_DIR  = os.path.dirname(__file__)
CFG_FILE  = os.path.join(BASE_DIR, 'config.json')

# in-memory valid tokens
_tokens: set[str] = set()

def load_config():
    if os.path.exists(CFG_FILE):
        with open(CFG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'username': 'admin', 'password': 'skycloud2026'}

class Handler(http.server.SimpleHTTPRequestHandler):

    def _auth(self):
        header = self.headers.get('Authorization', '')
        if header.startswith('Bearer '):
            return header[7:] in _tokens
        return False

    def do_GET(self):
        p = urlparse(self.path).path
        blocked = ('/config.json', '/leads.json', '/seller_leads.json',
                   '/seller_config.json', '/server.py', '/seller_server.py',
                   '/db.py', '/migrate.py', '/aicdn.db')
        if p in blocked or p.startswith('/.git') or p.startswith('/.claude'):
            return self._json(403, {'error': 'Forbidden'})
        if p == '/api/leads':
            if not self._auth():
                return self._json(401, {'success': False, 'error': 'Unauthorized'})
            self._json(200, {'success': True, 'data': db.list_buyer_leads()})
        else:
            super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        # Whitelist: only allow POST to known API endpoints
        if path not in ('/api/login', '/api/leads', '/api/chat'):
            return self._json(403, {'error': 'Forbidden'})

        length = int(self.headers.get('Content-Length', 0))
        try:
            data = json.loads(self.rfile.read(length)) if length else {}
        except (json.JSONDecodeError, ValueError):
            return self._json(400, {'error': 'Bad Request'})

        if path == '/api/login':
            cfg = load_config()
            if data.get('password') == cfg.get('password'):
                token = secrets.token_hex(32)
                _tokens.add(token)
                self._json(200, {'success': True, 'token': token})
            else:
                self._json(401, {'success': False, 'error': '密碼錯誤'})

        elif path == '/api/leads':
            if not self._auth():
                return self._json(401, {'success': False, 'error': 'Unauthorized'})
            action = data.get('action', 'addRow')

            if action == 'addRow':
                data.setdefault('createdAt',
                    datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                db.add_buyer_lead(data)
                self._json(200, {'success': True})

            elif action == 'updateRow':
                lead_id = data.get('rowIndex')
                if lead_id:
                    db.update_buyer_lead(lead_id, data)
                self._json(200, {'success': True})

            else:
                self._json(400, {'success': False, 'error': 'Unknown action'})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}]", fmt % args)

class ThreadingHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

if __name__ == '__main__':
    server = ThreadingHTTPServer(('', 8765), Handler)
    print('Server running on http://localhost:8765')
    server.serve_forever()
