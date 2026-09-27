"""Coleta noturna: busca → filtro por palavras-chave → dedup → LLM juiz → data/YYYY-MM-DD.json.

Uso:
    python src/main_collect.py              # coleta real
    python src/main_collect.py --no-llm     # sem LLM (só palavras-chave; útil para testar)
    python src/main_collect.py --varredura-completa   # busca vagas com TODOS os termos (~22 buscas SerpAPI)
"""
from __future__ import annotations

import argparse
import json
from datetime import timedelta

import lesson
import open_jobs
from common import DATA, load_config, log, today
from dedup import Seen, unique
from filters import keywords, llm_judge
from sources import events, jobs, linkedin, papers

SECTIONS = [  # (chave no JSON, módulo, limite em config.limits)
    ("vagas", jobs, "max_jobs"),
    ("eventos", events, "max_events"),
    ("papers", papers, "max_papers"),
    ("linkedin", linkedin, "max_linkedin"),
]


def run(use_llm: bool = True, full_scan: bool = False) -> dict:
    cfg = load_config()
    if full_scan:
        s = cfg.setdefault("serpapi", {})
        s["jobs_searches_per_day"] = len(cfg["queries"]["jobs"]) * s.get("jobs_pages_per_term", 2)
    now = today(cfg)
    # Coleta às 23h prepara a edição do dia seguinte (a que chega às 6h)
    edition = (now + timedelta(days=1)) if now.hour >= 18 else now
    day = edition.strftime("%Y-%m-%d")
    seen = Seen()
    use_llm = use_llm and llm_judge.available(cfg)
    if not use_llm:
        log.warning("LLM desativado (sem chave ou --no-llm): usando só palavras-chave — menos preciso")

    report = {"data": day, "gerado_em": now.isoformat(timespec="minutes"), "llm": use_llm}
    budget = cfg["llm"].get("max_items_per_day", 80)
    stats = {}
    approved_all: dict[str, list[dict]] = {}
    raw_jobs: list[dict] = []
    bootstrap = not open_jobs.PATH.exists()  # 1ª vez: rejulga vagas já vistas para montar a carteira

    for key, module, limit_key in SECTIONS:
        raw = module.collect(cfg)
        if key == "vagas":
            raw_jobs = raw
        cands = [it for it in unique(raw)
                 if (seen.is_new(it) or (bootstrap and key == "vagas")) and keywords.passes(it)]
        cands.sort(key=lambda it: it["score"], reverse=True)
        cands = cands[:max(budget, 0)]
        budget -= len(cands)
        if use_llm:
            approved = llm_judge.judge(cands, cfg)
            approved.sort(key=lambda it: (it.get("encaixe", 0), it.get("confianca", 0), it["score"]), reverse=True)
            for it in cands:  # julgados (aprovados ou não) não são julgados de novo
                seen.add(it, day)
        else:
            approved = cands
        if key == "linkedin":  # vaga divulgada no LinkedIn também é vaga
            posted_jobs = [it for it in approved if "/jobs/view/" in it["url"]]
            approved = [it for it in approved if it not in posted_jobs]
            for it in posted_jobs:
                it["tipo"], it["fonte"] = "vaga", "LinkedIn Jobs"
            approved_all["vagas"] += posted_jobs
            report["vagas"] = (report["vagas"] + posted_jobs)[: cfg["limits"]["max_jobs"]]
        approved_all[key] = list(approved)
        final = approved[: cfg["limits"][limit_key]]
        for it in final:
            it.pop("texto", None)  # não precisamos guardar o texto bruto
        report[key] = final
        stats[key] = {"brutos": len(raw), "pos_palavras_chave": len(cands), "aprovados": len(final)}
        log.info("%s: %s", key, stats[key])

    if use_llm:
        max_age = cfg.get("open_jobs", {}).get("max_age_days", 60)
        abertas = open_jobs.update(approved_all.get("vagas", []), raw_jobs, day, max_age)
    else:
        abertas = open_jobs.load()
    report["vagas_abertas_total"] = len(abertas)

    report["aula"] = lesson.for_date(cfg, edition.date())
    report["estatisticas"] = stats

    DATA.mkdir(exist_ok=True)
    out = DATA / f"{day}.json"
    if out.exists():  # 2ª coleta do mesmo dia: soma, não apaga o que já foi aprovado
        old = json.loads(out.read_text("utf-8"))
        for key, _, limit_key in SECTIONS:
            urls = {it["url"] for it in report[key]}
            merged = report[key] + [it for it in old.get(key, []) if it["url"] not in urls]
            report[key] = merged[: cfg["limits"][limit_key]]
    (DATA / f"{day}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    dates = sorted({p.stem for p in DATA.glob("????-??-??.json")}, reverse=True)
    (DATA / "index.json").write_text(json.dumps({"datas": dates}, indent=2), "utf-8")
    if use_llm:
        seen.save()
    log.info("OK → data/%s.json", day)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--varredura-completa", action="store_true")
    args = ap.parse_args()
    run(use_llm=not args.no_llm, full_scan=args.varredura_completa)
