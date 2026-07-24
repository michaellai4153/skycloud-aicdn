#!/usr/bin/env python3
"""
AICDN Forum Server — port 8767
Production: real Google OAuth via oauth.py
Dev mode:   if forum_config.json missing or google_client_id is empty,
            falls back to mock login (type any email).
"""

import http.server
import json
import os
import sqlite3
import urllib.parse
import uuid
import re
from datetime import datetime, timezone

import oauth as _oauth   # reuse existing oauth.py

try:
    import mistune, re as _re
    _md_renderer = mistune.Markdown()
    _ALLOWED_TAGS = {'p','b','i','strong','em','code','pre','ul','ol','li',
                     'blockquote','h1','h2','h3','h4','a','br','hr','del','s'}
    def _strip_tags(html):
        # Remove any tag not in the allowlist (and all <script>/<style>/event attrs)
        html = _re.sub(r'<script[\s\S]*?</script>', '', html, flags=_re.IGNORECASE)
        html = _re.sub(r'<style[\s\S]*?</style>', '', html, flags=_re.IGNORECASE)
        # Strip disallowed tags
        def _tag(m):
            tag = _re.match(r'</?(\w+)', m.group(0))
            if tag and tag.group(1).lower() in _ALLOWED_TAGS:
                # Strip event handler attributes (on*)
                cleaned = _re.sub(r'\s+on\w+=["\'][^"\']*["\']', '', m.group(0), flags=_re.IGNORECASE)
                cleaned = _re.sub(r'\s+on\w+=\S+', '', cleaned, flags=_re.IGNORECASE)
                # Strip javascript: in href/src
                cleaned = _re.sub(r'(href|src)=["\']javascript:[^"\']*["\']', '', cleaned, flags=_re.IGNORECASE)
                return cleaned
            return ''
        return _re.sub(r'<[^>]+>', _tag, html)
    def md(text): return _strip_tags(_md_renderer(text))
except Exception:
    def md(text): return text.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\n','<br>')

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(BASE_DIR, 'forum_sandbox.db')
CFG_PATH   = os.path.join(BASE_DIR, 'forum_config.json')
FORUM_PORT = 8767

SUPER_ADMINS = {'cliff@skycloud.com.tw', 'michael@skycloud.com.tw', 'lucy@skycloud.com.tw', 'eason@skycloud.com.tw'}

# ── Bot detection & SSR ───────────────────────────────────────────────────────

_BOT_UAS = {'gptbot', 'perplexitybot', 'claudebot', 'googlebot',
            'bingbot', 'anthropic-ai', 'cohere-ai', 'diffbot',
            'facebookbot', 'twitterbot', 'linkedinbot', 'slurp'}

def _is_bot(ua: str) -> bool:
    ua = ua.lower()
    return any(b in ua for b in _BOT_UAS)

def _esc(s) -> str:
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

