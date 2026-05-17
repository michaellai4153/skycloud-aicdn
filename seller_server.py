#!/usr/bin/env python3
import http.server
from socketserver import ThreadingMixIn
import json
import os
import datetime
import secrets
from urllib.parse import urlparse, parse_qs

import db
import ecpay
import oauth

BASE_DIR  = os.path.dirname(__file__)
CFG_FILE  = os.path.join(BASE_DIR, 'seller_config.json')

_tokens: set[str] = set()

def load_config():
    if os.path.exists(CFG_FILE):
        with open(CFG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'password': 'seller2026'}


def ecpay_config():
    cfg = load_config().get('ecpay') or {}
    return {**ecpay.DEFAULT_SANDBOX, **cfg}


def public_base_url():
    return load_config().get('base_url', 'https://www.aicdn.ai')

class Handler(http.server.SimpleHTTPRequestHandler):

    def _auth(self):
        # Prefer Google OAuth session cookie (issued by buyer server, shared DB)
        sid = oauth.parse_session_cookie(self.headers.get('Cookie', ''))
        if sid and db.get_session(sid):
            return True
        # Legacy: Bearer token from password login
        header = self.headers.get('Authorization', '')
        if header.startswith('Bearer '):
            return header[7:] in _tokens
        return False

    def do_GET(self):
        p = urlparse(self.path).path
        blocked = ('/seller_config.json', '/seller_leads.json', '/seller_server.py',
                   '/config.json', '/leads.json', '/server.py',
                   '/db.py', '/migrate.py', '/ecpay.py', '/oauth.py',
                   '/knowledge_base.py', '/openai_client.py',
                   '/qa_render.py', '/gen_questions.py',
                   '/aicdn.db', '/README.md')
        if (p in blocked
                or p.startswith('/.git') or p.startswith('/.claude')
                or p.startswith('/__pycache__') or p.endswith('.pyc')):
            return self._json(403, {'error': 'Forbidden'})
        # On the seller subdomain, "/" should serve the seller landing page.
        if p == '/':
            self.path = '/seller_index.html'
        if p == '/api/seller-leads':
            if not self._auth():
                return self._json(401, {'success': False, 'error': 'Unauthorized'})
            self._json(200, {'success': True, 'data': db.list_seller_leads()})
        elif p == '/api/me':
            email = self._session_email()
            self._json(200, {'authenticated': bool(email), 'email': email or None})
        elif p.startswith('/pay/'):
            self._handle_payment_redirect(p[len('/pay/'):])
        elif p == '/api/ecpay-result':
            self._html(200, ecpay.render_result_page(True, '付款已完成'))
        elif p == '/sitemap.xml':
            self._handle_sitemap()
        elif p == '/robots.txt':
            self._handle_robots()
        else:
            super().do_GET()

    def _public_base(self):
        return load_config().get('base_url', 'https://referral.aicdn.ai').rstrip('/')

    def _handle_sitemap(self):
        base = self._public_base()
        urls = [
            f'{base}/',
            f'{base}/privacy.html',
            f'{base}/terms.html',
            f'{base}/refund.html',
        ]
        body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                + ''.join(f'  <url><loc>{u}</loc></url>\n' for u in urls)
                + '</urlset>\n')
        self.send_response(200)
        self.send_header('Content-Type', 'application/xml; charset=utf-8')
        self.end_headers()
        self.wfile.write(body.encode('utf-8'))

    def _handle_robots(self):
        base = self._public_base()
        body = (
            'User-agent: *\n'
            'Allow: /\n'
            'Disallow: /seller_crm.html\n'
            'Disallow: /api/\n'
            'Disallow: /pay/\n'
            f'\nSitemap: {base}/sitemap.xml\n'
        )
        self._text(200, body)

    def _session_email(self):
        sid = oauth.parse_session_cookie(self.headers.get('Cookie', ''))
        if sid:
            s = db.get_session(sid)
            if s:
                return s['email']
        return None

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ('/api/login', '/api/seller-leads', '/api/seller-leads/bulk',
                        '/api/create-payment', '/api/ecpay-return',
                        '/api/logout'):
            return self._json(403, {'error': 'Forbidden'})

        if path == '/api/logout':
            sid = oauth.parse_session_cookie(self.headers.get('Cookie', ''))
            if sid:
                db.delete_session(sid)
            cfg = load_config()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Set-Cookie',
                oauth.clear_cookie_header(domain=cfg.get('cookie_domain')))
            self.end_headers()
            self.wfile.write(b'{"success":true}')
            return

        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length) if length else b''
        if path == '/api/ecpay-return':
            return self._handle_ecpay_webhook(body)

        try:
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError):
            return self._json(400, {'error': 'Bad Request'})

        if path == '/api/create-payment':
            if not self._auth():
                return self._json(401, {'success': False, 'error': 'Unauthorized'})
            return self._handle_create_payment(data, table='seller_leads')

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
            data.setdefault('createdAt',
                datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            data.setdefault('stage', 0)
            data.setdefault('nextDate', '')
            data.setdefault('notes', [])
            db.add_seller_lead(data)
            self._json(200, {'success': True})

        elif path == '/api/seller-leads/bulk':
            if not self._auth():
                return self._json(401, {'success': False, 'error': 'Unauthorized'})
            if data.get('action') == 'bulkSave':
                db.bulk_save_seller_leads(data.get('data', []))
                self._json(200, {'success': True})
            else:
                self._json(400, {'success': False, 'error': 'Unknown action'})

    # ─── ECPAY ────────────────────────────────────────────────────────────
    def _handle_create_payment(self, data, *, table):
        lead_id = data.get('lead_id')
        plan    = data.get('plan')
        amount  = data.get('amount')
        if not lead_id or not plan:
            return self._json(400, {'success': False, 'error': 'Missing lead_id or plan'})
        if plan not in ecpay.PLANS:
            return self._json(400, {'success': False, 'error': 'Unknown plan'})
        plan_name, plan_amount = ecpay.PLANS[plan]
        amount = int(amount) if amount else plan_amount
        if amount <= 0:
            return self._json(400, {'success': False, 'error': '金額必須大於 0'})

        cfg      = ecpay_config()
        order_id = ecpay.new_order_id()
        link     = f'{public_base_url()}/pay/{order_id}'

        db.set_payment(table, lead_id,
                       plan=plan, amount=amount,
                       ecpay_order_id=order_id, payment_link=link,
                       payment_status='link_sent')

        self._json(200, {
            'success': True, 'order_id': order_id, 'amount': amount,
            'plan': plan, 'plan_name': plan_name, 'link': link,
        })

    def _handle_payment_redirect(self, order_id):
        table, row = db.find_lead_by_order_id(order_id)
        if not row:
            return self._html(404, ecpay.render_result_page(False, '找不到此訂單'))
        if row.get('payment_status') == 'paid':
            return self._html(200, ecpay.render_result_page(True, '此訂單已完成付款'))
        cfg = ecpay_config()
        plan_name = ecpay.PLANS.get(row.get('plan', ''), ('AICDN 服務', 0))[0]
        params = ecpay.build_checkout_params(cfg,
            order_id=order_id,
            amount=row.get('amount') or 0,
            item_name=plan_name,
            trade_desc='AICDN 服務訂單',
            return_url=f'{public_base_url()}/api/ecpay-return',
            client_back_url=f'{public_base_url()}/api/ecpay-result',
        )
        self._html(200, ecpay.render_redirect_html(
            ecpay.get_endpoint(cfg), params))

    def _handle_ecpay_webhook(self, body):
        try:
            form = {k: v[0] for k, v in parse_qs(body.decode('utf-8')).items()}
        except Exception:
            return self._text(400, '0|BadRequest')
        cfg = ecpay_config()
        if not ecpay.verify_callback(form, cfg['hash_key'], cfg['hash_iv']):
            return self._text(400, '0|BadCheckMac')
        order_id   = form.get('MerchantTradeNo', '')
        rtn_code   = form.get('RtnCode', '0')
        table, row = db.find_lead_by_order_id(order_id)
        if not row:
            return self._text(400, '0|OrderNotFound')
        if rtn_code == '1':
            db.set_payment(table, row['id'], payment_status='paid',
                           paid_at=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        else:
            db.set_payment(table, row['id'], payment_status='failed')
        return self._text(200, '1|OK')

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

    def _html(self, code, html):
        body = html.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(body)

    def _text(self, code, text):
        body = text.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
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
