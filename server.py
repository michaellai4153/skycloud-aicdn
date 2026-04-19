#!/usr/bin/env python3
import http.server
import json
import os
import datetime
from urllib.parse import urlparse

DATA_FILE = os.path.join(os.path.dirname(__file__), 'leads.json')

def load_leads():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_leads(leads):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if urlparse(self.path).path == '/api/leads':
            leads = load_leads()
            for i, lead in enumerate(leads):
                lead['rowIndex'] = i + 2
            self._json(200, {'success': True, 'data': leads})
        else:
            super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path == '/api/leads':
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
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
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
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
