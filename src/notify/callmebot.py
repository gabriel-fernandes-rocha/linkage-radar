"""WhatsApp grátis via CallMeBot (https://www.callmebot.com/blog/free-api-whatsapp-messages/).

Limite descoberto na prática: a URL inteira corta em ~1024 caracteres. Como emojis viram 12
caracteres (%F0%9F%93%A1) e acentos 6, o texto é dividido em partes pelo tamanho CODIFICADO.
O CallMeBot só aceita GET (testado: POST é recusado), então não há como fugir desse limite.
"""
import os
import re
import time
from urllib.parse import quote_plus

import requests

from common import log
from notify import textsplit

MAX_ENCODED = 930  # medido: a URL inteira corta em ~1030; o resto é endereço + phone + apikey


def _enc(text: str) -> int:
    return len(quote_plus(text))


def split(text: str, limit: int = MAX_ENCODED) -> list[str]:
    return textsplit.split(text, limit, _enc)


PART_GAP = 15          # segundos entre partes (o CallMeBot limita mensagens em sequência)
RETRIES = (30, 90, 180)  # esperas antes de cada nova tentativa da MESMA parte


def send_part(part: str) -> None:
    """Envia UMA parte, com novas tentativas. Só levanta erro se todas falharem."""
    phone = os.environ["WHATSAPP_PHONE"]        # ex.: +557588493983 (como o CallMeBot registrou)
    apikey = os.environ["CALLMEBOT_APIKEY"]
    last = ""
    for attempt, wait in enumerate((0, *RETRIES)):
        if wait:
            log.warning("callmebot: tentativa %d em %ds (último erro: %s)", attempt + 1, wait, last)
            time.sleep(wait)
        try:
            r = requests.get("https://api.callmebot.com/whatsapp.php",
                             params={"phone": phone, "text": part, "apikey": apikey}, timeout=90)
            answer = " ".join(r.text.split())[:300]
            # sucesso = o CallMeBot confirma a fila ("Message queued"). Não procuramos "error" no texto,
            # porque a resposta repete a mensagem enviada (uma aula sobre "type I error" virava falso erro).
            low = r.text.lower()
            ok = r.status_code < 400 and ("message queued" in low or "message sent" in low)
            if not ok:
                answer = " ".join(r.text.split())[-300:]  # o motivo fica no fim da resposta
        except requests.RequestException as e:
            ok, answer = False, f"{type(e).__name__}: {e}"
        if ok:
            log.info("callmebot ok: %s", answer[:120])
            return
        last = answer
    raise RuntimeError(f"CallMeBot falhou após {len(RETRIES) + 1} tentativas: {last}")


def send(text: str) -> None:
    parts = split(text)
    for i, part in enumerate(parts):
        send_part(part)
        if i + 1 < len(parts):
            time.sleep(PART_GAP)
