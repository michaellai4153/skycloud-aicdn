"""ECPay (綠界) AIO Credit Card payment helpers.

References:
- API spec: https://developers.ecpay.com.tw/?p=2509
- Sandbox: https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5

Sandbox public test credentials (anyone can use):
    MerchantID = 3002607
    HashKey    = pwFHCqoQZGmho4w6
    HashIV     = EkRm7iFT261dpevs
    Test card  = 4311-9522-2222-2222 / any future expiry / any CVC
"""
import datetime
import hashlib
import secrets
from urllib.parse import quote_plus

SANDBOX_URL    = 'https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5'
PRODUCTION_URL = 'https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5'

DEFAULT_SANDBOX = {
    'merchant_id': '3002607',
    'hash_key':    'pwFHCqoQZGmho4w6',
    'hash_iv':     'EkRm7iFT261dpevs',
    'sandbox':     True,
}


# Plan code → (display name, default amount)
PLANS = {
    'buyer_starter_m': ('買家入門方案 月繳',   8000),
    'buyer_starter_q': ('買家入門方案 季繳',   15000),
    'buyer_starter_y': ('買家入門方案 年繳',   48000),
    'buyer_main_m':    ('買家主力方案 月繳',   12000),
    'buyer_main_q':    ('買家主力方案 季繳',   30000),
    'buyer_main_y':    ('買家主力方案 年繳',   96000),
    'buyer_flag_m':    ('買家旗艦方案 月繳',   18000),
    'buyer_flag_q':    ('買家旗艦方案 季繳',   45000),
    'buyer_flag_y':    ('買家旗艦方案 年繳',   144000),
    'seller_starter_y': ('賣家 starter 方案 年繳', 24000),
    'seller_elite_y':   ('賣家 elite 方案 年繳',   72000),
    'custom':          ('自訂方案',            0),
}


def get_endpoint(config):
    return SANDBOX_URL if config.get('sandbox', True) else PRODUCTION_URL


def new_order_id(prefix='AICDN'):
    """ECPay MerchantTradeNo: max 20 chars, alphanumeric.
    Format: AICDN(5) + YYMMDDHHmm(10) + 5 random hex = 20 chars."""
    ts = datetime.datetime.now().strftime('%y%m%d%H%M')
    rand = secrets.token_hex(3).upper()[:5]
    return f'{prefix}{ts}{rand}'


def _ecpay_urlencode(value):
    """ECPay uses .NET-style URL encoding. Same as standard urlencode but
    a handful of characters stay un-encoded."""
    s = quote_plus(str(value), safe='')
    # ECPay-specific: don't encode these
    return (s.replace('%21', '!').replace('%2A', '*')
              .replace('%28', '(').replace('%29', ')')
              .replace('%2D', '-').replace('%5F', '_')
              .replace('%2E', '.'))


def compute_check_mac_value(params, hash_key, hash_iv):
    """Build CheckMacValue per ECPay spec:
    1. Sort params by key (case-insensitive ascending)
    2. Concat: HashKey=<k>&key1=val1&...&HashIV=<iv>
    3. .NET-style URL encode
    4. Lowercase
    5. SHA256 hex, uppercase"""
    items = sorted(((k, v) for k, v in params.items() if k != 'CheckMacValue'),
                   key=lambda kv: kv[0].lower())
    raw = f'HashKey={hash_key}&' + '&'.join(f'{k}={v}' for k, v in items) + f'&HashIV={hash_iv}'
    encoded = _ecpay_urlencode(raw).lower()
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest().upper()


def build_checkout_params(config, *, order_id, amount, item_name, trade_desc,
                          return_url, client_back_url=''):
    """Build the parameter dict that the customer's browser POSTs to ECPay."""
    params = {
        'MerchantID':        config['merchant_id'],
        'MerchantTradeNo':   order_id,
        'MerchantTradeDate': datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S'),
        'PaymentType':       'aio',
        'TotalAmount':       str(int(amount)),
        'TradeDesc':         trade_desc,
        'ItemName':          item_name,
        'ReturnURL':         return_url,
        'ChoosePayment':     'Credit',
        'EncryptType':       '1',
    }
    if client_back_url:
        params['ClientBackURL'] = client_back_url
    params['CheckMacValue'] = compute_check_mac_value(
        params, config['hash_key'], config['hash_iv'])
    return params


def verify_callback(form_data, hash_key, hash_iv):
    """Verify the CheckMacValue from an ECPay callback. Returns True if valid."""
    received = form_data.get('CheckMacValue', '')
    if not received:
        return False
    expected = compute_check_mac_value(form_data, hash_key, hash_iv)
    return received.upper() == expected


def render_redirect_html(endpoint, params):
    """HTML page with auto-submitting form. Customer opens the payment link
    in browser → this page → form auto-POSTs to ECPay → ECPay credit card UI."""
    inputs = '\n'.join(
        f'    <input type="hidden" name="{k}" value="{v}">'
        for k, v in params.items()
    )
    return f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>導向綠界付款 — AICDN</title>
<style>
  body {{ font-family: -apple-system, sans-serif; text-align: center; padding: 80px 20px; color: #334; }}
  .spinner {{ width: 40px; height: 40px; border: 4px solid #e2e8f0; border-top-color: #0057FF;
              border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 24px; }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 8px; }}
  p {{ color: #64748b; font-size: 14px; }}
</style>
</head>
<body>
  <div class="spinner"></div>
  <h2>導向綠界刷卡頁面…</h2>
  <p>請勿關閉視窗，正在前往安全的付款頁。</p>
  <form id="ecpay" action="{endpoint}" method="POST">
{inputs}
  </form>
  <script>document.getElementById('ecpay').submit();</script>
</body>
</html>'''


def render_result_page(success, message):
    """Page user sees after ECPay redirects them back via ClientBackURL."""
    icon = '✅' if success else '⚠️'
    color = '#0057FF' if success else '#dc2626'
    return f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>付款結果 — AICDN</title>
<style>
  body {{ font-family: -apple-system, sans-serif; text-align: center; padding: 100px 20px; color: #334; }}
  .icon {{ font-size: 56px; margin-bottom: 24px; }}
  h1 {{ font-size: 24px; font-weight: 700; color: {color}; margin-bottom: 16px; }}
  p {{ color: #64748b; line-height: 1.7; max-width: 460px; margin: 0 auto; }}
  a {{ display: inline-block; margin-top: 32px; padding: 12px 28px; background: #0057FF;
      color: white; text-decoration: none; border-radius: 8px; font-weight: 500; }}
</style>
</head>
<body>
  <div class="icon">{icon}</div>
  <h1>{message}</h1>
  <p>感謝您使用騰雲運算 AICDN。<br>業務人員將於 1 個工作天內聯繫您完成服務開通。</p>
  <a href="/">返回首頁</a>
</body>
</html>'''
