import os, re, uuid, mimetypes
from datetime import datetime, timezone
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, send_from_directory, abort)
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
from apscheduler.schedulers.background import BackgroundScheduler

from blog_db import get_db, init_db

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR  = os.path.join(BASE_DIR, 'uploads')
ALLOWED_EXT = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'}
MAX_MB      = 10

app = Flask(__name__)
app.secret_key = os.environ.get('BLOG_SECRET', 'aicdn-cms-secret-change-in-prod-2024')
app.config['MAX_CONTENT_LENGTH'] = MAX_MB * 1024 * 1024

os.makedirs(UPLOAD_DIR, exist_ok=True)
init_db()

# ── Helpers ───────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text, flags=re.UNICODE)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    return text or f'post-{int(datetime.now().timestamp())}'

def unique_slug(base, exclude_id=None):
    db = get_db()
    candidate = base
    i = 1
    while True:
        row = db.execute(
            "SELECT id FROM blog_posts WHERE slug=? AND id!=?",
            (candidate, exclude_id or -1)
        ).fetchone()
        if not row:
            return candidate
        candidate = f'{base}-{i}'
        i += 1

def now_utc():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

# ── Scheduled publish (every minute) ─────────────────────────────────────────
def publish_scheduled_posts():
    try:
        with get_db() as db:
            db.execute("""
                UPDATE blog_posts
                SET status='published', updated_at=CURRENT_TIMESTAMP
                WHERE status='scheduled' AND publish_at <= CURRENT_TIMESTAMP
            """)
    except Exception as e:
        app.logger.error(f'Scheduler error: {e}')

scheduler = BackgroundScheduler()
scheduler.add_job(publish_scheduled_posts, 'interval', minutes=1)
scheduler.start()

