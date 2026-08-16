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

我們已收到您提交的 AICDN 免費試用申請。

申請資訊如下：
公司名稱：{company_name}
申請網域：{service_domain}
申請時間：{application_submitted_at}（Asia/Taipei）

AICDN 團隊將由專人與您聯繫，協助確認試用方案及後續啟用流程。目前您不需要進行其他操作。

若以上資料有誤，請直接回覆本信或聯繫 AICDN 服務窗口。

AICDN 團隊｜客服信箱：aicdn@skycloud.com.tw｜客服專線：0988-002-964
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
