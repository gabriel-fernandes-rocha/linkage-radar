"""Coleta noturna: busca → filtro por palavras-chave → dedup → LLM juiz → data/YYYY-MM-DD.json.

Uso:
    python src/main_collect.py              # coleta real
    python src/main_collect.py --no-llm     # sem LLM (só palavras-chave; útil para testar)
"""
from __future__ import annotations

import argparse
import json
from datetime import timedelta

import lesson
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


def run(use_llm: bool = True) -> dict:
    cfg = load_config()
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

    for key, module, limit_key in SECTIONS:
        raw = module.collect(cfg)
        cands = [it for it in unique(raw) if seen.is_new(it) and keywords.passes(it)]
        cands.sort(key=lambda it: it["score"], reverse=True)
        cands = cands[:max(budget, 0)]
        budget -= len(cands)
        if use_llm:
            approved = llm_judge.judge(cands, cfg)
            approved.sort(key=lambda it: (it.get("confianca", 0), it["score"]), reverse=True)
            for it in cands:  # julgados (aprovados ou não) não são julgados de novo
                seen.add(it, day)
        else:
            approved = cands
        final = approved[: cfg["limits"][limit_key]]
        for it in final:
            it.pop("texto", None)  # não precisamos guardar o texto bruto
        report[key] = final
        stats[key] = {"brutos": len(raw), "pos_palavras_chave": len(cands), "aprovados": len(final)}
        log.info("%s: %s", key, stats[key])

    report["aula"] = lesson.for_date(cfg, edition.date())
    report["estatisticas"] = stats

    DATA.mkdir(exist_ok=True)
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
    run(use_llm=not ap.parse_args().no_llm)
