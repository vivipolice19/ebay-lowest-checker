import requests

from config import DISCORD_WEBHOOK_URL, LINE_NOTIFY_TOKEN, REQUEST_TIMEOUT_SECONDS


def send_alert(message: str):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(
                DISCORD_WEBHOOK_URL,
                json={"content": message},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception:
            pass

    if LINE_NOTIFY_TOKEN:
        try:
            requests.post(
                "https://notify-api.line.me/api/notify",
                headers={"Authorization": f"Bearer {LINE_NOTIFY_TOKEN}"},
                data={"message": message},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception:
            pass
