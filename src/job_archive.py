"""Arquivo permanente de TODAS as vagas aprovadas (abertas e fechadas) + frequência de requisitos.

data/jobs_archive.json  → uma entrada por vaga (nunca é apagada; guarda quando fechou)
data/skills.json        → ranking do que o mercado pede nos requisitos (geral e últimos 90 dias)
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta

from common import DATA
from dedup import _norm_url

ARCHIVE = DATA / "jobs_archive.json"
SKILLS = DATA / "skills.json"
KEEP = ("titulo", "empresa", "local", "url", "fonte", "encaixe", "nota_perfil", "motivo", "resumo",
        "requisitos", "senioridade", "modalidade", "publicada_em", "juiz")


def load() -> list[dict]:
    return json.loads(ARCHIVE.read_text("utf-8")) if ARCHIVE.exists() else []


def update(new_jobs: list[dict], open_now: list[dict], day: str) -> list[dict]:
    archive = load()
    by_url = {_norm_url(j["url"]): j for j in archive}
    for job in new_jobs:
        key = _norm_url(job["url"])
        if key not in by_url:
            entry = {k: job.get(k) for k in KEEP if job.get(k) is not None}
            entry["primeira_vez"] = day
            archive.append(entry)
            by_url[key] = entry
    open_keys = {_norm_url(j["url"]) for j in open_now}
    for key, entry in by_url.items():
        if key in open_keys:
            entry["status"], entry["ultima_vez_aberta"] = "aberta", day
            entry.pop("fechada_em", None)
        elif entry.get("status") != "fechada":
            entry["status"], entry["fechada_em"] = "fechada", day
    ARCHIVE.write_text(json.dumps(archive, ensure_ascii=False, indent=1), "utf-8")
    write_skills(archive, day)
    return archive


def write_skills(archive: list[dict], day: str) -> dict:
    import market

    return market.write(archive, day)
