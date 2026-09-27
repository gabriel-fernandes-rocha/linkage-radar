"""Etapa 1 — score barato por palavras-chave. Elimina o grosso antes do LLM."""
from __future__ import annotations

import re
import unicodedata

STRONG = [  # +3
    "record linkage", "entity resolution", "entity matching", "probabilistic linkage",
    "fellegi-sunter", "fellegi sunter", "data linkage", "record deduplication", "deduplication of records",
    "duplicate detection", "address matching", "geocoding matching", "identity resolution",
    "privacy-preserving record linkage", "pprl", "linkage de dados", "linkage de registros",
    "pareamento de registros", "pareamento de bases", "resolucao de entidades", "vinculacao de registros",
    "relacionamento de bases", "address parsing", "geocodificacao de enderecos", "entity linking",
]
MEDIUM = [  # +1
    "fuzzy matching", "string similarity", "master data", "mdm", "geocoding", "geocodificacao",
    "splink", "dedupe", "zingg", "senzing", "jaro-winkler", "levenshtein", "blocking", "deduplication",
    "libpostal", "gazetteer", "matching", "linkage", "golden record", "data quality",
]
NEGATIVE = [  # -3
    "data entry", "sales", "account executive", "digitador", "vendas", "call center",
]

# Mesma lista que o spec: "data engineer" genérico e "GIS technician" sem matching são penalizados
GENERIC_ROLES = ["data engineer", "gis technician", "gis analyst", "engenheiro de dados"]

THRESHOLD = 3
THRESHOLD_SEARCH = 1  # itens de busca web (LinkedIn/eventos) já vêm pré-filtrados pela consulta


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _has(term: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


def score(it: dict) -> int:
    text = normalize(f"{it.get('titulo', '')} {it.get('texto', '')}")
    strong = sum(3 for t in STRONG if _has(t, text))
    medium = sum(1 for t in MEDIUM if _has(t, text))
    negative = sum(-3 for t in NEGATIVE if _has(t, text))
    s = strong + medium + negative
    title = normalize(it.get("titulo", ""))
    if strong == 0 and any(_has(r, title) for r in GENERIC_ROLES):
        s -= 3
    return s


def _strong_hits(text: str) -> int:
    """Total de ocorrências de termos fortes (não só termos distintos)."""
    return sum(len(re.findall(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", text)) for t in STRONG)


def central(it: dict) -> bool:
    """O tema é central (no título ou repetido no texto) e não só citado de passagem?

    Evita o falso positivo mais comum: empresa de MDM/ER cuja descrição padrão
    ("Somos líderes em entity resolution...") aparece em TODAS as vagas, inclusive de SRE/vendas.
    """
    if _strong_hits(normalize(it.get("titulo", ""))) > 0:
        return True
    return _strong_hits(normalize(it.get("texto", ""))) >= 2


def passes(it: dict) -> bool:
    it["score"] = score(it)
    if it.get("tipo") in ("linkedin", "evento"):
        return it["score"] >= THRESHOLD_SEARCH
    return it["score"] >= THRESHOLD and central(it)
