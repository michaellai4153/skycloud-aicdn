"""Outbound email (internal new-lead alerts + applicant confirmations) via SMTP."""
import datetime
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

NOTIFY_TO = ['aicdn@skycloud.com.tw', 'eason@skycloud.com.tw']

FIELD_LABELS = [
    ('name', '姓名'), ('title', '職稱'), ('company', '公司'),
    ('email', 'Email'), ('phone', '電話'), ('domain', '官網域名'),
]

LOGO_URL = 'https://www.aicdn.ai/images/logo-aicdn.png'

HTML_SIGNATURE = f"""
<div style="margin-top:40px;padding-top:24px;border-top:1px solid #E5E7EB;text-align:center;">
  <a href="https://www.aicdn.ai" target="_blank">
    <img src="{LOGO_URL}" alt="AICDN SkyCloud" style="height:48px;width:auto;display:inline-block;">
  </a>
  <p style="margin:12px 0 4px;font-size:12px;color:#6B7280;">SkyCloud 騰雲運算 — AI 爬蟲成長計劃</p>
  <p style="margin:0 0 4px;font-size:12px;color:#9CA3AF;">
    客服信箱：<a href="mailto:aicdn@skycloud.com.tw" style="color:#0057FF;text-decoration:none;">aicdn@skycloud.com.tw</a>
  </p>
  <p style="margin:0;font-size:12px;color:#9CA3AF;">
    官網：<a href="https://www.aicdn.ai" style="color:#0057FF;text-decoration:none;">www.aicdn.ai</a>
  </p>
</div>
"""

