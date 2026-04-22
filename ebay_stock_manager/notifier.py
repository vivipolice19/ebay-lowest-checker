import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from logger import log_info, log_error
from config import (
    LINE_NOTIFY_TOKEN, LINE_NOTIFY_URL,
    EMAIL_ALERTS, ALERT_EMAIL,
    SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD
)

def send_line_notify(message, token=None):
    token = token or LINE_NOTIFY_TOKEN
    if not token:
        log_error("LINE Notifyトークンが未設定です")
        return False

    try:
        data = urlencode({"message": message}).encode("utf-8")
        req = Request(
            LINE_NOTIFY_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )
        with urlopen(req, timeout=15) as response:
            result = json.loads(response.read().decode())
            if result.get("status") == 200:
                log_info("LINE通知送信成功")
                return True
            else:
                log_error(f"LINE通知エラー: {result}")
                return False
    except Exception as e:
        log_error(f"LINE通知送信エラー: {e}")
        return False

def send_email_alert(subject, body, to_email=None, smtp_server=None, smtp_port=None,
                     smtp_user=None, smtp_password=None):
    to_email = to_email or ALERT_EMAIL
    smtp_server = smtp_server or SMTP_SERVER
    smtp_port = smtp_port or SMTP_PORT
    smtp_user = smtp_user or SMTP_USER
    smtp_password = smtp_password or SMTP_PASSWORD

    if not all([to_email, smtp_server, smtp_user, smtp_password]):
        log_error("メール設定が不完全です")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        log_info(f"メール通知送信成功: {to_email}")
        return True
    except Exception as e:
        log_error(f"メール送信エラー: {e}")
        return False

def format_profit_alert(alerts):
    if not alerts:
        return ""

    lines = ["\n[在庫同期ツール] 利益アラート\n"]
    for alert in alerts:
        status_label = "危険" if alert["alert_status"] == "danger" else "警告"
        lines.append(
            f"[{status_label}] ID:{alert['id']} "
            f"利益率:{alert['profit_rate']:.1f}% "
            f"利益:{alert['profit_jpy']:.0f}円"
        )
    lines.append(f"\nアラート商品数: {len(alerts)}件")
    return "\n".join(lines)

def send_profit_alerts(alerts, line_token=None):
    if not alerts:
        return

    message = format_profit_alert(alerts)

    if line_token or LINE_NOTIFY_TOKEN:
        send_line_notify(message, token=line_token)

    if EMAIL_ALERTS and ALERT_EMAIL:
        send_email_alert(
            subject="[在庫同期ツール] 利益アラート",
            body=message
        )
