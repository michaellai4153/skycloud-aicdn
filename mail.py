"""Outbound notification email (new lead alerts) via SMTP."""
import smtplib
import threading
from email.mime.text import MIMEText

NOTIFY_TO = 'aicdn@skycloud.com.tw'

FIELD_LABELS = [
    ('name', '姓名'), ('title', '職稱'), ('company', '公司'),
    ('email', 'Email'), ('phone', '電話'), ('domain', '官網域名'),
]


def _build_body(lead):
    lines = [f'{label}：{lead.get(field) or "—"}' for field, label in FIELD_LABELS]
    return '\n'.join(lines)


def _send(cfg, lead):
    smtp_cfg = cfg.get('smtp') or {}
    host = smtp_cfg.get('host')
    user = smtp_cfg.get('user')
    password = smtp_cfg.get('password')
    if not (host and user and password):
        print('[mail] smtp not configured, skipping lead notification')
        return

    port = smtp_cfg.get('port', 587)
    to_addr = smtp_cfg.get('notify_to', NOTIFY_TO)

    msg = MIMEText(_build_body(lead), _charset='utf-8')
    msg['Subject'] = f'[AICDN] 新報名：{lead.get("company") or lead.get("name") or ""}'
    msg['From'] = user
    msg['To'] = to_addr

    try:
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.starttls()
            s.login(user, password)
            s.sendmail(user, [to_addr], msg.as_string())
    except Exception as e:
        print(f'[mail] failed to send lead notification: {e}')


def notify_new_lead(cfg, lead):
    """Fire-and-forget: send in a background thread so form submission never blocks on SMTP."""
    threading.Thread(target=_send, args=(cfg, lead), daemon=True).start()
