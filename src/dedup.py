"""Evita repetir itens já vistos: hash de URL + título normalizado em data/seen.json."""
from __future__ import annotations

import hashlib
import json
import re

from common import DATA
from filters.keywords import normalize

SEEN = DATA / "seen.json"


def _norm_url(url: str) -> str:
    url = re.sub(r"^https?://(www\.)?", "", url.strip().lower())
    return url.split("?")[0].split("#")[0].rstrip("/")


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize(title)).strip()


def keys(it: dict) -> list[str]:
    h = lambda s: hashlib.sha1(s.encode()).hexdigest()[:16]
    return [h("u:" + _norm_url(it["url"])), h(f"t:{it['tipo']}:" + _norm_title(it["titulo"]))]


class Seen:
    def __init__(self):
        self.data: dict[str, str] = json.loads(SEEN.read_text("utf-8")) if SEEN.exists() else {}

    def is_new(self, it: dict) -> bool:
        return not any(k in self.data for k in keys(it))

    def add(self, it: dict, day: str):
        for k in keys(it):
            self.data[k] = day

    def save(self):
        SEEN.write_text(json.dumps(self.data, indent=0, sort_keys=True), "utf-8")


def unique(items: list[dict]) -> list[dict]:
    """Remove duplicatas dentro da própria coleta do dia."""
    out, ks = [], set()
    for it in items:
        k = keys(it)
        if not ks.intersection(k):
            ks.update(k)
            out.append(it)
    return out
