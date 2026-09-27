"""Carteira de vagas abertas que combinam com o perfil (data/open_jobs.json).

- Toda vaga aprovada pelo juiz entra na carteira com a data em que apareceu.
- Todo dia cada vaga é revalidada:
    * fontes que listam TODAS as vagas abertas (Greenhouse, Lever, Ashby, Remotive, RemoteOK):
      continua aberta se ainda estiver na listagem de hoje;
    * demais fontes (Google Jobs, Adzuna, HN, LinkedIn): checagem do link
      (404/410 ou aviso de "vaga encerrada" = fechada);
    * nada fica na carteira além de `open_jobs.max_age_days`.
"""
from __future__ import annotations

import json
import re
from datetime import date

import requests

from common import DATA, UA, log
from dedup import _norm_url

PATH = DATA / "open_jobs.json"
FULL_LISTING = ("Greenhouse/", "Lever/", "Ashby/", "Remotive", "RemoteOK")
CLOSED_PATTERNS = re.compile(
    r"no longer accepting applications|job (is )?(no longer|not) available|this job has expired|"
    r"position (has been )?(filled|closed)|vaga (encerrada|expirada|não está mais disponível)",
    re.I,
)


def load() -> list[dict]:
    return json.loads(PATH.read_text("utf-8")) if PATH.exists() else []


def save(jobs: list[dict]) -> None:
    PATH.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), "utf-8")


def _link_alive(url: str) -> bool:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20, allow_redirects=True)
    except requests.RequestException:
        return True  # erro de rede não fecha a vaga; tenta de novo amanhã
    if r.status_code in (404, 410):
        return False
    return not CLOSED_PATTERNS.search(r.text[:300_000])


def still_open(job: dict, listed_today: set[str]) -> bool:
    if job.get("fonte", "").startswith(FULL_LISTING):
        return _norm_url(job["url"]) in listed_today
    return _link_alive(job["url"])


def update(new_jobs: list[dict], raw_jobs: list[dict], day: str, max_age_days: int) -> list[dict]:
    """Adiciona as novas, revalida as antigas e devolve a carteira ordenada (novas primeiro)."""
    listed_today = {_norm_url(j["url"]) for j in raw_jobs}
    current = load()
    known = {_norm_url(j["url"]) for j in current}
    kept = []
    for job in current:
        age = (date.fromisoformat(day) - date.fromisoformat(job["desde"])).days
        if age > max_age_days:
            log.info("open_jobs: expirou (%dd) %s", age, job["titulo"])
        elif still_open(job, listed_today):
            job["nova"] = job["desde"] == day
            job["verificada_em"] = day
            kept.append(job)
        else:
            log.info("open_jobs: fechou %s", job["titulo"])
    for job in new_jobs:
        if _norm_url(job["url"]) in known:
            continue
        job = {k: v for k, v in job.items() if k != "texto"}
        job.update(desde=day, verificada_em=day, nova=True)
        kept.append(job)
    kept.sort(key=lambda j: (j["nova"], j.get("encaixe", 0), j["desde"]), reverse=True)
    save(kept)
    log.info("open_jobs: %d abertas (%d novas)", len(kept), sum(j["nova"] for j in kept))
    return kept