def _html_wrap(body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F9FAFB;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F9FAFB;padding:40px 20px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;border:1px solid #E5E7EB;padding:48px 48px 40px;max-width:600px;width:100%;">
        <tr><td>
          {body_html}
          {HTML_SIGNATURE}
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _send(cfg, *, to_addr, subject, body_text, body_html=None):
    smtp_cfg = cfg.get('smtp') or {}
    host = smtp_cfg.get('host')
    user = smtp_cfg.get('user')
    password = smtp_cfg.get('password')
    if not (host and user and password):
        print('[mail] smtp not configured, skipping email')
        return

    port = smtp_cfg.get('port', 587)
    from_addr = smtp_cfg.get('from', user)

    # to_addr may be a string or a list
    recipients = to_addr if isinstance(to_addr, list) else [to_addr]
    to_header = ', '.join(recipients)

    if body_html:
        msg = MIMEMultipart('alternative')
        msg.attach(MIMEText(body_text, 'plain', _charset='utf-8'))
        msg.attach(MIMEText(body_html, 'html', _charset='utf-8'))
    else:
        msg = MIMEText(body_text, 'plain', _charset='utf-8')

    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = to_header

    try:
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.starttls()
            s.login(user, password)
            s.sendmail(from_addr, recipients, msg.as_string())
    except Exception as e:
        print(f'[mail] failed to send email to {to_header}: {e}')


def _internal_notification_body(lead):
    lines = [f'{label}：{lead.get(field) or "—"}' for field, label in FIELD_LABELS]
    return '\n'.join(lines)


def _notify_recipients(cfg):
    """Return the full internal notification recipient list."""
    smtp_cfg = cfg.get('smtp') or {}
    extra = smtp_cfg.get('notify_to')
    base = list(NOTIFY_TO)
    if extra:
        extras = extra if isinstance(extra, list) else [extra]
        for e in extras:
            if e not in base:
                base.append(e)
    return base


def notify_new_lead(cfg, lead):
    """Internal alert to the AICDN team that a new buyer form was submitted."""
    to_addr = _notify_recipients(cfg)
    subject = f'[AICDN Buyer] 新報名：{lead.get("company") or lead.get("name") or ""}'
    body = _internal_notification_body(lead)
    threading.Thread(target=_send, args=(cfg,),
                      kwargs=dict(to_addr=to_addr, subject=subject, body_text=body),
                      daemon=True).start()


def notify_new_seller_lead(cfg, lead):
    """Internal alert to the AICDN team that a new seller form was submitted."""
    to_addr = _notify_recipients(cfg)
    subject = f'[AICDN Seller] 新報名：{lead.get("company") or lead.get("name") or ""}'
    body = _internal_notification_body(lead)
    threading.Thread(target=_send, args=(cfg,),
                      kwargs=dict(to_addr=to_addr, subject=subject, body_text=body),
                      daemon=True).start()


# ── Buyer confirmation ────────────────────────────────────────────────────────

_BUYER_TEXT = """您好，{customer_name} 先生／小姐：

我們已收到您提交的 AICDN 免費試用申請，申請資訊如下：
公司名稱：{company_name}
申請網域：{service_domain}
申請時間：{application_submitted_at}（Asia/Taipei）

請您先至 AICDN Portal 完成「聯絡人資訊」與「身份驗證」，完成後將由專人與您聯繫，協助確認試用方案及後續啟用流程。
AICDN 商務平台：portal.aicdn.ai

如有任何問題，歡迎透過以下方式聯繫我們：
AICDN 團隊客服信箱：aicdn@skycloud.com.tw
"""

_BUYER_HTML = """
<h2 style="margin:0 0 8px;font-size:20px;font-weight:700;color:#0A0E1A;">您好，{customer_name} 先生／小姐：</h2>
<p style="margin:0 0 24px;font-size:14px;color:#6B7280;">我們已收到您提交的 AICDN 免費試用申請</p>

<table width="100%" cellpadding="0" cellspacing="0" style="background:#F0F4FF;border-radius:8px;padding:20px 24px;margin-bottom:28px;">
  <tr><td>
    <p style="margin:0 0 6px;font-size:13px;color:#374151;"><strong>公司名稱：</strong>{company_name}</p>
    <p style="margin:0 0 6px;font-size:13px;color:#374151;"><strong>申請網域：</strong>{service_domain}</p>
    <p style="margin:0;font-size:13px;color:#374151;"><strong>申請時間：</strong>{application_submitted_at}（Asia/Taipei）</p>
  </td></tr>
</table>

<p style="margin:0 0 16px;font-size:14px;color:#374151;line-height:1.7;">
  請您先至 AICDN Portal 完成「聯絡人資訊」與「身份驗證」，完成後將由專人與您聯繫，協助確認試用方案及後續啟用流程。
</p>

<div style="text-align:center;margin:28px 0;">
  <a href="https://portal.aicdn.ai" style="display:inline-block;background:linear-gradient(135deg,#0057FF,#00C8FF);color:white;text-decoration:none;padding:14px 36px;border-radius:8px;font-size:15px;font-weight:600;">前往 AICDN Portal →</a>
</div>
"""


def notify_applicant(cfg, lead):
    """Confirmation email sent back to the applicant themselves."""
    to_addr = lead.get('email')
    if not to_addr:
        return
    submitted_at = lead.get('createdAt') or datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    fmt = dict(
        customer_name=lead.get('name') or '',
        company_name=lead.get('company') or '',
        service_domain=lead.get('domain') or '',
        application_submitted_at=submitted_at,
    )
    body_text = _BUYER_TEXT.format(**fmt)
    body_html = _html_wrap(_BUYER_HTML.format(**fmt))
    subject = '【AICDN】已收到您的免費試用申請'
    threading.Thread(target=_send, args=(cfg,),
                      kwargs=dict(to_addr=to_addr, subject=subject,
                                  body_text=body_text, body_html=body_html),
                      daemon=True).start()


# ── Seller confirmation ───────────────────────────────────────────────────────

_SELLER_TEXT = """您好，{customer_name} 先生／小姐：

我們已收到您提交的 AICDN 賣家登記資料。
請登入 AICDN Portal，依序完成以下啟用步驟：

1. 註冊 Portal 帳號
2. 完成身分認證
3. 選擇參與方案
4. 於網站完成 CDN 加掛
5. 上傳可供引薦的網站內容

完成以上設定並通過確認後，即可正式啟用 AICDN 分潤計畫，開始透過網站資源獲得分潤收益。

立即前往 AICDN Portal：
https://portal.aicdn.ai/login

如在註冊或設定過程中遇到問題，歡迎聯繫我們：
AICDN 團隊
客服信箱：aicdn@skycloud.com.tw
LINE 官方帳號：https://line.me/ti/p/~@aicdn
"""

_SELLER_HTML = """
<h2 style="margin:0 0 8px;font-size:20px;font-weight:700;color:#0A0E1A;">您好，{customer_name} 先生／小姐：</h2>
<p style="margin:0 0 24px;font-size:14px;color:#6B7280;">我們已收到您提交的 AICDN 賣家登記資料</p>

<p style="margin:0 0 12px;font-size:14px;color:#374151;line-height:1.7;">
  請登入 AICDN Portal，依序完成以下啟用步驟：
</p>

<table width="100%" cellpadding="0" cellspacing="0" style="background:#F0F4FF;border-radius:8px;padding:20px 24px;margin-bottom:28px;">
  <tr><td>
    <p style="margin:0 0 8px;font-size:13px;color:#374151;">① 註冊 Portal 帳號</p>
    <p style="margin:0 0 8px;font-size:13px;color:#374151;">② 完成身分認證</p>
    <p style="margin:0 0 8px;font-size:13px;color:#374151;">③ 選擇參與方案</p>
    <p style="margin:0 0 8px;font-size:13px;color:#374151;">④ 於網站完成 CDN 加掛</p>
    <p style="margin:0;font-size:13px;color:#374151;">⑤ 上傳可供引薦的網站內容</p>
  </td></tr>
</table>

<p style="margin:0 0 24px;font-size:14px;color:#374151;line-height:1.7;">
  完成以上設定並通過確認後，即可正式啟用 AICDN 分潤計畫，開始透過網站資源獲得分潤收益。
</p>

<div style="text-align:center;margin:28px 0;">
  <a href="https://portal.aicdn.ai/login" style="display:inline-block;background:linear-gradient(135deg,#0057FF,#00C8FF);color:white;text-decoration:none;padding:14px 36px;border-radius:8px;font-size:15px;font-weight:600;">立即前往 AICDN Portal →</a>
</div>

<p style="margin:0;font-size:13px;color:#6B7280;line-height:1.7;">
  如有任何問題，歡迎聯繫我們：<br>
  LINE 官方帳號：<a href="https://line.me/ti/p/~@aicdn" style="color:#0057FF;text-decoration:none;">@aicdn</a>
</p>
"""


def notify_seller_applicant(cfg, lead):
    """Confirmation email sent to the seller applicant after form submission."""
    to_addr = lead.get('email')
    if not to_addr:
        return
    fmt = dict(customer_name=lead.get('name') or '')
    body_text = _SELLER_TEXT.format(**fmt)
    body_html = _html_wrap(_SELLER_HTML.format(**fmt))
    subject = '【AICDN】已收到您的賣家登記，請完成分潤計畫啟用任務'
    threading.Thread(target=_send, args=(cfg,),
                      kwargs=dict(to_addr=to_addr, subject=subject,
                                  body_text=body_text, body_html=body_html),
                      daemon=True).start()
