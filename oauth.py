"""Google OAuth helpers.

Flow:
1. /api/oauth/login    → redirect to Google authorize
2. /api/oauth/callback → exchange code, verify hd, create session, set cookie
3. /api/logout         → delete session, clear cookie

State CSRF: random tokens stored in-memory with the desired return URL.
Sessions: stored in SQLite via db.create_session / db.get_session.
"""
import json
import secrets
import time
import urllib.parse
import urllib.request

GOOGLE_AUTH_URL     = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL    = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'

SCOPES = 'openid email profile'
SESSION_COOKIE = 'aicdn_session'
SESSION_TTL    = 86400  # 24h

# In-memory CSRF state: { state_token: (return_url, created_at) }
# State expires after 10 minutes. Keys are popped on use to prevent replay.
_states: dict = {}
_STATE_TTL = 600


def _cleanup_states():
    cutoff = time.time() - _STATE_TTL
    expired = [k for k, (_, t) in _states.items() if t < cutoff]
    for k in expired:
        _states.pop(k, None)


def authorize_url(*, client_id, redirect_uri, return_to='/admin.html',
                  hd_hint='skycloud.com.tw'):
    """Build the Google authorize URL. Returns (url, state_token)."""
    _cleanup_states()
    state = secrets.token_urlsafe(32)
    _states[state] = (return_to, time.time())
    params = {
        'client_id':     client_id,
        'redirect_uri':  redirect_uri,
        'response_type': 'code',
        'scope':         SCOPES,
        'state':         state,
        'access_type':   'online',
        'prompt':        'select_account',
    }
    if hd_hint:
        params['hd'] = hd_hint
    return f'{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}', state


def consume_state(state):
    """Return the return_url stored for this state, or None if invalid/expired."""
    entry = _states.pop(state, None)
    if not entry:
        return None
    return_to, ts = entry
    if time.time() - ts > _STATE_TTL:
        return None
    return return_to


def exchange_code(code, *, client_id, client_secret, redirect_uri,
                  proxy=None, timeout=15):
    """Exchange auth code for tokens. Returns the tokens dict."""
    body = urllib.parse.urlencode({
        'code':          code,
        'client_id':     client_id,
        'client_secret': client_secret,
        'redirect_uri':  redirect_uri,
        'grant_type':    'authorization_code',
    }).encode('utf-8')
    req = urllib.request.Request(
        GOOGLE_TOKEN_URL, data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )
    opener = _opener(proxy)
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def fetch_userinfo(access_token, *, proxy=None, timeout=15):
    """Fetch the userinfo for the authenticated user (email, hd, etc)."""
    req = urllib.request.Request(
        GOOGLE_USERINFO_URL,
        headers={'Authorization': f'Bearer {access_token}'},
    )
    opener = _opener(proxy)
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def _opener(proxy):
    """Build a urllib opener, optionally routing through an HTTP CONNECT proxy
    (same mechanism used in openai_client.py for the JP tunnel)."""
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({'https': proxy, 'http': proxy})
        )
    return urllib.request.build_opener()


def parse_session_cookie(cookie_header):
    """Extract the session id from a `Cookie:` header, if present."""
    if not cookie_header:
        return None
    for item in cookie_header.split(';'):
        k, _, v = item.strip().partition('=')
        if k == SESSION_COOKIE and v:
            return v
    return None


def session_cookie_header(session_id, *, max_age=SESSION_TTL):
    return (f'{SESSION_COOKIE}={session_id}; HttpOnly; Secure; '
            f'SameSite=Lax; Path=/; Max-Age={max_age}')


def clear_cookie_header():
    return f'{SESSION_COOKIE}=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0'


def render_denied(message='存取被拒'):
    """Page shown when domain check fails."""
    return f'''<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8"><title>存取被拒</title>
<style>body{{font-family:-apple-system,sans-serif;text-align:center;padding:100px 20px;color:#334}}
h1{{font-size:22px;margin-bottom:12px;color:#dc2626}}
a{{display:inline-block;margin-top:24px;padding:12px 28px;background:#0057FF;color:white;text-decoration:none;border-radius:8px}}</style>
</head><body><h1>{message}</h1>
<p>只允許 <code>@skycloud.com.tw</code> 的 Google 帳號登入。</p>
<a href="/">返回首頁</a></body></html>'''
