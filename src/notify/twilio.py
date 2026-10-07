"""WhatsApp via Twilio (alternativa paga). Secrets: TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, WHATSAPP_PHONE."""
import os

import requests


def send(text: str) -> None:
    sid, token = os.environ["TWILIO_SID"], os.environ["TWILIO_TOKEN"]
    r = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        auth=(sid, token),
        data={"From": f"whatsapp:{os.environ['TWILIO_FROM']}",
              "To": f"whatsapp:{os.environ['WHATSAPP_PHONE']}", "Body": text},
        timeout=60,
    )
    r.raise_for_status()


PART_GAP = 2


def send_part(part: str) -> None:
    send(part)
