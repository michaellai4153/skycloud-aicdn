#!/usr/bin/env python3
"""Run once to create the initial CMS user."""
from werkzeug.security import generate_password_hash
from blog_db import get_db, init_db

USERS = [
    {'username': 'skcmarketing', 'display_name': 'Marketing', 'password': 'Skycloudlove$marketing'},
]

init_db()
with get_db() as conn:
    for u in USERS:
        try:
            conn.execute(
                "INSERT INTO cms_users (username, display_name, password_hash) VALUES (?,?,?)",
                (u['username'], u['display_name'], generate_password_hash(u['password']))
            )
            print(f"Created user: {u['username']}")
        except Exception as e:
            print(f"Skip {u['username']}: {e}")
