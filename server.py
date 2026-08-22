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
        elif p.startswith('/media/'):
            filename = p[len('/media/'):]
            self._serve_upload(filename)
        elif p == '/api/blog/posts':
            self._handle_blog_posts()
        elif p.startswith('/blog/'):
            slug = p[len('/blog/'):]
            self._handle_blog_article(slug)
        elif p in ('/', '/blog', '/faq', '/cname', '/pricing'):
            # SPA clean URLs — serve index.html, never cache so JS updates take effect
            with open(os.path.join(BASE_DIR, 'index.html'), 'r', encoding='utf-8') as f:
                body = f.read().encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        else:
            super().do_GET()

    def _serve_upload(self, filename):
        import mimetypes
        if not filename or '/' in filename or '..' in filename:
            self.send_error(404)
            return
        path = os.path.join(BASE_DIR, 'blog_admin', 'uploads', filename)
        if not os.path.isfile(path):
            self.send_error(404)
            return
        mime, _ = mimetypes.guess_type(path)
        mime = mime or 'application/octet-stream'
        with open(path, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'public, max-age=2592000')
        self.end_headers()
        self.wfile.write(data)

    def _blog_db(self):
        import sqlite3
        db_path = os.path.join(BASE_DIR, 'blog.db')
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _handle_blog_posts(self):
        try:
            conn = self._blog_db()
            rows = conn.execute("""
                SELECT p.id, p.slug, p.title, p.excerpt, p.cover_image,
                       p.publish_at, p.updated_at, c.name AS category
                FROM blog_posts p
                LEFT JOIN blog_categories c ON c.id = p.category_id
                WHERE p.status = 'published'
                ORDER BY COALESCE(p.publish_at, p.created_at) DESC
            """).fetchall()
            posts = [dict(r) for r in rows]
            self._json(200, {'posts': posts})
        except Exception as e:
            self._json(200, {'posts': []})

    def _handle_blog_article(self, slug):
        if not slug or '/' in slug or '..' in slug:
            return self._json(404, {'error': 'Not Found'})
        try:
            conn = self._blog_db()
            row = conn.execute("""
                SELECT p.*, c.name AS category
                FROM blog_posts p
                LEFT JOIN blog_categories c ON c.id = p.category_id
                WHERE p.slug = ? AND p.status = 'published'
            """, (slug,)).fetchone()
        except Exception:
            row = None
        if not row:
            self._html(404, '<h1>文章不存在</h1>')
            return
        p = dict(row)
        pub_date = (p.get('publish_at') or p.get('updated_at') or '')[:10]
        keywords_meta = f'<meta name="keywords" content="{p["keywords"]}">' if p.get('keywords') else ''
        desc_meta = f'<meta name="description" content="{p["excerpt"]}">' if p.get('excerpt') else ''
        cover_html = f'<img class="article-cover-img" src="{p["cover_image"]}" alt="{p["title"]}">' if p.get('cover_image') else ''
        cat_html = f'<span class="article-tag">{p["category"]}</span>' if p.get('category') else ''
        self._html(200, f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{p["title"]} — AICDN</title>
{keywords_meta}{desc_meta}
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#fff;color:#1A2033}}
a{{color:inherit;text-decoration:none}}
/* ── Navbar (同官網) ── */
nav{{position:sticky;top:0;left:0;right:0;z-index:100;padding:0 40px;height:64px;display:flex;align-items:center;justify-content:space-between;background:rgba(255,255,255,0.92);backdrop-filter:blur(16px);border-bottom:1px solid rgba(0,87,255,0.15)}}
.nav-logo{{display:flex;align-items:center;gap:10px;text-decoration:none}}
.nav-logo-img{{height:40px;width:auto;display:block;mix-blend-mode:multiply}}
.nav-links{{display:flex;gap:32px;list-style:none}}
.nav-links a{{color:#6B7280;text-decoration:none;font-size:14px;transition:color .2s}}
.nav-links a:hover{{color:#1A2033}}
.nav-links a.active{{color:#0057FF;font-weight:600}}
.nav-cta{{background:linear-gradient(135deg,#0057FF,#00C8FF);color:#fff;border:none;border-radius:6px;padding:8px 20px;font-size:14px;font-weight:500;cursor:pointer;text-decoration:none;box-shadow:0 0 18px rgba(0,87,255,.3);transition:transform .2s,box-shadow .2s}}
.nav-cta:hover{{transform:translateY(-1px);box-shadow:0 0 28px rgba(0,87,255,.5)}}
.nav-cta-forum{{background:linear-gradient(135deg,#A855F7,#7C3AED);color:#fff;border:none;border-radius:6px;padding:8px 20px;font-size:14px;font-weight:500;cursor:pointer;text-decoration:none;box-shadow:0 0 14px rgba(124,58,237,.25);transition:transform .2s,box-shadow .2s}}
.nav-cta-forum:hover{{transform:translateY(-1px);box-shadow:0 0 24px rgba(124,58,237,.45)}}
.nav-cta-login{{background:transparent;color:#374151;border:1px solid #9CA3AF;border-radius:6px;padding:7px 16px;font-size:14px;font-weight:500;cursor:pointer;text-decoration:none;transition:border-color .2s,color .2s}}
.nav-cta-login:hover{{border-color:#0057FF;color:#0057FF}}
@media(max-width:768px){{nav{{padding:0 20px}}.nav-links{{display:none}}}}
/* ── Article ── */
.article-wrap{{max-width:780px;margin:56px auto;padding:0 24px 100px}}
.article-tag{{display:inline-block;background:#EFF6FF;color:#0057FF;padding:4px 14px;border-radius:20px;font-size:13px;font-weight:600;margin-bottom:16px}}
h1.article-title{{font-size:32px;font-weight:800;line-height:1.35;color:#0F1629;margin-bottom:12px}}
.article-meta{{font-size:13px;color:#9CA3AF;margin-bottom:32px}}
.article-cover-img{{width:100%;border-radius:14px;margin-bottom:40px;object-fit:cover;max-height:420px}}
.article-body{{font-size:16px;line-height:1.85;color:#374151}}
.article-body h2{{font-size:22px;font-weight:700;color:#0F1629;margin:40px 0 14px}}
.article-body h3{{font-size:18px;font-weight:700;color:#1A2033;margin:28px 0 10px}}
.article-body p{{margin-bottom:18px}}
.article-body ul,.article-body ol{{margin-bottom:18px;padding-left:28px}}
.article-body li{{margin-bottom:8px}}
.article-body strong{{color:#0F1629}}
.article-body a{{color:#0057FF;text-decoration:underline}}
.article-body pre{{background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;padding:20px;font-size:13px;line-height:1.8;overflow-x:auto;color:#374151;margin:24px 0}}
.article-body code{{background:#EFF6FF;padding:2px 7px;border-radius:4px;font-size:13px;color:#0057FF}}
.article-body img{{max-width:100%;border-radius:8px;margin:12px 0}}
.article-body blockquote{{border-left:4px solid #0057FF;margin:24px 0;padding:12px 20px;background:#F0F5FF;border-radius:0 8px 8px 0;color:#374151;font-style:italic}}
.article-cta{{margin-top:60px;background:linear-gradient(135deg,rgba(0,87,255,.06),rgba(0,200,255,.04));border:1px solid rgba(0,87,255,.15);border-radius:16px;padding:36px;text-align:center}}
.article-cta h3{{font-size:20px;font-weight:700;color:#0F1629;margin-bottom:10px}}
.article-cta p{{color:#6B7280;margin-bottom:20px}}
.btn-primary{{display:inline-block;background:linear-gradient(135deg,#0057FF,#00C8FF);color:#fff;padding:12px 32px;border-radius:8px;font-weight:700;font-size:15px;box-shadow:0 0 18px rgba(0,87,255,.3)}}
</style>
</head>
<body>
<nav>
  <a class="nav-logo" href="/">
    <img decoding="async" class="nav-logo-img" src="/images/logo-aicdn.png" alt="AiCDN SkyCloud">
  </a>
  <ul class="nav-links">
    <li><a href="/">首頁</a></li>
    <li><a href="/pricing">價格方案</a></li>
    <li><a href="/cname">CNAME教學</a></li>
    <li><a href="/faq">常見問題</a></li>
    <li><a href="/blog" class="active">專欄部落格</a></li>
  </ul>
  <div style="display:flex;align-items:center;gap:8px;">
    <a href="https://forum.aicdn.ai" target="_blank" class="nav-cta-forum">論壇</a>
    <a href="/" class="nav-cta">免費參與 →</a>
    <a href="https://portal.aicdn.ai" target="_blank" class="nav-cta-login">登入</a>
  </div>
</nav>
<div class="article-wrap">
  {cat_html}
  <h1 class="article-title">{p["title"]}</h1>
  <div class="article-meta">騰雲運算 SkyCloud 編輯部・{pub_date}</div>
  {cover_html}
  <div class="article-body">{p["content"]}</div>
  <div class="article-cta">
    <h3>準備好讓 AI 看見你的品牌了嗎？</h3>
    <p>免費參與 AICDN AI 爬蟲成長計劃，7 天觀測，數據說話。</p>
    <a href="/" class="btn-primary">立即免費報名 →</a>
  </div>
</div>
</body>
</html>''')

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
                cfg = load_config()
                mail.notify_new_lead(cfg, data)
                mail.notify_applicant(cfg, data)
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
