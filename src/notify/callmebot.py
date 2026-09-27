"""WhatsApp grátis via CallMeBot (https://www.callmebot.com/blog/free-api-whatsapp-messages/)."""
import os

import requests


def send(text: str) -> None:
    phone = os.environ["WHATSAPP_PHONE"]        # ex.: +5575999999999
    apikey = os.environ["CALLMEBOT_APIKEY"]
    r = requests.get(
        "https://api.callmebot.com/whatsapp.php",
        params={"phone": phone, "text": text, "apikey": apikey},
        timeout=60,
    )
    r.raise_for_status()
    if "error" in r.text.lower() and "queued" not in r.text.lower():
        raise RuntimeError(f"CallMeBot respondeu: {r.text[:300]}")
