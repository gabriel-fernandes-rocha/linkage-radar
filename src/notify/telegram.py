"""Telegram (grátis, sem limite de mensagens). Secrets: TELEGRAM_TOKEN e TELEGRAM_CHAT_ID.

Crie o bot no @BotFather, mande /start para ele e rode scripts/telegram_chat_id.py para descobrir o chat id.
"""
import html
import os
import re
import time

import requests

from common import log
from notify import textsplit

LIMIT = 3800        # o Telegram aceita 4096 caracteres por mensagem (folga para as tags HTML)
FORMAT = "html"
PART_GAP = 1
RETRIES = (10, 30, 90)


TAG = re.compile(r"<(/?)([a-zA-Z-]+)([^<>]*)>")
HTML_TAGS = {"b", "strong", "i", "em", "u", "s", "code", "pre", "a", "tg-spoiler", "blockquote"}


def balance(parts: list[str]) -> list[str]:
    """Tag aberta numa parte é fechada no fim dela e reaberta na seguinte (o Telegram recusa HTML desbalanceado)."""
    out, carry = [], []
    for part in parts:
        stack = list(carry)
        for m in TAG.finditer(part):
            name = m[2].lower()
            if name not in HTML_TAGS:
                continue
            if not m[1]:
                stack.append((name, m[0]))
                continue
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    del stack[i]
                    break
        out.append("".join(t for _, t in carry) + part + "".join(f"</{n}>" for n, _ in reversed(stack)))
        carry = stack
    return out


def split(text: str, limit: int = LIMIT) -> list[str]:
    return balance(textsplit.split(text, limit, len))


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
            body = {"chat_id": chat, "text": part, "parse_mode": "HTML", "disable_web_page_preview": True}
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=60, json=body)
            data = r.json()
            if not data.get("ok") and "parse" in str(data.get("description", "")).lower():
                # formatação quebrada (ex.: bloco de código cortado entre partes): manda como texto simples
                log.warning("telegram: HTML recusado (%s); reenviando sem formatação", data.get("description"))
                plain = html.unescape(re.sub(r"<[^>]+>", "", part))
                r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=60,
                                  json={"chat_id": chat, "text": plain, "disable_web_page_preview": True})
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
