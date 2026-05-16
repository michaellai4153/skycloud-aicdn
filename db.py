"""Shared SQLite helper for buyer/seller leads.

Single file `aicdn.db`, two tables: `buyer_leads` and `seller_leads`.
WAL mode enables concurrent reads while writes are serialized via process lock.
"""
import sqlite3
import json
import os
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE  = os.path.join(BASE_DIR, 'aicdn.db')

# Serialize writes across threads (SQLite handles its own locking, but this
# avoids "database is locked" under bursty load on the small Python http server).
_write_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(DB_FILE, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


def _column_exists(c, table, column):
    rows = c.execute(f'PRAGMA table_info({table})').fetchall()
    return any(r['name'] == column for r in rows)


def _add_column_if_missing(c, table, column, decl):
    if _column_exists(c, table, column):
        return
    try:
        c.execute(f'ALTER TABLE {table} ADD COLUMN {column} {decl}')
    except sqlite3.OperationalError as e:
        # Tolerate concurrent init from another process (race after the existence check)
        if 'duplicate column name' not in str(e):
            raise


# Payment columns added to both buyer_leads and seller_leads.
# plan codes: buyer_m, buyer_y, seller_low_m, seller_low_y, seller_high_m, seller_high_y, custom
# payment_status: unpaid | link_sent | paid | failed
PAYMENT_COLUMNS = [
    ('plan',            "TEXT DEFAULT ''"),
    ('amount',          'INTEGER DEFAULT 0'),
    ('payment_status',  "TEXT DEFAULT 'unpaid'"),
    ('ecpay_order_id',  "TEXT DEFAULT ''"),
    ('payment_link',    "TEXT DEFAULT ''"),
    ('paid_at',         "TEXT DEFAULT ''"),
]


SESSION_TABLE_SQL = '''
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_email ON sessions(email);
'''


QA_TABLES_SQL = '''
CREATE TABLE IF NOT EXISTS qa_questions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT UNIQUE NOT NULL,
    question    TEXT NOT NULL,
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_qa_questions_slug ON qa_questions(slug);

CREATE TABLE IF NOT EXISTS qa_answers (
    slug         TEXT PRIMARY KEY,
    answer       TEXT NOT NULL,
    generated_at TEXT,
    FOREIGN KEY (slug) REFERENCES qa_questions(slug) ON DELETE CASCADE
);
'''


def init_schema():
    with _conn() as c:
        # WAL is a database-level setting; once enabled it persists.
        # Tolerate failure when another process is initializing concurrently.
        try:
            c.execute('PRAGMA journal_mode=WAL')
        except sqlite3.OperationalError:
            pass
        c.executescript('''
        CREATE TABLE IF NOT EXISTS buyer_leads (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT, title TEXT, company TEXT, email TEXT,
            domain    TEXT,
            status    TEXT DEFAULT '待處理',
            start     TEXT, end TEXT, ip TEXT, note TEXT,
            createdAt TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_buyer_email  ON buyer_leads(email);
        CREATE INDEX IF NOT EXISTS idx_buyer_status ON buyer_leads(status);

        CREATE TABLE IF NOT EXISTS seller_leads (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT, phone TEXT, email TEXT, website TEXT,
            type      TEXT, topic TEXT, traffic TEXT, ads TEXT, note TEXT,
            stage     INTEGER DEFAULT 0,
            nextDate  TEXT DEFAULT '',
            notes     TEXT DEFAULT '[]',
            createdAt TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_seller_email ON seller_leads(email);
        CREATE INDEX IF NOT EXISTS idx_seller_stage ON seller_leads(stage);
        ''')
        # Idempotent column additions (safe to re-run on existing DBs)
        for col, decl in PAYMENT_COLUMNS:
            _add_column_if_missing(c, 'buyer_leads', col, decl)
            _add_column_if_missing(c, 'seller_leads', col, decl)
        c.execute('CREATE INDEX IF NOT EXISTS idx_buyer_payment  ON buyer_leads(payment_status)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_seller_payment ON seller_leads(payment_status)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_buyer_order  ON buyer_leads(ecpay_order_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_seller_order ON seller_leads(ecpay_order_id)')
        c.executescript(QA_TABLES_SQL)
        c.executescript(SESSION_TABLE_SQL)


# ─── BUYER ────────────────────────────────────────────────────────────────
BUYER_FIELDS = ['name', 'title', 'company', 'email', 'domain', 'status',
                'start', 'end', 'ip', 'note', 'createdAt']
BUYER_UPDATABLE = ['status', 'name', 'title', 'company', 'email', 'domain',
                   'start', 'end', 'ip', 'note',
                   'plan', 'amount', 'payment_status', 'ecpay_order_id',
                   'payment_link', 'paid_at']


def list_buyer_leads():
    """Return all buyer leads as dicts. `rowIndex` aliases the primary key."""
    with _conn() as c:
        rows = c.execute('SELECT * FROM buyer_leads ORDER BY id').fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d['rowIndex'] = d['id']  # legacy field used by admin.html
            out.append(d)
        return out


def add_buyer_lead(d):
    cols = ','.join(BUYER_FIELDS)
    placeholders = ','.join(['?'] * len(BUYER_FIELDS))
    vals = [d.get(f, '') for f in BUYER_FIELDS]
    if not vals[BUYER_FIELDS.index('status')]:
        vals[BUYER_FIELDS.index('status')] = '待處理'
    with _write_lock, _conn() as c:
        c.execute(f'INSERT INTO buyer_leads ({cols}) VALUES ({placeholders})', vals)


def update_buyer_lead(lead_id, d):
    sets, vals = [], []
    for f in BUYER_UPDATABLE:
        if f in d:
            sets.append(f'{f} = ?')
            vals.append(d[f])
    if not sets:
        return
    vals.append(lead_id)
    with _write_lock, _conn() as c:
        c.execute(f'UPDATE buyer_leads SET {",".join(sets)} WHERE id = ?', vals)


# ─── SELLER ───────────────────────────────────────────────────────────────
SELLER_FIELDS = ['name', 'phone', 'email', 'website', 'type', 'topic',
                 'traffic', 'ads', 'note', 'stage', 'nextDate', 'notes',
                 'createdAt']


def _seller_row_to_dict(r):
    d = dict(r)
    try:
        d['notes'] = json.loads(d.get('notes') or '[]')
    except (json.JSONDecodeError, TypeError):
        d['notes'] = []
    return d


def list_seller_leads():
    with _conn() as c:
        rows = c.execute('SELECT * FROM seller_leads ORDER BY id').fetchall()
        return [_seller_row_to_dict(r) for r in rows]


def add_seller_lead(d):
    """Public application submission."""
    vals = [
        d.get('name', ''), d.get('phone', ''), d.get('email', ''), d.get('website', ''),
        d.get('type', ''), d.get('topic', ''), d.get('traffic', ''), d.get('ads', ''),
        d.get('note', ''), d.get('stage', 0), d.get('nextDate', ''),
        json.dumps(d.get('notes', []), ensure_ascii=False),
        d.get('createdAt', ''),
    ]
    with _write_lock, _conn() as c:
        cur = c.execute(
            f'INSERT INTO seller_leads ({",".join(SELLER_FIELDS)}) '
            f'VALUES ({",".join(["?"] * len(SELLER_FIELDS))})',
            vals,
        )
        return cur.lastrowid


def bulk_save_seller_leads(leads):
    """Replace all seller leads. Used by CRM bulkSave action."""
    with _write_lock, _conn() as c:
        c.execute('BEGIN')
        try:
            c.execute('DELETE FROM seller_leads')
            for d in leads:
                vals = [
                    d.get('id'),  # preserve client-side id
                    d.get('name', ''), d.get('phone', ''), d.get('email', ''),
                    d.get('website', ''), d.get('type', ''), d.get('topic', ''),
                    d.get('traffic', ''), d.get('ads', ''), d.get('note', ''),
                    d.get('stage', 0), d.get('nextDate', ''),
                    json.dumps(d.get('notes', []), ensure_ascii=False),
                    d.get('createdAt', ''),
                ]
                c.execute(
                    f'INSERT INTO seller_leads (id,{",".join(SELLER_FIELDS)}) '
                    f'VALUES (?,{",".join(["?"] * len(SELLER_FIELDS))})',
                    vals,
                )
            c.execute('COMMIT')
        except Exception:
            c.execute('ROLLBACK')
            raise


# ─── PAYMENT HELPERS ──────────────────────────────────────────────────────
# Works on either 'buyer_leads' or 'seller_leads' table.

def set_payment(table, lead_id, *, plan=None, amount=None,
                ecpay_order_id=None, payment_link=None,
                payment_status=None, paid_at=None):
    if table not in ('buyer_leads', 'seller_leads'):
        raise ValueError(f'invalid table: {table}')
    updates = {
        'plan': plan, 'amount': amount,
        'ecpay_order_id': ecpay_order_id, 'payment_link': payment_link,
        'payment_status': payment_status, 'paid_at': paid_at,
    }
    sets, vals = [], []
    for k, v in updates.items():
        if v is not None:
            sets.append(f'{k} = ?')
            vals.append(v)
    if not sets:
        return
    vals.append(lead_id)
    with _write_lock, _conn() as c:
        c.execute(f'UPDATE {table} SET {",".join(sets)} WHERE id = ?', vals)


def find_lead_by_order_id(order_id):
    """Look up a lead in either table by ECPay order id. Returns (table, row) or (None, None)."""
    with _conn() as c:
        for table in ('buyer_leads', 'seller_leads'):
            r = c.execute(
                f'SELECT * FROM {table} WHERE ecpay_order_id = ?', (order_id,)
            ).fetchone()
            if r:
                return table, dict(r)
    return None, None


# ─── QA (AI 助手知識問答) ───────────────────────────────────────────────
def list_qa_questions():
    """All published FAQ questions (ordered by id)."""
    with _conn() as c:
        rows = c.execute(
            'SELECT id, slug, question, created_at FROM qa_questions ORDER BY id'
        ).fetchall()
        return [dict(r) for r in rows]


def get_qa_question(slug):
    with _conn() as c:
        r = c.execute(
            'SELECT id, slug, question, created_at FROM qa_questions WHERE slug = ?',
            (slug,),
        ).fetchone()
        return dict(r) if r else None


def upsert_qa_questions(items):
    """Replace the FAQ list with the given items.
    `items` is a list of dicts: {slug, question}. Existing answers for any
    slugs not in the new list are cascade-deleted (FK ON DELETE CASCADE)."""
    import datetime as _dt
    now = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _write_lock, _conn() as c:
        c.execute('BEGIN')
        try:
            c.execute('DELETE FROM qa_questions')
            for item in items:
                c.execute(
                    'INSERT INTO qa_questions (slug, question, created_at) VALUES (?, ?, ?)',
                    (item['slug'], item['question'], now),
                )
            c.execute('COMMIT')
        except Exception:
            c.execute('ROLLBACK')
            raise


def get_qa_answer(slug):
    with _conn() as c:
        r = c.execute(
            'SELECT answer, generated_at FROM qa_answers WHERE slug = ?',
            (slug,),
        ).fetchone()
        return dict(r) if r else None


def set_qa_answer(slug, answer):
    import datetime as _dt
    now = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _write_lock, _conn() as c:
        c.execute(
            'INSERT OR REPLACE INTO qa_answers (slug, answer, generated_at) '
            'VALUES (?, ?, ?)',
            (slug, answer, now),
        )


# ─── SESSIONS (Google OAuth) ──────────────────────────────────────────────
def create_session(session_id, email, *, ttl_seconds=86400):
    import datetime as _dt
    now = _dt.datetime.now()
    expires = now + _dt.timedelta(seconds=ttl_seconds)
    with _write_lock, _conn() as c:
        c.execute(
            'INSERT INTO sessions (id, email, created_at, expires_at) VALUES (?, ?, ?, ?)',
            (session_id, email,
             now.strftime('%Y-%m-%d %H:%M:%S'),
             expires.strftime('%Y-%m-%d %H:%M:%S')),
        )


def get_session(session_id):
    """Return session dict if valid (not expired) else None."""
    import datetime as _dt
    if not session_id:
        return None
    with _conn() as c:
        r = c.execute(
            'SELECT id, email, created_at, expires_at FROM sessions WHERE id = ?',
            (session_id,),
        ).fetchone()
        if not r:
            return None
        d = dict(r)
    try:
        if _dt.datetime.strptime(d['expires_at'], '%Y-%m-%d %H:%M:%S') < _dt.datetime.now():
            return None
    except ValueError:
        return None
    return d


def delete_session(session_id):
    with _write_lock, _conn() as c:
        c.execute('DELETE FROM sessions WHERE id = ?', (session_id,))


def cleanup_expired_sessions():
    import datetime as _dt
    now = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _write_lock, _conn() as c:
        c.execute('DELETE FROM sessions WHERE expires_at < ?', (now,))


# ─── INIT ON IMPORT ───────────────────────────────────────────────────────
init_schema()
