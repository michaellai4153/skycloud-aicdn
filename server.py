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
import knowledge_base
import mail
import oauth
import openai_client
import qa_render
import random

BASE_DIR  = os.path.dirname(__file__)
CFG_FILE  = os.path.join(BASE_DIR, 'config.json')

# Admin portal (/admin.html) access is restricted to this explicit list,
# on top of the @skycloud.com.tw domain (hd) check. Override via
# config.json 'allowed_admin_emails'.
ADMIN_EMAILS_DEFAULT = [
    'eason@skycloud.com.tw',
    'lucy@skycloud.com.tw',
    'fred@skycloud.com.tw',
    'cliff@skycloud.com.tw',
]

# in-memory valid tokens
_tokens: set[str] = set()

def load_config():
    if os.path.exists(CFG_FILE):
        with open(CFG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'username': 'admin', 'password': 'skycloud2026'}


def ecpay_config():
    """Return ECPay config from config.json, falling back to public sandbox."""
    cfg = load_config().get('ecpay') or {}
    return {**ecpay.DEFAULT_SANDBOX, **cfg}


def public_base_url():
    """Base URL used in ECPay return/back URLs. Override via config.json 'base_url'."""
    return load_config().get('base_url', 'https://www.aicdn.ai')

class Handler(http.server.SimpleHTTPRequestHandler):

    def _auth(self):
        # Prefer Google OAuth session cookie
        sid = oauth.parse_session_cookie(self.headers.get('Cookie', ''))
        if sid and db.get_session(sid):
            return True
        # Legacy: Bearer token from password login
        header = self.headers.get('Authorization', '')
        if header.startswith('Bearer '):
            return header[7:] in _tokens
        return False

    def _session_email(self):
        sid = oauth.parse_session_cookie(self.headers.get('Cookie', ''))
        if sid:
            s = db.get_session(sid)
            if s:
                return s['email']
        return None

    def do_GET(self):
        p = urlparse(self.path).path
        blocked = ('/config.json', '/leads.json', '/seller_leads.json',
                   '/seller_config.json', '/server.py', '/seller_server.py',
                   '/db.py', '/migrate.py', '/ecpay.py', '/oauth.py',
                   '/knowledge_base.py', '/openai_client.py',
                   '/qa_render.py', '/gen_questions.py',
                   '/aicdn.db', '/README.md', '/CLAUDE.md',
                   '/config.example.json', '/seller_config.example.json')
        if (p in blocked
                or p.startswith('/.git') or p.startswith('/.claude')
                or p.startswith('/__pycache__') or p.endswith('.pyc')):
            return self._json(403, {'error': 'Forbidden'})
        if p == '/api/leads':
            if not self._auth():
                return self._json(401, {'success': False, 'error': 'Unauthorized'})
            self._json(200, {'success': True, 'data': db.list_buyer_leads()})
        elif p.startswith('/pay/'):
            order_id = p[len('/pay/'):]
            self._handle_payment_redirect(order_id)
        elif p == '/api/ecpay-result':
            self._html(200, ecpay.render_result_page(
                True, '付款已完成'))
        elif p == '/api/qa':
            self._handle_list_questions()
        elif p.startswith('/qa/'):
            self._handle_qa_page(p[len('/qa/'):])
        elif p == '/sitemap.xml':
            self._handle_sitemap()
        elif p == '/robots.txt':
            self._handle_robots()
        elif p == '/api/oauth/login':
            self._handle_oauth_login()
        elif p == '/api/oauth/callback':
            self._handle_oauth_callback()
        elif p == '/api/me':
            self._handle_me()
        elif p in ('/blog', '/faq', '/cname', '/pricing', '/article-1', '/article-2'):
            # SPA clean URLs — serve index.html and let JS handle routing
            with open(os.path.join(BASE_DIR, 'index.html'), 'r', encoding='utf-8') as f:
                self._html(200, f.read())
        else:
            super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        # Whitelist: only allow POST to known API endpoints
        if path not in ('/api/login', '/api/leads', '/api/chat',
                        '/api/create-payment', '/api/ecpay-return',
                        '/api/logout'):
            return self._json(403, {'error': 'Forbidden'})

        # ECPay webhook posts form-encoded data; everything else is JSON.
        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length) if length else b''
        if path == '/api/ecpay-return':
            return self._handle_ecpay_webhook(body)

        try:
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError):
            return self._json(400, {'error': 'Bad Request'})

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

        if path == '/api/create-payment':
            if not self._auth():
                return self._json(401, {'success': False, 'error': 'Unauthorized'})
            return self._handle_create_payment(data, table='buyer_leads')

        if path == '/api/login':
            cfg = load_config()
            if data.get('password') == cfg.get('password'):
                token = secrets.token_hex(32)
                _tokens.add(token)
                self._json(200, {'success': True, 'token': token})
            else:
                self._json(401, {'success': False, 'error': '密碼錯誤'})

        elif path == '/api/leads':
            action = data.get('action', 'addRow')

            if action == 'addRow':
                # Public: anyone can submit an application
                data.setdefault('createdAt',
                    datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                db.add_buyer_lead(data)
                mail.notify_new_lead(load_config(), data)
                self._json(200, {'success': True})

            elif action == 'updateRow':
                if not self._auth():
                    return self._json(401, {'success': False, 'error': 'Unauthorized'})
                lead_id = data.get('rowIndex')
                if lead_id:
                    db.update_buyer_lead(lead_id, data)
                self._json(200, {'success': True})

            elif action == 'deleteRow':
                if not self._auth():
                    return self._json(401, {'success': False, 'error': 'Unauthorized'})
                lead_id = data.get('rowIndex')
                if lead_id:
                    db.delete_buyer_lead(lead_id)
                self._json(200, {'success': True})

            else:
                self._json(400, {'success': False, 'error': 'Unknown action'})

    # ─── ECPAY ────────────────────────────────────────────────────────────
    def _handle_create_payment(self, data, *, table):
        """Admin generates a payment link for a lead."""
        lead_id = data.get('lead_id')
        plan    = data.get('plan')
        amount  = data.get('amount')
        if not lead_id or not plan:
            return self._json(400, {'success': False, 'error': 'Missing lead_id or plan'})
        if plan not in ecpay.PLANS:
            return self._json(400, {'success': False, 'error': 'Unknown plan'})

        # Resolve amount: explicit > plan default; custom requires explicit.
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
            'success': True,
            'order_id': order_id,
            'amount':   amount,
            'plan':     plan,
            'plan_name': plan_name,
            'link':     link,
        })

    def _handle_payment_redirect(self, order_id):
        """Browser hits /pay/<order_id> → render auto-submitting form to ECPay."""
        table, row = db.find_lead_by_order_id(order_id)
        if not row:
            return self._html(404, ecpay.render_result_page(
                False, '找不到此訂單'))
        if row.get('payment_status') == 'paid':
            return self._html(200, ecpay.render_result_page(
                True, '此訂單已完成付款'))

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
        """ECPay server posts form-encoded result. Verify signature, update DB."""
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
            db.set_payment(table, row['id'],
                           payment_status='paid',
                           paid_at=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        else:
            db.set_payment(table, row['id'], payment_status='failed')

        return self._text(200, '1|OK')

    # ─── AI QA ────────────────────────────────────────────────────────────
    def _handle_list_questions(self):
        """JSON list of FAQ questions (used by index.html to render cards)."""
        qs = db.list_qa_questions()
        # Frontend picks 5 random; we expose all 10 + a shuffled-5 helper.
        sample = random.sample(qs, min(5, len(qs))) if qs else []
        self._json(200, {
            'success': True,
            'all': qs,
            'sample': [{'slug': q['slug'], 'question': q['question']} for q in sample],
        })

    def _handle_qa_page(self, slug):
        """Server-rendered Q&A page. Cached answers served instantly; cache miss
        triggers a single OpenAI call (then cached)."""
        q = db.get_qa_question(slug)
        if not q:
            return self._html(404, qa_render.render_not_found())

        cached = db.get_qa_answer(slug)
        if cached:
            answer_text = cached['answer']
        else:
            try:
                answer_text = openai_client.chat([
                    {'role': 'system', 'content': knowledge_base.system_prompt()},
                    {'role': 'user',   'content': q['question']},
                ], model='gpt-4o-mini', temperature=0.4, max_tokens=600)
                db.set_qa_answer(slug, answer_text)
            except Exception as e:
                print(f'[QA] OpenAI error for {slug}: {e}')
                answer_text = ('抱歉，目前無法即時產生回答。'
                               '請填寫網站表單，我們會在 24 小時內聯繫您。')

        # Sample 4 related questions (excluding current)
        all_qs = db.list_qa_questions()
        related = [r for r in all_qs if r['slug'] != slug]
        related = random.sample(related, min(4, len(related)))

        html = qa_render.render_qa_page(
            question=q['question'],
            answer_html=qa_render.md_to_html(answer_text),
            slug=slug,
            related=related,
            meta_description=answer_text[:140].replace('\n', ' '),
        )
        self._html(200, html)

    # ─── SEO ──────────────────────────────────────────────────────────────
    def _handle_sitemap(self):
        base = public_base_url().rstrip('/')
        # www.aicdn.ai sitemap. Seller landing lives on referral.aicdn.ai now
        # and has its own sitemap there.
        urls = [
            f'{base}/',
            f'{base}/privacy.html',
            f'{base}/terms.html',
            f'{base}/refund.html',
        ]
        for q in db.list_qa_questions():
            urls.append(f'{base}/qa/{q["slug"]}')
        body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                + ''.join(f'  <url><loc>{u}</loc></url>\n' for u in urls)
                + '</urlset>\n')
        self.send_response(200)
        self.send_header('Content-Type', 'application/xml; charset=utf-8')
        self.end_headers()
        self.wfile.write(body.encode('utf-8'))

    # ─── GOOGLE OAUTH ─────────────────────────────────────────────────────
    def _handle_oauth_login(self):
        cfg = load_config()
        cid = cfg.get('google_client_id')
        if not cid:
            return self._html(500, '<h1>OAuth not configured</h1>')
        qs = parse_qs(urlparse(self.path).query)
        return_to = qs.get('return', ['/admin.html'])[0]
        # Validate to prevent open redirect; accept paths or *.aicdn.ai URLs.
        if not oauth.is_safe_return_url(
                return_to, allowed_root=cfg.get('cookie_root', 'aicdn.ai')):
            return_to = '/admin.html'
        url, _ = oauth.authorize_url(
            client_id=cid,
            redirect_uri=f'{public_base_url()}/api/oauth/callback',
            return_to=return_to,
            hd_hint=cfg.get('allowed_domain', 'skycloud.com.tw'),
        )
        self.send_response(302)
        self.send_header('Location', url)
        self.end_headers()

    def _handle_oauth_callback(self):
        cfg = load_config()
        qs = parse_qs(urlparse(self.path).query)
        code  = qs.get('code', [''])[0]
        state = qs.get('state', [''])[0]
        if qs.get('error'):
            return self._html(400, f'<h1>登入失敗：{qs["error"][0]}</h1>')

        return_to = oauth.consume_state(state)
        if not return_to:
            return self._html(400, '<h1>無效的登入請求（state 過期或不存在）</h1>')

        # OpenAI proxy is reused for Google API calls (both blocked by HK).
        proxy = cfg.get('openai_proxy') or None
        try:
            tokens = oauth.exchange_code(
                code,
                client_id     = cfg['google_client_id'],
                client_secret = cfg['google_client_secret'],
                redirect_uri  = f'{public_base_url()}/api/oauth/callback',
                proxy         = proxy,
            )
            user = oauth.fetch_userinfo(tokens['access_token'], proxy=proxy)
        except Exception as e:
            return self._html(500, f'<h1>Google 認證失敗</h1><p>{e}</p>')

        allowed = cfg.get('allowed_domain', 'skycloud.com.tw')
        if user.get('hd') != allowed:
            return self._html(403, oauth.render_denied(
                f'只允許 @{allowed} 的帳號（你登入的是 {user.get("email","未知")}）'))

        email = (user.get('email') or '').lower()
        allowed_emails = {e.lower() for e in cfg.get('allowed_admin_emails', ADMIN_EMAILS_DEFAULT)}
        if email not in allowed_emails:
            return self._html(403, oauth.render_denied(
                f'此帳號沒有管理後台權限（{user.get("email","未知")}）'))

        sid = secrets.token_urlsafe(32)
        db.create_session(sid, user['email'])
        self.send_response(302)
        self.send_header('Set-Cookie',
            oauth.session_cookie_header(sid, domain=cfg.get('cookie_domain')))
        self.send_header('Location', return_to)
        self.end_headers()

    def _handle_me(self):
        email = self._session_email()
        if email:
            self._json(200, {'authenticated': True, 'email': email})
        else:
            self._json(200, {'authenticated': False})

    # ─── SEO ──────────────────────────────────────────────────────────────
    def _handle_robots(self):
        base = public_base_url().rstrip('/')
        body = (
            'User-agent: facebookexternalhit\n'
            'Allow: /\n'
            '\n'
            'User-agent: *\n'
            'Allow: /\n'
            'Allow: /qa/\n'
            'Disallow: /admin.html\n'
            'Disallow: /seller_crm.html\n'
            'Disallow: /api/\n'
            'Disallow: /pay/\n'
            f'\nSitemap: {base}/sitemap.xml\n'
        )
        self._text(200, body)

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
    server = ThreadingHTTPServer(('', 8765), Handler)
    print('Server running on http://localhost:8765')
    server.serve_forever()
