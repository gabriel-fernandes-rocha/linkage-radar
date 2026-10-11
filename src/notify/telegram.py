"""Telegram (grátis, sem limite de mensagens). Secrets: TELEGRAM_TOKEN e TELEGRAM_CHAT_ID.

Crie o bot no @BotFather, mande /start para ele e rode scripts/telegram_chat_id.py para descobrir o chat id.
"""
import os
import time

import requests

from common import log
from notify import textsplit

LIMIT = 4000        # o Telegram aceita 4096 caracteres por mensagem
PART_GAP = 1
RETRIES = (10, 30, 90)


def split(text: str, limit: int = LIMIT) -> list[str]:
    return textsplit.split(text, limit, len)


def fits(text: str) -> bool:
    return len(text) <= LIMIT


def send_part(part: str) -> None:
    token, chat = os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    last = ""
    for attempt, wait in enumerate((0, *RETRIES)):
        if wait:
            log.warning("telegram: tentativa %d em %ds (último erro: %s)", attempt + 1, wait, last)
            time.sleep(wait)
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=60,
                              json={"chat_id": chat, "text": part, "disable_web_page_preview": True})
            data = r.json()
            if data.get("ok"):
                return
            last = str(data.get("description", r.text))[:300]
            retry_after = (data.get("parameters") or {}).get("retry_after")
            if retry_after:
                time.sleep(int(retry_after))
        except (requests.RequestException, ValueError) as e:
            last = f"{type(e).__name__}: {e}"
    raise RuntimeError(f"Telegram falhou após {len(RETRIES) + 1} tentativas: {last}")


def send(text: str) -> None:
    for i, part in enumerate(split(text)):
        if i:
            time.sleep(PART_GAP)
        send_part(part)
