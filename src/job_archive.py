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
        "requisitos", "senioridade", "modalidade")


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


def _rank(jobs: list[dict]) -> dict:
    must, nice, any_ = Counter(), Counter(), Counter()
    for j in jobs:
        req = j.get("requisitos") or {}
        must.update(req.get("obrigatorios", []))
        nice.update(req.get("desejaveis", []))
        any_.update(set(req.get("obrigatorios", [])) | set(req.get("desejaveis", [])))
    n = sum(1 for j in jobs if j.get("requisitos"))
    rows = [{"nome": k, "vagas": c, "pct": round(100 * c / n) if n else 0,
             "obrigatorio": must[k], "desejavel": nice[k]} for k, c in any_.most_common(60)]
    return {"vagas_analisadas": n, "ranking": rows}


def write_skills(archive: list[dict], day: str) -> dict:
    since = (date.fromisoformat(day) - timedelta(days=90)).isoformat()
    stats = {
        "atualizado_em": day,
        "geral": _rank(archive),
        "ultimos_90_dias": _rank([j for j in archive if j.get("primeira_vez", "") >= since]),
        "senioridade": Counter(j.get("senioridade", "nao_informado") for j in archive).most_common(),
        "modalidade": Counter(j.get("modalidade", "nao_informado") for j in archive).most_common(),
    }
    SKILLS.write_text(json.dumps(stats, ensure_ascii=False, indent=1), "utf-8")
    return stats
