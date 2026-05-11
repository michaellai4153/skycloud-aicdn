#!/usr/bin/env python3
import http.server
from socketserver import ThreadingMixIn
import json
import os
import datetime
import secrets
from urllib.parse import urlparse

BASE_DIR  = os.path.dirname(__file__)
DATA_FILE = os.path.join(BASE_DIR, 'seller_leads.json')
CFG_FILE  = os.path.join(BASE_DIR, 'seller_config.json')

_tokens: set[str] = set()

def load_config():
    if os.path.exists(CFG_FILE):
        with open(CFG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'password': 'seller2026'}

def load_leads():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_leads(leads):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)

class Handler(http.server.SimpleHTTPRequestHandler):

    def _auth(self):
        header = self.headers.get('Authorization', '')
        if header.startswith('Bearer '):
            return header[7:] in _tokens
        return False

    def do_GET(self):
        p = urlparse(self.path).path
        blocked = ('/seller_config.json', '/seller_leads.json', '/seller_server.py')
        if p in blocked or p.startswith('/.git') or p.startswith('/.claude'):
            return self._json(403, {'error': 'Forbidden'})
        if p == '/api/seller-leads':
            if not self._auth():
                return self._json(401, {'success': False, 'error': 'Unauthorized'})
            leads = load_leads()
            self._json(200, {'success': True, 'data': leads})
        else:
            super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ('/api/login', '/api/seller-leads', '/api/seller-leads/bulk'):
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

        elif path == '/api/seller-leads':
            # Public POST: submit application (no auth required)
            leads = load_leads()
            leads.append({
                'id':        len(leads) + 1,
                'name':      data.get('name', ''),
                'phone':     data.get('phone', ''),
                'email':     data.get('email', ''),
                'website':   data.get('website', ''),
                'type':      data.get('type', ''),
                'topic':     data.get('topic', ''),
                'traffic':   data.get('traffic', ''),
                'ads':       data.get('ads', ''),
                'note':      data.get('note', ''),
                'stage':     0,
                'nextDate':  '',
                'notes':     [],
                'createdAt': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            })
            save_leads(leads)
            self._json(200, {'success': True})

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
    server = ThreadingHTTPServer(('', 8766), Handler)
    print('Seller server running on http://localhost:8766')
    server.serve_forever()
