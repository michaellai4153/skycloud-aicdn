"""Minimal OpenAI Chat Completions client.

Uses stdlib only (urllib) so we don't introduce pip dependencies on the
production host. Reads the API key from config.json on each call so a
rotated key only requires a config update — no restart needed.
"""
import json
import os
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _api_key():
    cfg_path = os.path.join(BASE_DIR, 'config.json')
    if os.path.exists(cfg_path):
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        key = cfg.get('openai_api_key')
        if key:
            return key
    return os.environ.get('OPENAI_API_KEY', '')


def chat(messages, *, model='gpt-4o-mini', temperature=0.4, max_tokens=600,
         response_format=None, timeout=30):
    """Call OpenAI Chat Completions. Returns the assistant text or raises."""
    key = _api_key()
    if not key:
        raise RuntimeError('OpenAI API key not configured (config.json: openai_api_key)')

    body = {
        'model': model,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
    }
    if response_format is not None:
        body['response_format'] = response_format

    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        data=json.dumps(body).encode('utf-8'),
        headers={
            'Content-Type':  'application/json',
            'Authorization': f'Bearer {key}',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'OpenAI HTTP {e.code}: {detail}') from None

    return payload['choices'][0]['message']['content']
