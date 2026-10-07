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

MAX_ENCODED = 930  # medido: a URL inteira corta em ~1030; o resto é endereço + phone + apikey


def _enc(text: str) -> int:
    return len(quote_plus(text))


def _tokens(text: str, limit: int) -> list[tuple[str, str]]:
    """(separador, pedaço): frases de um mesmo parágrafo se juntam com espaço, linhas com quebra."""
    out = []
    for line in text.split("\n"):
        sents = re.split(r"(?<=[.!?;:])\s+", line) if line else [""]
        for j, sent in enumerate(sents):
            sep = "\n" if j == 0 else " "
            while _enc(sent) > limit:  # frase gigante (ex.: URL): corta no tamanho
                n = len(sent)
                while _enc(sent[:n]) > limit:
                    n -= 20
                out.append((sep, sent[:n]))
                sent, sep = sent[n:], " "
            out.append((sep, sent))
    return out


def _join(tokens: list[tuple[str, str]]) -> str:
    return "".join(sep + txt for sep, txt in tokens)[1:] if tokens else ""


def split(text: str, limit: int = MAX_ENCODED) -> list[str]:
    """Enche cada parte ao máximo. Ao cortar, prefere o fim de uma seção (linha em branco) ou de um
    parágrafo, desde que a parte já esteja ao menos 75% cheia; senão corta entre frases."""
    if _enc(text) <= limit:
        return [text]
    parts, cur = [], []
    for tok in _tokens(text, limit):
        if _enc(_join(cur + [tok])) <= limit:
            cur.append(tok)
            continue
        cut = None
        for prefer in (lambda i: cur[i] == ("\n", ""), lambda i: cur[i][0] == "\n"):
            cut = next((i for i in range(len(cur) - 1, 0, -1)
                        if prefer(i) and _enc(_join(cur[:i])) >= 0.75 * limit), None)
            if cut is not None:
                break
        if cut is None:
            parts.append(_join(cur))
            cur = [("\n", tok[1])]
        else:
            parts.append(_join(cur[:cut]))
            rest = cur[cut:] + [tok]
            while len(rest) > 1 and rest[0] == ("\n", ""):  # só as linhas em branco do início
                rest = rest[1:]
            cur = [("\n", rest[0][1])] + rest[1:]
            while _enc(_join(cur)) > limit:
                parts.append(_join(cur[:-1]))
                cur = [("\n", cur[-1][1])]
    if cur:
        parts.append(_join(cur))
    return [x.strip("\n") for x in parts if x.strip()]


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
