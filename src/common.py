"""Utilidades compartilhadas: config, caminhos, HTTP, datas."""
from __future__ import annotations

import html
import logging
import os
import re
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


def get(url: str, **kw) -> requests.Response:
    headers = {"User-Agent": UA, **kw.pop("headers", {})}
    r = requests.get(url, headers=headers, timeout=kw.pop("timeout", TIMEOUT), **kw)
    r.raise_for_status()
    return r


def clean(text: str | None, limit: int = 1500) -> str:
    """Remove HTML e espaços extras; corta no limite (economiza tokens do LLM)."""
    if not text:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


TRACKING = re.compile(r"^(utm_\w+|gclid|fbclid|trk\w*|ref|refId|trackingId|src)$", re.I)


def clean_url(url: str) -> str:
    """Remove parâmetros de rastreamento (utm_*, trk...) — URLs mais curtas no WhatsApp."""
    parts = urlsplit(url or "")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING.match(k)]
    return urlunsplit(parts._replace(query=urlencode(query)))


def item(kind: str, title: str, url: str, **extra) -> dict:
    return {"tipo": kind, "titulo": clean(title, 300), "url": clean_url(url), **extra}
