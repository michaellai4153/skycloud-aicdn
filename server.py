#!/usr/bin/env python3
import http.server
import json
import os
import datetime
import secrets
from urllib.parse import urlparse

BASE_DIR  = os.path.dirname(__file__)
DATA_FILE = os.path.join(BASE_DIR, 'leads.json')
CFG_FILE  = os.path.join(BASE_DIR, 'config.json')

# in-memory valid tokens
_tokens: set[str] = set()

def load_config():
    if os.path.exists(CFG_FILE):
        with open(CFG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'username': 'admin', 'password': 'skycloud2026'}

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
        blocked = ('/config.json', '/leads.json', '/server.py')
        if p in blocked or p.startswith('/.git') or p.startswith('/.claude'):
            return self._json(403, {'error': 'Forbidden'})
        if p == '/api/leads':
            if not self._auth():
                return self._json(401, {'success': False, 'error': 'Unauthorized'})
            leads = load_leads()
            for i, lead in enumerate(leads):
                lead['rowIndex'] = i + 2
            self._json(200, {'success': True, 'data': leads})
        else:
            super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get('Content-Length', 0))
        data = json.loads(self.rfile.read(length)) if length else {}

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
            leads = load_leads()
            action = data.get('action', 'addRow')

            if action == 'addRow':
                leads.append({
                    'name':      data.get('name', ''),
                    'title':     data.get('title', ''),
                    'company':   data.get('company', ''),
                    'email':     data.get('email', ''),
                    'domain':    data.get('domain', ''),
                    'status':    data.get('status', '待處理'),
                    'start':     data.get('start', ''),
                    'end':       data.get('end', ''),
                    'ip':        data.get('ip', ''),
                    'note':      data.get('note', ''),
                    'createdAt': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                })
                save_leads(leads)
                self._json(200, {'success': True})

            elif action == 'updateRow':
                idx = (data.get('rowIndex') or 2) - 2
                if 0 <= idx < len(leads):
                    for f in ['status','name','title','company','email','domain','start','end','ip','note']:
                        if f in data:
                            leads[idx][f] = data[f]
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

if __name__ == '__main__':
    server = http.server.HTTPServer(('', 8765), Handler)
    print('Server running on http://localhost:8765')
    server.serve_forever()
