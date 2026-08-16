import sqlite3, os

DB_PATH = os.environ.get(
    'BLOG_DB_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'blog.db')
)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS cms_users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            display_name  TEXT,
            password_hash TEXT NOT NULL,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS blog_categories (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            ord  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS blog_posts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            slug         TEXT NOT NULL UNIQUE,
            title        TEXT NOT NULL,
            excerpt      TEXT    DEFAULT '',
            content      TEXT    DEFAULT '',
            cover_image  TEXT    DEFAULT '',
            category_id  INTEGER REFERENCES blog_categories(id) ON DELETE SET NULL,
            keywords     TEXT    DEFAULT '',
            status       TEXT    NOT NULL DEFAULT 'draft',
            publish_at   DATETIME,
            created_by   INTEGER REFERENCES cms_users(id),
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)