def render_thread_ssr(tid: int) -> str:
    conn = get_db()
    t = conn.execute('''
        SELECT ft.*, fc.name as cat_name
        FROM forum_threads ft
        LEFT JOIN forum_categories fc ON ft.category_id = fc.id
        WHERE ft.id = ?
    ''', (tid,)).fetchone()
    if not t:
        conn.close()
        return ''
    comments = conn.execute('''
        SELECT body_md, created_at, author_name, author_email
        FROM forum_comments
        WHERE thread_id = ? AND is_deleted = 0 ORDER BY created_at ASC
    ''', (tid,)).fetchall()
    conn.close()

    comments_html = ''.join(f'''
      <div style="border-top:1px solid #eee;padding:16px 0">
        <strong>{_esc(c["author_name"] or c["author_email"])}</strong>
        <span style="color:#888;font-size:12px;margin-left:8px">{_esc(c["created_at"])}</span>
        <div style="margin-top:8px;font-size:14px;line-height:1.7">{md(c["body_md"] or "")}</div>
      </div>''' for c in comments)

    cfg = load_config()
    base_url = cfg.get('base_url', 'https://forum.aicdn.ai').rstrip('/')

    return f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{_esc(t["title"])} — AICDN 論壇</title>
  <meta name="description" content="{_esc((t['body_md'] or '')[:160])}">
  <link rel="canonical" href="{base_url}/t/{_esc(t['slug'] or str(tid))}">
  <style>
    body{{font-family:sans-serif;max-width:820px;margin:40px auto;padding:0 20px;color:#1A2033;line-height:1.7}}
    a{{color:#0057FF}} h1{{font-size:22px;line-height:1.4;margin-bottom:8px}}
    .meta{{color:#888;font-size:13px;margin-bottom:24px}}
    .body{{font-size:15px;line-height:1.8;margin-bottom:32px}}
    .body h2,.body h3{{margin:20px 0 8px}} .body code{{background:#eef;padding:1px 5px;border-radius:3px}}
    .body pre{{background:#f5f5f5;padding:14px;border-radius:6px;overflow-x:auto;font-size:13px}}
    .body ul,.body ol{{padding-left:22px}} .body blockquote{{border-left:3px solid #0057FF;padding-left:12px;color:#555}}
  </style>
</head>
<body>
  <p><a href="{base_url}">← AICDN 論壇</a></p>
  <h1>{_esc(t["title"])}</h1>
  <div class="meta">
    作者：{_esc(t["author_name"] or t["author_email"] or "")} &nbsp;·&nbsp;
    分類：{_esc(t["cat_name"] or "—")} &nbsp;·&nbsp;
    {_esc(t["created_at"])}
  </div>
  <div class="body">{md(t["body_md"] or "")}</div>
  <h2 style="font-size:16px;color:#555">{len(comments)} 則回覆</h2>
  {comments_html}
</body>
</html>'''

# ── Slug generation ───────────────────────────────────────────────────────────

def make_slug(title: str, tid: int) -> str:
    """Extract ASCII words from title, fallback to t-{id}. Always ends with -{id}."""
    # keep alphanumeric and spaces, lowercase
    ascii_part = re.sub(r'[^a-zA-Z0-9\s]', ' ', title).lower()
    words = ascii_part.split()
    if words:
        slug_base = '-'.join(words)[:50].rstrip('-')
    else:
        slug_base = 't'
    return f'{slug_base}-{tid}'

def get_or_create_slug(conn, tid: int, title: str) -> str:
    row = conn.execute('SELECT slug FROM forum_threads WHERE id=?', (tid,)).fetchone()
    if row and row['slug']:
        return row['slug']
    slug = make_slug(title, tid)
    conn.execute('UPDATE forum_threads SET slug=? WHERE id=?', (slug, tid))
    conn.commit()
    return slug

# ── Config ────────────────────────────────────────────────────────────────────

def load_config():
    if not os.path.exists(CFG_PATH):
        return {}
    with open(CFG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def is_dev_mode():
    cfg = load_config()
    return not cfg.get('google_client_id', '').strip()

def oauth_redirect_uri(cfg):
    base = cfg.get('base_url', f'http://localhost:{FORUM_PORT}').rstrip('/')
    return f'{base}/api/forum/oauth/callback'

# ── DB ────────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS forum_admins (
            email       TEXT PRIMARY KEY,
            added_by    TEXT,
            added_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS forum_categories (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT NOT NULL UNIQUE,
            slug  TEXT NOT NULL UNIQUE,
            color TEXT DEFAULT "#0057FF",
            ord   INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS forum_threads (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id   INTEGER REFERENCES forum_categories(id),
            author_email  TEXT NOT NULL,
            author_name   TEXT NOT NULL,
            title         TEXT NOT NULL,
            body_md       TEXT NOT NULL,
            body_html     TEXT NOT NULL,
            is_pinned     INTEGER DEFAULT 0,
            is_admin_post INTEGER DEFAULT 0,
            reply_count   INTEGER DEFAULT 0,
            view_count    INTEGER DEFAULT 0,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS forum_comments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id    INTEGER REFERENCES forum_threads(id) ON DELETE CASCADE,
            author_email TEXT NOT NULL,
            author_name  TEXT NOT NULL,
            body_md      TEXT NOT NULL,
            body_html    TEXT NOT NULL,
            is_best      INTEGER DEFAULT 0,
            is_deleted   INTEGER DEFAULT 0,
            created_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS forum_sessions (
            id         TEXT PRIMARY KEY,
            email      TEXT NOT NULL,
            name       TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_threads_cat  ON forum_threads(category_id);
        CREATE INDEX IF NOT EXISTS idx_threads_pin  ON forum_threads(is_pinned);
        CREATE INDEX IF NOT EXISTS idx_comments_tid ON forum_comments(thread_id);
    ''')

    # Migration: add slug column if not exists
    cols = [r[1] for r in conn.execute('PRAGMA table_info(forum_threads)').fetchall()]
    if 'slug' not in cols:
        conn.execute('ALTER TABLE forum_threads ADD COLUMN slug TEXT DEFAULT ""')
        conn.commit()

    now = utcnow()
    for email in SUPER_ADMINS:
        c.execute('INSERT OR IGNORE INTO forum_admins(email,added_by,added_at) VALUES(?,?,?)',
                  (email, 'system', now))

    cats = [
        ('公告',           'announcements', '#F59E0B', 1),
        ('操作指南',       'guides',        '#10B981', 2),
        ('技術問答',       'technical',     '#0057FF', 3),
        ('帳號與付款',     'billing',       '#8B5CF6', 4),
        ('一般討論',       'general',       '#0099DD', 5),
        ('功能建議',       'feedback',      '#EF4444', 6),
        ('AI 爬蟲 & AEO', 'aeo',           '#0099DD', 7),
    ]
    for name, slug, color, ord_ in cats:
        c.execute('INSERT OR IGNORE INTO forum_categories(name,slug,color,ord) VALUES(?,?,?,?)',
                  (name, slug, color, ord_))

    c.execute('SELECT COUNT(*) FROM forum_threads')
    if c.fetchone()[0] == 0:
        sample = [
            (1, 'cliff@skycloud.com.tw', 'Cliff (SkyCloud)',
             '【公告】AICDN 服務上線說明與 CNAME 設定指南',
             '歡迎使用 AICDN！\n\n本文說明如何完成 **CNAME 設定**，讓你的網站開始接收 AI 爬蟲流量。\n\n## 步驟一\n\n前往你的 DNS 管理平台，新增一筆 CNAME 記錄：\n\n```\nwww  CNAME  xxxxxx-site-01.gocname.com\n```\n\n## 步驟二\n\n等待 DNS 生效（通常 5–30 分鐘）。\n\n如有問題請在下方留言！',
             1, 1),
            (3, 'cliff@skycloud.com.tw', 'Cliff (SkyCloud)',
             '什麼是 AI 爬蟲？GPTBot、ClaudeBot、PerplexityBot 完整介紹',
             '近年來 AI 公司大量部署自動爬蟲收集訓練資料。\n\n## 主要 AI 爬蟲\n\n- **GPTBot** — OpenAI\n- **ClaudeBot** — Anthropic\n- **PerplexityBot** — Perplexity AI\n- **Google-Extended** — Google\n\n## 如何允許 AI 爬蟲？\n\n在 `robots.txt` 中加入對應規則，或使用 AICDN 統一管理。',
             0, 1),
            (3, 'user@example.com', 'wang_dev',
             'CNAME 設定完成後多久會生效？',
             '我昨天在 GoDaddy 設定好了，但現在 `nslookup` 還是顯示舊的 IP。\n\n請問需要等多久？',
             0, 0),
            (5, 'alice@example.com', 'alice_shop',
             '請問分潤撥款的時間是每月幾號？',
             '我是商業主，想了解分潤收益的計算週期和撥款日期，謝謝！',
             0, 0),
        ]
        for cat_id, email, name, title, body, pinned, is_admin in sample:
            html = md(body)
            c.execute('''INSERT INTO forum_threads
                (category_id,author_email,author_name,title,body_md,body_html,
                 is_pinned,is_admin_post,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (cat_id, email, name, title, body, html, pinned, is_admin, now, now))

        c.execute('SELECT id FROM forum_threads WHERE title LIKE "%CNAME 設定完成%"')
        row = c.fetchone()
        if row:
            tid = row[0]
            cb = 'DNS 傳播通常需要 **1–48 小時**，視你的 TTL 設定而定。可用 [nslookup.io](https://nslookup.io) 即時查詢。'
            c.execute('''INSERT INTO forum_comments
                (thread_id,author_email,author_name,body_md,body_html,is_best,created_at)
                VALUES(?,?,?,?,?,?,?)''',
                (tid, 'cliff@skycloud.com.tw', 'Cliff (SkyCloud)', cb, md(cb), 1, now))
            c.execute('UPDATE forum_threads SET reply_count=1 WHERE id=?', (tid,))

    # Backfill slugs for any thread missing one
    threads_no_slug = conn.execute(
        'SELECT id, title FROM forum_threads WHERE slug IS NULL OR slug=""'
    ).fetchall()
    for row in threads_no_slug:
        slug = make_slug(row['title'], row['id'])
        c.execute('UPDATE forum_threads SET slug=? WHERE id=?', (slug, row['id']))

    conn.commit()
    conn.close()

def utcnow():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

# ── Session helpers ───────────────────────────────────────────────────────────

SESSION_COOKIE = 'forum_sid'

def get_session(cookie_header):
    if not cookie_header:
        return None
    for part in cookie_header.split(';'):
        part = part.strip()
        if part.startswith(f'{SESSION_COOKIE}='):
            sid = part[len(f'{SESSION_COOKIE}='):]
            conn = get_db()
            row = conn.execute('SELECT * FROM forum_sessions WHERE id=?', (sid,)).fetchone()
            conn.close()
            return dict(row) if row else None
    return None

def create_session(email, name):
    sid = str(uuid.uuid4())
    conn = get_db()
    conn.execute('INSERT OR REPLACE INTO forum_sessions(id,email,name,created_at) VALUES(?,?,?,?)',
                 (sid, email, name, utcnow()))
    conn.commit()
    conn.close()
    return sid

def set_session_cookie(sid, secure=True):
    parts = [f'{SESSION_COOKIE}={sid}', 'Path=/', 'HttpOnly', 'SameSite=Lax', 'Max-Age=86400']
    if secure:
        parts.append('Secure')
    return '; '.join(parts)

def clear_session_cookie():
    return f'{SESSION_COOKIE}=; Path=/; Max-Age=0'

def is_admin_email(email):
    conn = get_db()
    row = conn.execute('SELECT 1 FROM forum_admins WHERE email=?', (email,)).fetchone()
    conn.close()
    return row is not None

# ── Handler ───────────────────────────────────────────────────────────────────

class ForumHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype='application/json', extra_headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype + '; charset=utf-8')
        self.send_header('Content-Length', len(data))
        self.send_header('Access-Control-Allow-Origin', '*')
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, obj)

    def _html(self, code, html):
        self._send(code, html, 'text/html')

    def _redirect(self, url, extra_headers=None):
        self.send_response(302)
        self.send_header('Location', url)
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length).decode('utf-8') if length else ''

    def _parse_json(self):
        try:
            return json.loads(self._read_body())
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,DELETE,PUT,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        p = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        cookie = self.headers.get('Cookie', '')
        session = get_session(cookie)

        # ── Semantic thread URLs ──
        # New: /t/{slug}-{id}
        m_slug = re.match(r'^/t/([\w-]+-(\d+))$', p)
        # Old: /t/{id}  → 301 to /t/{slug}-{id}
        m_id   = re.match(r'^/t/(\d+)$', p)

        if m_id and not m_slug:
            # Old URL — 301 to canonical slug URL
            tid = int(m_id.group(1))
            conn = get_db()
            row = conn.execute('SELECT id, title, slug FROM forum_threads WHERE id=?', (tid,)).fetchone()
            conn.close()
            if not row:
                self._json(404, {'error': 'not found'}); return
            slug = row['slug'] or make_slug(row['title'], tid)
            self.send_response(301)
            self.send_header('Location', f'/t/{slug}')
            self.end_headers()
            return

        if m_slug:
            full_slug = m_slug.group(1)
            tid = int(m_slug.group(2))
            conn = get_db()
            row = conn.execute('SELECT id, title, slug FROM forum_threads WHERE id=?', (tid,)).fetchone()
            conn.close()
            if not row:
                self._json(404, {'error': 'not found'}); return
            correct_slug = row['slug'] or make_slug(row['title'], tid)
            if full_slug != correct_slug:
                # Slug mismatch — 301 to correct canonical
                self.send_response(301)
                self.send_header('Location', f'/t/{correct_slug}')
                self.end_headers()
                return
            ua = self.headers.get('User-Agent', '')
            if _is_bot(ua):
                html = render_thread_ssr(tid)
                self._html(200 if html else 404, html or '<h1>404</h1>')
                return

        # /c/{category-slug} → SPA (JS will read slug from URL and filter)
        m_cat = re.match(r'^/c/([\w-]+)$', p)

        if p in ('/', '/forum', '/forum.html', '') or m_slug or m_cat:
            fpath = os.path.join(BASE_DIR, 'forum.html')
            with open(fpath, 'r', encoding='utf-8') as f:
                self._html(200, f.read())
            return

        # ── Static files ──
        if p.startswith('/images/') or p.split('.')[-1] in ('png','jpg','jpeg','webp','ico','svg','css','js'):
            fpath = os.path.realpath(os.path.join(BASE_DIR, p.lstrip('/')))
            _base = os.path.realpath(BASE_DIR)
            if not fpath.startswith(_base + os.sep):
                self._json(403, {'error': 'forbidden'}); return
            if os.path.exists(fpath):
                ext = os.path.splitext(fpath)[1]
                ctypes = {'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg',
                          '.webp':'image/webp','.ico':'image/x-icon','.svg':'image/svg+xml',
                          '.css':'text/css','.js':'application/javascript'}
                with open(fpath, 'rb') as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', ctypes.get(ext, 'application/octet-stream'))
                self.send_header('Content-Length', len(data))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._json(404, {'error': 'not found'})
            return

        # ── robots.txt ──
        if p == '/robots.txt':
            body = (
                'User-agent: *\n'
                'Disallow: /api/\n'
                'Disallow: /admin\n'
                'Disallow: /login\n'
                '\n'
                'User-agent: Googlebot\n'
                'Allow: /\n'
                '\n'
                'User-agent: Bingbot\n'
                'Allow: /\n'
                '\n'
                'User-agent: GPTBot\n'
                'Allow: /\n'
                '\n'
                'User-agent: ClaudeBot\n'
                'Allow: /\n'
                '\n'
                'User-agent: PerplexityBot\n'
                'Allow: /\n'
                '\n'
                'User-agent: Google-Extended\n'
                'Allow: /\n'
                '\n'
                'User-agent: anthropic-ai\n'
                'Allow: /\n'
                '\n'
                f'Sitemap: {load_config().get("base_url", "https://forum.aicdn.ai").rstrip("/")}/sitemap.xml\n'
            ).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
            return

        # ── sitemap.xml ──
        if p == '/sitemap.xml':
            cfg = load_config()
            base = cfg.get('base_url', 'https://forum.aicdn.ai').rstrip('/')
            conn = get_db()
            threads = conn.execute(
                'SELECT slug, updated_at, created_at FROM forum_threads ORDER BY created_at DESC'
            ).fetchall()
            categories = conn.execute(
                'SELECT slug FROM forum_categories WHERE slug IS NOT NULL AND slug != ""'
            ).fetchall()
            conn.close()

            def fmt_date(d):
                if not d:
                    return ''
                return d[:10]

            urls = []
            # Homepage
            urls.append(f'  <url><loc>{base}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>')
            # Category pages
            for cat in categories:
                urls.append(f'  <url><loc>{base}/c/{cat["slug"]}</loc><changefreq>daily</changefreq><priority>0.8</priority></url>')
            # Thread pages
            for t in threads:
                lastmod = fmt_date(t['updated_at'] or t['created_at'])
                lm_tag = f'<lastmod>{lastmod}</lastmod>' if lastmod else ''
                urls.append(f'  <url><loc>{base}/t/{t["slug"]}</loc>{lm_tag}<changefreq>weekly</changefreq><priority>0.7</priority></url>')

            xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                   + '\n'.join(urls) + '\n</urlset>').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/xml; charset=utf-8')
            self.send_header('Content-Length', len(xml))
            self.end_headers()
            self.wfile.write(xml)
            return

        # ── /api/forum/me ──
        if p == '/api/forum/me':
            if session:
                self._json(200, {
                    'email': session['email'],
                    'name':  session['name'],
                    'is_admin': is_admin_email(session['email'])
                })
            else:
                self._json(200, {'email': None, 'dev_mode': is_dev_mode()})
            return

        # ── /api/forum/dev_mode ──
        if p == '/api/forum/dev_mode':
            self._json(200, {'dev_mode': is_dev_mode()})
            return

        # ── Google OAuth: login ──
        if p == '/api/forum/oauth/login':
            cfg = load_config()
            if is_dev_mode():
                self._json(400, {'error': 'dev mode — use mock login'}); return
            return_to = qs.get('return', ['/'])[0]
            proxy = cfg.get('openai_proxy')  # same proxy for Google API calls
            url, _ = _oauth.authorize_url(
                client_id=cfg['google_client_id'],
                redirect_uri=oauth_redirect_uri(cfg),
                return_to=return_to,
                hd_hint=None,   # allow ANY Google account for forum
            )
            self._redirect(url)
            return

        # ── Google OAuth: callback ──
        if p == '/api/forum/oauth/callback':
            cfg = load_config()
            code  = qs.get('code',  [None])[0]
            state = qs.get('state', [None])[0]
            error = qs.get('error', [None])[0]

            if error or not code:
                self._html(400, f'<p>OAuth 錯誤：{error or "no code"}</p><a href="/">返回</a>')
                return

            return_to = _oauth.consume_state(state)
            if return_to is None:
                self._html(400, '<p>無效或過期的 state，請重新登入。</p><a href="/">返回</a>')
                return

            try:
                proxy = cfg.get('openai_proxy')
                tokens = _oauth.exchange_code(
                    code,
                    client_id=cfg['google_client_id'],
                    client_secret=cfg['google_client_secret'],
                    redirect_uri=oauth_redirect_uri(cfg),
                    proxy=proxy,
                )
                userinfo = _oauth.fetch_userinfo(tokens['access_token'], proxy=proxy)
            except Exception as e:
                self._html(500, f'<p>OAuth 交換失敗：{e}</p><a href="/">返回</a>')
                return

            email = userinfo.get('email', '').lower()
            name  = userinfo.get('name') or email.split('@')[0]

            if not email:
                self._html(400, '<p>無法取得 Email，請確認已授權。</p><a href="/">返回</a>')
                return

            sid = create_session(email, name)
            # Use Secure only in production (HTTPS)
            is_prod = cfg.get('base_url', '').startswith('https')
            cookie_val = set_session_cookie(sid, secure=is_prod)
            self._redirect('/', extra_headers={'Set-Cookie': cookie_val})
            return

        # ── Categories ──
        if p == '/api/forum/categories':
            conn = get_db()
            cats = conn.execute('SELECT * FROM forum_categories ORDER BY ord').fetchall()
            conn.close()
            self._json(200, [dict(c) for c in cats])
            return

        # ── Threads list ──
        if p == '/api/forum/threads':
            cat_id = qs.get('category_id', [None])[0]
            conn = get_db()
            if cat_id:
                rows = conn.execute('''
                    SELECT t.*, c.name as cat_name, c.color as cat_color
                    FROM forum_threads t
                    LEFT JOIN forum_categories c ON t.category_id=c.id
                    WHERE t.category_id=?
                    ORDER BY t.is_pinned DESC, t.created_at DESC
                ''', (cat_id,)).fetchall()
            else:
                rows = conn.execute('''
                    SELECT t.*, c.name as cat_name, c.color as cat_color
                    FROM forum_threads t
                    LEFT JOIN forum_categories c ON t.category_id=c.id
                    ORDER BY t.is_pinned DESC, t.created_at DESC
                ''').fetchall()
            conn.close()
            self._json(200, [dict(r) for r in rows])
            return

        # ── Single thread ──
        m = re.match(r'^/api/forum/threads/(\d+)$', p)
        if m:
            tid = int(m.group(1))
            conn = get_db()
            conn.execute('UPDATE forum_threads SET view_count=view_count+1 WHERE id=?', (tid,))
            conn.commit()
            thread = conn.execute('''
                SELECT t.*, c.name as cat_name, c.color as cat_color
                FROM forum_threads t
                LEFT JOIN forum_categories c ON t.category_id=c.id
                WHERE t.id=?
            ''', (tid,)).fetchone()
            if not thread:
                conn.close(); self._json(404, {'error': 'not found'}); return
            comments = conn.execute('''
                SELECT * FROM forum_comments
                WHERE thread_id=? AND is_deleted=0
                ORDER BY is_best DESC, created_at ASC
            ''', (tid,)).fetchall()
            conn.close()
            self._json(200, {'thread': dict(thread), 'comments': [dict(c) for c in comments]})
            return

        # ── Admins list ──
        if p == '/api/forum/admins':
            if not session or not is_admin_email(session['email']):
                self._json(403, {'error': 'forbidden'}); return
            conn = get_db()
            admins = conn.execute('SELECT * FROM forum_admins ORDER BY added_at').fetchall()
            conn.close()
            self._json(200, [dict(a) for a in admins])
            return

        self._json(404, {'error': 'not found'})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        p = parsed.path
        cookie = self.headers.get('Cookie', '')
        session = get_session(cookie)
        data = self._parse_json()

        # ── Dev mode mock login ──
        if p == '/api/forum/login':
            if not is_dev_mode():
                self._json(400, {'error': 'use Google OAuth in production'}); return
            email = data.get('email', '').strip().lower()
            name  = data.get('name', '').strip() or email.split('@')[0]
            if not email or '@' not in email:
                self._json(400, {'error': 'invalid email'}); return
            sid = create_session(email, name)
            body = json.dumps({
                'ok': True, 'email': email, 'name': name,
                'is_admin': is_admin_email(email)
            }, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', len(body))
            self.send_header('Set-Cookie', set_session_cookie(sid, secure=False))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)
            return

        # ── Logout ──
        if p == '/api/forum/logout':
            if session:
                conn = get_db()
                conn.execute('DELETE FROM forum_sessions WHERE id=?', (session['id'],))
                conn.commit()
                conn.close()
            body = json.dumps({'ok': True}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', len(body))
            self.send_header('Set-Cookie', clear_session_cookie())
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)
            return

        # ── Create thread ──
        if p == '/api/forum/threads':
            if not session:
                self._json(401, {'error': 'login required'}); return
            title   = data.get('title', '').strip()
            body_md = data.get('body', '').strip()
            cat_id  = data.get('category_id')
            is_admin_post = 1 if (data.get('is_admin_post') and is_admin_email(session['email'])) else 0
            if not title or not body_md or not cat_id:
                self._json(400, {'error': 'missing fields'}); return
            now = utcnow()
            conn = get_db()
            cur = conn.execute('''
                INSERT INTO forum_threads
                (category_id,author_email,author_name,title,body_md,body_html,
                 is_admin_post,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
            ''', (cat_id, session['email'], session['name'], title, body_md,
                  md(body_md), is_admin_post, now, now))
            tid = cur.lastrowid
            slug = make_slug(title, tid)
            conn.execute('UPDATE forum_threads SET slug=? WHERE id=?', (slug, tid))
            conn.commit(); conn.close()
            self._json(201, {'id': tid, 'slug': slug})
            return

        # ── Create comment ──
        m = re.match(r'^/api/forum/threads/(\d+)/comments$', p)
        if m:
            if not session:
                self._json(401, {'error': 'login required'}); return
            tid = int(m.group(1))
            body_md = data.get('body', '').strip()
            if not body_md:
                self._json(400, {'error': 'empty comment'}); return
            now = utcnow()
            conn = get_db()
            cur = conn.execute('''
                INSERT INTO forum_comments
                (thread_id,author_email,author_name,body_md,body_html,created_at)
                VALUES(?,?,?,?,?,?)
            ''', (tid, session['email'], session['name'], body_md, md(body_md), now))
            cid = cur.lastrowid
            conn.execute('UPDATE forum_threads SET reply_count=reply_count+1, updated_at=? WHERE id=?',
                         (now, tid))
            conn.commit()
            comment = conn.execute('SELECT * FROM forum_comments WHERE id=?', (cid,)).fetchone()
            conn.close()
            self._json(201, dict(comment))
            return

        # ── Add admin ──
        if p == '/api/forum/admins':
            if not session or not is_admin_email(session['email']):
                self._json(403, {'error': 'forbidden'}); return
            email = data.get('email', '').strip().lower()
            if not email or '@' not in email:
                self._json(400, {'error': 'invalid email'}); return
            conn = get_db()
            conn.execute('INSERT OR IGNORE INTO forum_admins(email,added_by,added_at) VALUES(?,?,?)',
                         (email, session['email'], utcnow()))
            conn.commit(); conn.close()
            self._json(200, {'ok': True})
            return

        # ── Pin thread ──
        m = re.match(r'^/api/forum/threads/(\d+)/pin$', p)
        if m:
            if not session or not is_admin_email(session['email']):
                self._json(403, {'error': 'forbidden'}); return
            tid = int(m.group(1))
            conn = get_db()
            row = conn.execute('SELECT is_pinned FROM forum_threads WHERE id=?', (tid,)).fetchone()
            new_val = 0 if row['is_pinned'] else 1
            conn.execute('UPDATE forum_threads SET is_pinned=? WHERE id=?', (new_val, tid))
            conn.commit(); conn.close()
            self._json(200, {'is_pinned': new_val})
            return

        # ── Mark best answer ──
        m = re.match(r'^/api/forum/comments/(\d+)/best$', p)
        if m:
            if not session or not is_admin_email(session['email']):
                self._json(403, {'error': 'forbidden'}); return
            cid = int(m.group(1))
            conn = get_db()
            row = conn.execute('SELECT thread_id, is_best FROM forum_comments WHERE id=?', (cid,)).fetchone()
            if row:
                conn.execute('UPDATE forum_comments SET is_best=0 WHERE thread_id=?', (row['thread_id'],))
                new_val = 0 if row['is_best'] else 1
                conn.execute('UPDATE forum_comments SET is_best=? WHERE id=?', (new_val, cid))
                conn.commit()
            conn.close()
            self._json(200, {'ok': True})
            return

        self._json(404, {'error': 'not found'})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        p = parsed.path
        cookie = self.headers.get('Cookie', '')
        session = get_session(cookie)

        # ── Delete thread ──
        m = re.match(r'^/api/forum/threads/(\d+)$', p)
        if m:
            if not session or not is_admin_email(session['email']):
                self._json(403, {'error': 'forbidden'}); return
            tid = int(m.group(1))
            conn = get_db()
            conn.execute('DELETE FROM forum_threads WHERE id=?', (tid,))
            conn.commit(); conn.close()
            self._json(200, {'ok': True})
            return

        # ── Delete comment ──
        m = re.match(r'^/api/forum/comments/(\d+)$', p)
        if m:
            if not session or not is_admin_email(session['email']):
                self._json(403, {'error': 'forbidden'}); return
            cid = int(m.group(1))
            conn = get_db()
            row = conn.execute('SELECT thread_id FROM forum_comments WHERE id=?', (cid,)).fetchone()
            if row:
                conn.execute('UPDATE forum_comments SET is_deleted=1 WHERE id=?', (cid,))
                conn.execute('UPDATE forum_threads SET reply_count=MAX(0,reply_count-1) WHERE id=?',
                             (row['thread_id'],))
                conn.commit()
            conn.close()
            self._json(200, {'ok': True})
            return

        # ── Remove admin ──
        m = re.match(r'^/api/forum/admins/(.+)$', p)
        if m:
            if not session or not is_admin_email(session['email']):
                self._json(403, {'error': 'forbidden'}); return
            email = urllib.parse.unquote(m.group(1))
            if email in SUPER_ADMINS:
                self._json(400, {'error': 'cannot remove super admin'}); return
            conn = get_db()
            conn.execute('DELETE FROM forum_admins WHERE email=?', (email,))
            conn.commit(); conn.close()
            self._json(200, {'ok': True})
            return

        self._json(404, {'error': 'not found'})

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        p = parsed.path
        cookie = self.headers.get('Cookie', '')
        session = get_session(cookie)
        data = self._parse_json()

        # ── Edit thread (admin OR original author) ──
        m = re.match(r'^/api/forum/threads/(\d+)$', p)
        if m:
            if not session:
                self._json(401, {'error': 'login required'}); return
            tid = int(m.group(1))
            conn = get_db()
            thread = conn.execute('SELECT author_email FROM forum_threads WHERE id=?', (tid,)).fetchone()
            if not thread:
                conn.close(); self._json(404, {'error': 'not found'}); return
            is_author = thread['author_email'] == session['email']
            if not is_author and not is_admin_email(session['email']):
                conn.close(); self._json(403, {'error': 'forbidden'}); return
            title   = data.get('title', '').strip()
            body_md = data.get('body', '').strip()
            if not title or not body_md:
                conn.close(); self._json(400, {'error': 'missing fields'}); return
            conn.execute('UPDATE forum_threads SET title=?,body_md=?,body_html=?,updated_at=? WHERE id=?',
                         (title, body_md, md(body_md), utcnow(), tid))
            conn.commit(); conn.close()
            self._json(200, {'ok': True})
            return

        self._json(404, {'error': 'not found'})


if __name__ == '__main__':
    init_db()
    mode = 'DEV (mock login)' if is_dev_mode() else 'PRODUCTION (Google OAuth)'
    print(f'AICDN Forum — {mode}')
    print(f'http://localhost:{FORUM_PORT}')
    if is_dev_mode():
        print('→ Create forum_config.json with google_client_id to enable real OAuth')
    server = http.server.HTTPServer(('', FORUM_PORT), ForumHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
