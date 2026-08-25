"""Outbound email (internal new-lead alerts + applicant confirmations) via SMTP."""
import datetime
import smtplib
import threading
from email.mime.text import MIMEText

NOTIFY_TO = 'aicdn@skycloud.com.tw'

FIELD_LABELS = [
    ('name', '姓名'), ('title', '職稱'), ('company', '公司'),
    ('email', 'Email'), ('phone', '電話'), ('domain', '官網域名'),
]

CONFIRMATION_TEMPLATE = """您好，{customer_name} 先生／小姐：

我們已收到您提交的 AICDN 免費試用申請，申請資訊如下：
公司名稱：{company_name}
申請網域：{service_domain}
申請時間：{application_submitted_at}（Asia/Taipei）

請您先至 AICDN Portal 完成「聯絡人資訊」與「身份驗證」，完成後將由專人與您聯繫，協助確認試用方案及後續啟用流程。

如有任何問題，歡迎透過以下方式聯繫我們：
AICDN 團隊
客服信箱：aicdn@skycloud.com.tw
LINE 官方帳號：https://line.me/ti/p/~@aicdn
加入好友：
"""


def _internal_notification_body(lead):
    lines = [f'{label}：{lead.get(field) or "—"}' for field, label in FIELD_LABELS]
    return '\n'.join(lines)


def _send(cfg, *, to_addr, subject, body):
    smtp_cfg = cfg.get('smtp') or {}
    host = smtp_cfg.get('host')
    user = smtp_cfg.get('user')
    password = smtp_cfg.get('password')
    if not (host and user and password):
        print('[mail] smtp not configured, skipping email')
        return

    port = smtp_cfg.get('port', 587)
    from_addr = smtp_cfg.get('from', user)

    msg = MIMEText(body, _charset='utf-8')
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = to_addr

    try:
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.starttls()
            s.login(user, password)
            s.sendmail(from_addr, [to_addr], msg.as_string())
    except Exception as e:
        print(f'[mail] failed to send email to {to_addr}: {e}')


def notify_new_lead(cfg, lead):
    """Internal alert to the AICDN team that a new form was submitted."""
    smtp_cfg = cfg.get('smtp') or {}
    to_addr = smtp_cfg.get('notify_to', NOTIFY_TO)
    subject = f'[AICDN] 新報名：{lead.get("company") or lead.get("name") or ""}'
    body = _internal_notification_body(lead)
    threading.Thread(target=_send, args=(cfg,),
                      kwargs=dict(to_addr=to_addr, subject=subject, body=body),
                      daemon=True).start()


def notify_applicant(cfg, lead):
    """Confirmation email sent back to the applicant themselves."""
    to_addr = lead.get('email')
    if not to_addr:
        return
    submitted_at = lead.get('createdAt') or datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    body = CONFIRMATION_TEMPLATE.format(
        customer_name=lead.get('name') or '',
        company_name=lead.get('company') or '',
        service_domain=lead.get('domain') or '',
        application_submitted_at=submitted_at,
    )
    subject = '【AICDN】已收到您的免費試用申請'
    threading.Thread(target=_send, args=(cfg,),
                      kwargs=dict(to_addr=to_addr, subject=subject, body=body),
                      daemon=True).start()


SELLER_CONFIRMATION_TEMPLATE = """您好，{customer_name} 先生／小姐：

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


def notify_seller_applicant(cfg, lead):
    """Confirmation email sent to the seller applicant after form submission."""
    to_addr = lead.get('email')
    if not to_addr:
        return
    body = SELLER_CONFIRMATION_TEMPLATE.format(
        customer_name=lead.get('name') or '',
    )
    subject = '【AICDN】已收到您的賣家登記，請完成分潤計畫啟用任務'
    threading.Thread(target=_send, args=(cfg,),
                      kwargs=dict(to_addr=to_addr, subject=subject, body=body),
                      daemon=True).start()
