"""Utilidades compartilhadas: config, caminhos, HTTP, datas."""
from __future__ import annotations

import html
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CURRICULUM = ROOT / "curriculum"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("radar")

UA = "Mozilla/5.0 (LinkageRadar; +https://github.com/) Python-requests"
TIMEOUT = 20


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def today(cfg: dict | None = None) -> datetime:
    tz = ZoneInfo((cfg or {}).get("timezone", "America/Sao_Paulo"))
    return datetime.now(tz)


def get(url: str, retries: int = 3, **kw) -> requests.Response:
    """GET com novas tentativas (espera crescente) quando a API pede calma (429) ou oscila (5xx)."""
    headers = {"User-Agent": UA, **kw.pop("headers", {})}
    timeout = kw.pop("timeout", TIMEOUT)
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=headers, timeout=timeout, **kw)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == retries:
                raise
        else:
            if r.status_code != 429 and r.status_code < 500 or attempt == retries:
                r.raise_for_status()
                return r
            wait = r.headers.get("Retry-After", "")
        time.sleep(int(wait) if wait.isdigit() and int(wait) <= 60 else 5 * 3 ** attempt)
    raise RuntimeError("inalcançável")


def clean(text: str | None, limit: int = 1500) -> str:
    """Remove HTML e espaços extras; corta no limite (economiza tokens do LLM)."""
    if not text:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def no_dash(text: str) -> str:
    """Remove travessões (— e –), que deixam o texto com cara de gerado por IA."""
    if not text:
        return text
    text = re.sub(r"\s*[—–]\s*(?=\d)", "-", text)          # intervalos: 40k–50k -> 40k-50k
    text = re.sub(r"\s+[—–]\s+", ", ", text)               # "A — B" -> "A, B"
    text = re.sub(r"[—–]", "-", text)
    return re.sub(r",\s*,", ",", text)


TRACKING = re.compile(r"^(utm_\w+|gclid|fbclid|trk\w*|ref|refId|trackingId|src)$", re.I)


def clean_url(url: str) -> str:
    """Remove parâmetros de rastreamento (utm_*, trk...) — URLs mais curtas no WhatsApp."""
    parts = urlsplit(url or "")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING.match(k)]
    return urlunsplit(parts._replace(query=urlencode(query)))


def item(kind: str, title: str, url: str, **extra) -> dict:
    return {"tipo": kind, "titulo": clean(title, 300), "url": clean_url(url), **extra}
