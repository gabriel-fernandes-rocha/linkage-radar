"""Aplica os níveis de fluência marcados na aba "Minhas ferramentas" do site e recalcula as compatibilidades.

Chamado pelo workflow .github/workflows/niveis.yml quando VOCÊ (dono do repositório) abre a issue
"niveis: ..." que o botão "Salvar no radar" do site prepara. Também roda localmente:
    python scripts/aplicar_niveis.py arquivo.json      # {"AWS": "parcial", "Spark": "tem", ...}
    python scripts/aplicar_niveis.py                   # só recalcula

Níveis: "tem" (fluente), "parcial" (básico), "nao" (não sei). "auto" = remove a marcação (vale o veredito da IA).
Não chama IA nenhuma: só refaz a conta com os níveis novos.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import compat  # noqa: E402
import job_archive  # noqa: E402
import open_jobs  # noqa: E402
from common import DATA, load_config, log  # noqa: E402

VALID = {"tem", "parcial", "nao", "auto"}


def parse(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S) or re.search(r"(\{.*\})", text, re.S)
    if not m:
        raise ValueError("não achei o JSON com os níveis")
    data = json.loads(m.group(1))
    if not isinstance(data, dict):
        raise ValueError("formato inválido")
    out = {}
    for k, v in data.items():
        name = re.sub(r"\s+", " ", str(k)).strip()[:60]
        if name and v in VALID:
            out[name] = v
    return out


def save_levels(new: dict) -> dict:
    """O site manda o conjunto COMPLETO das suas marcações; "auto" remove."""
    levels = {k: v for k, v in sorted(new.items(), key=lambda kv: kv[0].lower()) if v != "auto"}
    compat.NIVEIS.parent.mkdir(parents=True, exist_ok=True)
    compat.NIVEIS.write_text(json.dumps(levels, ensure_ascii=False, indent=1), "utf-8")
    log.info("níveis: %d habilidades marcadas por você", len(levels))
    return levels


def recompute() -> None:
    cfg = load_config()
    cache = compat._load_cache()  # vereditos da IA + seus níveis por cima
    day = date.today().isoformat()
    for jobs_path, archive_path, skills_path in (
            (open_jobs.PATH, job_archive.ARCHIVE, job_archive.SKILLS),
            (DATA / "brasil" / "open_jobs.json", DATA / "brasil" / "archive.json", DATA / "brasil" / "skills.json")):
        if not jobs_path.exists():
            continue
        jobs = open_jobs.load(jobs_path)
        for j in jobs:
            if j.get("requisitos"):
                compat.score(j, cfg, cache)
        jobs.sort(key=lambda j: j.get("encaixe", 0), reverse=True)
        open_jobs.save(jobs, jobs_path)
        if archive_path.exists():
            job_archive.write_skills(job_archive.load(archive_path), day, skills_path)
        log.info("níveis: %d vagas recalculadas em %s", len(jobs), jobs_path.relative_to(ROOT))


if __name__ == "__main__":
    body = os.environ.get("ISSUE_BODY")
    if body is None and len(sys.argv) > 1:
        body = Path(sys.argv[1]).read_text("utf-8")
    if body:
        save_levels(parse(body))
    recompute()
