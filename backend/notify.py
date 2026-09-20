import os
import requests
import logging
import threading

logger = logging.getLogger(__name__)

def send_telegram_notification(message):
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        return
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")

def send_discord_notification(message):
    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        return
        
    payload = {
        "content": message
    }
    try:
        requests.post(webhook_url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Failed to send Discord notification: {e}")

def notify_all(message):
    """Send notification to all configured integrations."""
    send_telegram_notification(message)
    send_discord_notification(message)


def notify_all_async(message):
    """Deliver notifications outside the request path; integration failures are isolated."""
    threading.Thread(target=notify_all, args=(message,), name='nigel-notify', daemon=True).start()
