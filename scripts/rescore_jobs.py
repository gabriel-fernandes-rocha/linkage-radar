"""Recalcula requisitos e compatibilidade das vagas já salvas (open_jobs + arquivo), relendo cada página.

Uso: python scripts/rescore_jobs.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import compat  # noqa: E402
import job_archive  # noqa: E402
import open_jobs  # noqa: E402
import requests  # noqa: E402
from common import UA, clean, load_config, log  # noqa: E402
from dedup import _norm_url  # noqa: E402
from filters import requirements  # noqa: E402


CLOSED = set()


def fetch_text(url: str) -> str:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
    except requests.RequestException as e:
        log.warning("não consegui reler %s (%s)", url[:70], e)
        return ""
    if r.status_code in (404, 410) or open_jobs.CLOSED_PATTERNS.search(r.text[:300_000]):
        CLOSED.add(_norm_url(url))  # vaga encerrada
        return ""
    return clean(r.text, 8000) if r.ok else ""


def main():
    cfg = load_config()
    jobs = open_jobs.load()
    archive = job_archive.load()
    by_url = {_norm_url(j["url"]): j for j in archive}
    for j in jobs:
        by_url.setdefault(_norm_url(j["url"]), j)
    allj = list(by_url.values())
    for j in allj:
        j["texto"] = fetch_text(j["url"]) or f"{j['titulo']}. {j.get('resumo', '')} {j.get('motivo', '')}"
    requirements.extract(allj, cfg)
    compat.score_jobs(allj, cfg)
    for j in allj:
        j.pop("texto", None)
    fresh = {_norm_url(j["url"]): j for j in allj}
    for coll in (jobs, archive):
        for j in coll:
            j.update({k: v for k, v in fresh[_norm_url(j["url"])].items() if k not in ("desde", "nova")})
    for j in jobs:
        if _norm_url(j["url"]) in CLOSED:
            print("fechou:", j["titulo"][:60])
    jobs = [j for j in jobs if _norm_url(j["url"]) not in CLOSED]
    for j in archive:
        if _norm_url(j["url"]) in CLOSED:
            j["status"], j["fechada_em"] = "fechada", date.today().isoformat()
    jobs.sort(key=lambda j: j.get("encaixe", 0), reverse=True)
    open_jobs.save(jobs)
    job_archive.ARCHIVE.write_text(json.dumps(archive, ensure_ascii=False, indent=1), "utf-8")
    job_archive.write_skills(archive, date.today().isoformat())
    for j in jobs:
        d = j.get("compat_detalhe", {})
        print(f"{round(j.get('encaixe', 0) * 100):3}% | {j['titulo'][:45]:45} | {d.get('local_txt', '')[:45]:45} | "
              f"hab {d.get('habilidades')}% sen {d.get('senioridade')}%")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
