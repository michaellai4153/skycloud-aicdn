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
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA foreign_keys=ON')
    return c


def init_schema():
    with _conn() as c:
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


# ─── BUYER ────────────────────────────────────────────────────────────────
BUYER_FIELDS = ['name', 'title', 'company', 'email', 'domain', 'status',
                'start', 'end', 'ip', 'note', 'createdAt']
BUYER_UPDATABLE = ['status', 'name', 'title', 'company', 'email', 'domain',
                   'start', 'end', 'ip', 'note']


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


# ─── INIT ON IMPORT ───────────────────────────────────────────────────────
init_schema()
