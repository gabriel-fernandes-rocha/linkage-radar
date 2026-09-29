"""WhatsApp grátis via CallMeBot (https://www.callmebot.com/blog/free-api-whatsapp-messages/).

Limite descoberto na prática: a URL inteira corta em ~1024 caracteres. Como emojis viram 12
caracteres (%F0%9F%93%A1) e acentos 6, o texto é dividido em partes pelo tamanho CODIFICADO.
"""
import os
import time
from urllib.parse import quote_plus

import requests

from common import log

MAX_ENCODED = 930  # medido: a URL inteira corta em ~1030; o resto é endereço + phone + apikey


def split(text: str, limit: int = MAX_ENCODED) -> list[str]:
    """Divide preferindo quebras de parágrafo (linha em branco); só quebra linhas se precisar."""
    if len(quote_plus(text)) <= limit:
        return [text]
    parts, cur = [], ""
    for para in text.split("\n\n"):
        cand = f"{cur}\n\n{para}" if cur else para
        if len(quote_plus(cand)) <= limit:
            cur = cand
            continue
        if cur:
            parts.append(cur)
        if len(quote_plus(para)) <= limit:
            cur = para
        else:
            sub = _split_lines(para, limit)
            parts += sub[:-1]
            cur = sub[-1]
    if cur:
        parts.append(cur)
    return parts


def _split_lines(text: str, limit: int) -> list[str]:
    parts, cur = [], ""
    for line in text.split("\n"):
        cand = f"{cur}\n{line}" if cur else line
        if len(quote_plus(cand)) <= limit:
            cur = cand
            continue
        if cur:
            parts.append(cur)
        while len(quote_plus(line)) > limit:  # linha sozinha grande demais: corta
            n = len(line)
            while len(quote_plus(line[:n])) > limit:
                n -= 10
            parts.append(line[:n])
            line = line[n:]
        cur = line
    if cur:
        parts.append(cur)
    return parts


def send(text: str) -> None:
    phone = os.environ["WHATSAPP_PHONE"]        # ex.: +557588493983 (como o CallMeBot registrou)
    apikey = os.environ["CALLMEBOT_APIKEY"]
    parts = split(text)
    for i, part in enumerate(parts, 1):
        r = requests.get(
            "https://api.callmebot.com/whatsapp.php",
            params={"phone": phone, "text": part, "apikey": apikey},
            timeout=60,
        )
        r.raise_for_status()
        answer = " ".join(r.text.split())[:200]
        log.info("callmebot parte %d/%d: %s", i, len(parts), answer)
        if "error" in r.text.lower() and "queued" not in r.text.lower():
            raise RuntimeError(f"CallMeBot respondeu: {answer}")
        if i < len(parts):
            time.sleep(8)  # o CallMeBot recusa mensagens em sequência muito rápida
