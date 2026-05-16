"""One-shot migration: leads.json + seller_leads.json → aicdn.db

Run once on production after deploying the SQLite-aware server code:
    python3 migrate.py

Safe to re-run: backs up JSON to .bak and skips if DB already has data.
"""
import json
import os
import shutil
import sys

import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _backup(path):
    if os.path.exists(path):
        shutil.copy2(path, path + '.bak')
        print(f'  ✓ backed up to {path}.bak')


def migrate_buyer():
    src = os.path.join(BASE_DIR, 'leads.json')
    if not os.path.exists(src):
        print('Buyer: leads.json not found, skipping.')
        return
    if db.list_buyer_leads():
        print('Buyer: DB already has rows, skipping migration to avoid duplicates.')
        return
    with open(src, 'r', encoding='utf-8') as f:
        leads = json.load(f)
    print(f'Buyer: migrating {len(leads)} leads...')
    for d in leads:
        db.add_buyer_lead(d)
    _backup(src)
    print('  ✓ done')


def migrate_seller():
    src = os.path.join(BASE_DIR, 'seller_leads.json')
    if not os.path.exists(src):
        print('Seller: seller_leads.json not found, skipping.')
        return
    if db.list_seller_leads():
        print('Seller: DB already has rows, skipping migration to avoid duplicates.')
        return
    with open(src, 'r', encoding='utf-8') as f:
        leads = json.load(f)
    print(f'Seller: migrating {len(leads)} leads...')
    db.bulk_save_seller_leads(leads)
    _backup(src)
    print('  ✓ done')


if __name__ == '__main__':
    print(f'Database: {db.DB_FILE}')
    migrate_buyer()
    migrate_seller()
    print('Migration complete.')