# ── Auth routes ───────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('post_list'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()
        user = db.execute('SELECT * FROM cms_users WHERE username=?', (username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id']  = user['id']
            session['username'] = user['username']
            session['display']  = user['display_name'] or user['username']
            next_url = request.args.get('next') or url_for('post_list')
            return redirect(next_url)
        error = '帳號或密碼錯誤'
    return render_template('login.html', error=error)

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── Post list ─────────────────────────────────────────────────────────────────
@app.route('/')
@app.route('/posts')
@login_required
def post_list():
    db = get_db()
    q      = request.args.get('q', '').strip()
    status = request.args.get('status', '')
    sql    = """
        SELECT p.*, c.name AS category_name
        FROM blog_posts p
        LEFT JOIN blog_categories c ON c.id = p.category_id
        WHERE 1=1
    """
    params = []
    if q:
        sql += " AND (p.title LIKE ? OR p.keywords LIKE ?)"
        params += [f'%{q}%', f'%{q}%']
    if status:
        sql += " AND p.status = ?"
        params.append(status)
    sql += " ORDER BY p.updated_at DESC"
    posts = db.execute(sql, params).fetchall()
    cats  = db.execute("SELECT * FROM blog_categories ORDER BY ord, name").fetchall()
    return render_template('list.html', posts=posts, cats=cats,
                           q=q, status_filter=status)

# ── New post ──────────────────────────────────────────────────────────────────
@app.route('/posts/new', methods=['GET', 'POST'])
@login_required
def post_new():
    db   = get_db()
    cats = db.execute("SELECT * FROM blog_categories ORDER BY ord, name").fetchall()
    if request.method == 'POST':
        return _save_post(db, cats, post_id=None)
    return render_template('edit.html', post=None, cats=cats)

# ── Edit post ─────────────────────────────────────────────────────────────────
@app.route('/posts/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def post_edit(post_id):
    db   = get_db()
    post = db.execute('SELECT * FROM blog_posts WHERE id=?', (post_id,)).fetchone()
    if not post:
        abort(404)
    cats = db.execute("SELECT * FROM blog_categories ORDER BY ord, name").fetchall()
    if request.method == 'POST':
        return _save_post(db, cats, post_id=post_id)
    return render_template('edit.html', post=post, cats=cats)

def _save_post(db, cats, post_id):
    title      = request.form.get('title', '').strip()
    slug_input = request.form.get('slug', '').strip()
    excerpt    = request.form.get('excerpt', '').strip()
    content    = request.form.get('content', '').strip()
    keywords   = request.form.get('keywords', '').strip()
    cat_id     = request.form.get('category_id') or None
    action     = request.form.get('action', 'draft')
    publish_at = request.form.get('publish_at', '').strip() or None
    cover      = request.form.get('cover_image', '').strip()

    # Validation
    errors = []
    if not title:
        errors.append('標題為必填欄位')
    if action == 'publish' and not content:
        errors.append('發布文章必須填寫內文')
    if action == 'scheduled' and not publish_at:
        errors.append('預約發布必須設定發布時間')

    slug = slug_input or slugify(title)
    slug = unique_slug(slug, exclude_id=post_id)

    if errors:
        flash('；'.join(errors), 'error')
        post = db.execute('SELECT * FROM blog_posts WHERE id=?', (post_id,)).fetchone() if post_id else None
        return render_template('edit.html', post=post, cats=cats,
                               form=request.form)

    status = {'publish': 'published', 'scheduled': 'scheduled'}.get(action, 'draft')

    if post_id:
        db.execute("""
            UPDATE blog_posts SET title=?, slug=?, excerpt=?, content=?, keywords=?,
            category_id=?, status=?, publish_at=?, cover_image=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (title, slug, excerpt, content, keywords, cat_id, status, publish_at, cover, post_id))
        flash('文章已儲存', 'success')
        pid = post_id
    else:
        cur = db.execute("""
            INSERT INTO blog_posts (title, slug, excerpt, content, keywords,
            category_id, status, publish_at, cover_image, created_by)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (title, slug, excerpt, content, keywords, cat_id, status, publish_at, cover,
              session['user_id']))
        db.commit()
        flash('文章已建立', 'success')
        pid = cur.lastrowid

    return redirect(url_for('post_edit', post_id=pid))

# ── Quick status actions ───────────────────────────────────────────────────────
@app.route('/posts/<int:post_id>/unpublish', methods=['POST'])
@login_required
def post_unpublish(post_id):
    with get_db() as db:
        db.execute("UPDATE blog_posts SET status='unpublished', updated_at=CURRENT_TIMESTAMP WHERE id=?", (post_id,))
    flash('文章已下架', 'success')
    return redirect(url_for('post_list'))

@app.route('/posts/<int:post_id>/delete', methods=['POST'])
@login_required
def post_delete(post_id):
    with get_db() as db:
        db.execute("DELETE FROM blog_posts WHERE id=?", (post_id,))
    flash('文章已刪除', 'success')
    return redirect(url_for('post_list'))

# ── Preview ───────────────────────────────────────────────────────────────────
@app.route('/posts/<int:post_id>/preview')
@login_required
def post_preview(post_id):
    db   = get_db()
    post = db.execute("""
        SELECT p.*, c.name AS category_name
        FROM blog_posts p LEFT JOIN blog_categories c ON c.id=p.category_id
        WHERE p.id=?
    """, (post_id,)).fetchone()
    if not post:
        abort(404)
    return render_template('preview.html', post=post)

# ── Category CRUD ─────────────────────────────────────────────────────────────
@app.route('/categories', methods=['GET', 'POST'])
@login_required
def categories():
    db = get_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name:
            slug = unique_slug(slugify(name))
            try:
                db.execute("INSERT INTO blog_categories (name, slug) VALUES (?,?)", (name, slug))
                db.commit()
                flash(f'分類「{name}」已建立', 'success')
            except Exception:
                flash('分類建立失敗（名稱重複？）', 'error')
        return redirect(url_for('categories'))
    cats = db.execute("SELECT * FROM blog_categories ORDER BY ord, name").fetchall()
    return render_template('categories.html', cats=cats)

@app.route('/categories/<int:cat_id>/delete', methods=['POST'])
@login_required
def category_delete(cat_id):
    with get_db() as db:
        db.execute("DELETE FROM blog_categories WHERE id=?", (cat_id,))
    flash('分類已刪除', 'success')
    return redirect(url_for('categories'))

# ── API: image upload ─────────────────────────────────────────────────────────
@app.route('/api/upload-image', methods=['POST'])
@login_required
def upload_image():
    f = request.files.get('file')
    if not f or not allowed_file(f.filename):
        return jsonify({'error': '不支援的檔案格式'}), 400
    ext      = f.filename.rsplit('.', 1)[1].lower()
    filename = f'{uuid.uuid4().hex}.{ext}'
    f.save(os.path.join(UPLOAD_DIR, filename))
    return jsonify({'url': f'/media/{filename}'})

# ── API: slug check ───────────────────────────────────────────────────────────
@app.route('/api/check-slug')
@login_required
def check_slug():
    slug       = request.args.get('slug', '').strip()
    exclude_id = request.args.get('exclude_id', type=int)
    if not slug:
        return jsonify({'available': False, 'reason': '不可為空'})
    db  = get_db()
    row = db.execute(
        "SELECT id FROM blog_posts WHERE slug=? AND id!=?",
        (slug, exclude_id or -1)
    ).fetchone()
    return jsonify({'available': row is None})

# ── Serve uploads ─────────────────────────────────────────────────────────────
@app.route('/media/<filename>')
def media(filename):
    return send_from_directory(UPLOAD_DIR, filename)

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8767))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
