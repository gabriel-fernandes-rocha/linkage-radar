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
    # título SOZINHO não identifica vaga: "Cientista de Dados Pleno" existe em dezenas de empresas.
    # Para vagas, a 2ª chave é título + empresa (sem empresa conhecida, só a URL vale).
    if it.get("tipo") == "vaga":
        company = _norm_title(it.get("empresa") or "")
        return [h("u:" + _norm_url(it["url"]))] + ([h(f"t:vaga:{_norm_title(it['titulo'])}|{company}")] if company else [])
    return [h("u:" + _norm_url(it["url"])), h(f"t:{it['tipo']}:" + _norm_title(it["titulo"]))]


class Seen:
    def __init__(self, path=None):
        self.path = path or SEEN  # a trilha de fraude tem o seu próprio histórico (data/fraude/seen.json)
        self.data: dict[str, str] = json.loads(self.path.read_text("utf-8")) if self.path.exists() else {}

    def is_new(self, it: dict) -> bool:
        return not any(k in self.data for k in keys(it))

    def add(self, it: dict, day: str):
        for k in keys(it):
            self.data[k] = day

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=0, sort_keys=True), "utf-8")


def unique(items: list[dict]) -> list[dict]:
    """Remove duplicatas dentro da própria coleta do dia."""
    out, ks = [], set()
    for it in items:
        k = keys(it)
        if not ks.intersection(k):
            ks.update(k)
            out.append(it)
    return out
