"""Generate 10 fixed FAQ questions for the home-page AI assistant.

Run on demand (initial setup or periodic refresh):
    python3 gen_questions.py

Uses OpenAI to read the knowledge base and produce 10 distinct, customer-facing
questions a Buyer or Seller might ask. Output is written to the qa_questions
table (replacing the previous batch) and answers cache is cleared (FK cascade).
"""
import json
import re
import unicodedata

import db
import knowledge_base
import openai_client


PROMPT = """以下是 AICDN 行銷網站的完整知識庫：

==========
{kb}
==========

請依據上述知識庫，產生 10 個**台灣潛在客戶最可能問的問題**，
這些問題會顯示在官方網站的首頁，由真人或潛在 Buyer/Seller 點選。

要求：
1. 問題口語、清楚、有具體脈絡，避免空泛
2. 10 題要涵蓋不同面向（價格、功能、SEO、合作模式、申請流程、隱私 等）
3. 每題提供一個 URL 適用的 slug（英文小寫、用連字號分隔、不超過 50 字元）
4. 純 JSON 回答，格式：
{{
  "questions": [
    {{"slug": "...", "question": "..."}},
    ...
  ]
}}
不要包含其他文字或 markdown 圍欄。"""


def slugify(text):
    """Fallback slug normaliser if the model returns something messy."""
    text = unicodedata.normalize('NFKD', text)
    text = re.sub(r'[^a-zA-Z0-9一-鿿\s-]', '', text).strip()
    text = re.sub(r'\s+', '-', text).lower()
    return text[:50] or 'question'


def generate():
    prompt = PROMPT.format(kb=knowledge_base.KNOWLEDGE)
    print('Asking OpenAI to generate 10 questions...')
    text = openai_client.chat(
        [{'role': 'user', 'content': prompt}],
        model='gpt-4o-mini',
        temperature=0.7,
        max_tokens=1200,
        response_format={'type': 'json_object'},
    )
    data = json.loads(text)
    items = data.get('questions') or []
    if len(items) < 5:
        raise RuntimeError(f'Expected ~10 questions, got {len(items)}')

    # Normalise + dedupe slugs
    seen = set()
    cleaned = []
    for it in items[:10]:
        slug = slugify(it.get('slug') or it.get('question', ''))
        base = slug
        n = 2
        while slug in seen:
            slug = f'{base}-{n}'
            n += 1
        seen.add(slug)
        cleaned.append({'slug': slug, 'question': it['question'].strip()})

    db.upsert_qa_questions(cleaned)
    print(f'\nSaved {len(cleaned)} questions:')
    for it in cleaned:
        print(f'  {it["slug"]:<40} {it["question"]}')


if __name__ == '__main__':
    generate()
