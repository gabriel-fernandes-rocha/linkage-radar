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
import career
import compat
import brasil
import health
import job_archive
import market
import open_jobs
from common import DATA, load_config, log, today
from dedup import Seen, unique
from filters import heuristic, keywords, llm_judge, requirements
from sources import events, jobs, linkedin, network, papers

SECTIONS = [  # (chave no JSON, módulo, limite em config.limits)
    ("vagas", jobs, "max_jobs"),
    ("eventos", events, "max_events"),
    ("papers", papers, "max_papers"),
    ("linkedin", linkedin, "max_linkedin"),
]


def safe(label: str, fn, default=None):
    """Roda uma etapa secundária isolada: se falhar, registra (o monitor de saúde mostra) e a coleta continua.
    Assim um erro numa parte nunca deixa o dia sem edição."""
    try:
        return fn()
    except Exception as e:
        import traceback

        log.warning("etapa %s falhou: %s | %s", label, e, traceback.format_exc(limit=3).replace("\n", " "))
        return default


def run(use_llm: bool = True, full_scan: bool = False, only_if_missing: bool = False,
        rejudge: bool = False) -> dict | None:
    cfg = load_config()
    if full_scan:
        s = cfg.setdefault("serpapi", {})
        s["jobs_searches_per_day"] = len(cfg["queries"]["jobs"]) * s.get("jobs_pages_per_term", 2)
    now = today(cfg)
    # Coleta às 23h prepara a edição do dia seguinte (a que chega às 6h)
    edition = (now + timedelta(days=1)) if now.hour >= 18 else now
    day = edition.strftime("%Y-%m-%d")
    if only_if_missing and (DATA / f"{day}.json").exists():
        log.info("edição %s já coletada; nada a fazer", day)
        return None
    seen = Seen()
    use_llm = use_llm and llm_judge.available(cfg)
    if not use_llm:
        log.warning("LLM desativado (sem chave ou --no-llm): usando só palavras-chave — menos preciso")

    report = {"data": day, "gerado_em": now.isoformat(timespec="minutes"), "llm": use_llm}
    from sources import websearch

    report["serpapi_orcamento"] = websearch.set_daily_budget()
    budget = cfg["llm"].get("max_items_per_day", 80)
    stats = {}
    approved_all: dict[str, list[dict]] = {}
    raw_jobs: list[dict] = []
    # 1ª vez: rejulga vagas já vistas para montar a carteira e o arquivo com requisitos
    bootstrap = rejudge or not (open_jobs.PATH.exists() and job_archive.ARCHIVE.exists())

    for key, module, limit_key in SECTIONS:
        raw = safe(f"fonte {key}", lambda: module.collect(cfg), []) or []
        if key == "vagas":
            raw_jobs = raw
        cands = [it for it in unique(raw)
                 if (seen.is_new(it) or (bootstrap and key == "vagas")) and keywords.passes(it)]
        # vagas publicadas mais recentemente vão primeiro para o juiz (ser dos primeiros a se candidatar)
        cands.sort(key=lambda it: (it.get("publicada_em") or "", it["score"]), reverse=True)
        cands = cands[:max(budget, 0)]
        budget -= len(cands)
        if use_llm:
            approved = safe(f"juiz {key}", lambda: llm_judge.judge(cands, cfg), []) or []
            for it in cands:  # só o que foi REALMENTE julgado vira "visto"; o resto é reavaliado amanhã
                if it.pop("_julgado", False):
                    seen.add(it, day)
                elif heuristic.approve(it):  # nenhuma IA respondeu: heurística de alta precisão
                    it.update(nao_verificado=True, motivo="Aprovado pela heurística (nenhuma IA respondeu hoje); "
                                                          "será reavaliado quando um juiz voltar.")
                    approved.append(it)
            approved.sort(key=lambda it: (it.get("encaixe", 0), it.get("confianca", 0), it["score"]), reverse=True)
        else:
            approved = cands
        if key == "eventos":  # só evento de verdade: página de evento, com data futura (não docs/artigos)
            approved = safe("validar eventos", lambda: events.validate(approved, edition.date()), approved)
        if key == "linkedin":  # vaga divulgada no LinkedIn também é vaga
            posted_jobs = [it for it in approved if "/jobs/view/" in it["url"]]
            approved = [it for it in approved if it not in posted_jobs]
            for it in posted_jobs:
                it["tipo"], it["fonte"] = "vaga", "LinkedIn Jobs"
            approved_all["vagas"] += posted_jobs
            report["vagas"] = (report["vagas"] + posted_jobs)[: cfg["limits"]["max_jobs"]]
        if key in ("vagas", "linkedin"):  # requisitos antes de descartar o texto
            fresh_jobs = [it for it in approved_all.get("vagas", []) + approved
                          if it["tipo"] == "vaga" and "requisitos" not in it]
            if use_llm:
                safe("requisitos", lambda: requirements.extract(fresh_jobs, cfg))
            safe("requisitos sem IA", lambda: requirements.ensure(fresh_jobs))  # toda vaga ganha compatibilidade
            safe("compatibilidade", lambda: compat.score_jobs(fresh_jobs, cfg))
        approved_all[key] = list(approved)
        final = approved[: cfg["limits"][limit_key]]
        for it in final:
            it.pop("texto", None)  # não precisamos guardar o texto bruto
        report[key] = final
        stats[key] = {"brutos": len(raw), "pos_palavras_chave": len(cands), "aprovados": len(final)}
        log.info("%s: %s", key, stats[key])

    if use_llm:
        max_age = cfg.get("open_jobs", {}).get("max_age_days", 60)
        abertas = safe("vagas abertas", lambda: open_jobs.update(approved_all.get("vagas", []), raw_jobs, day,
                                                                  max_age), None)
        if abertas is None:
            abertas = open_jobs.load()
        try:
            # habilidades de todas as vagas (garante vereditos; refaz tudo se o currículo mudou)
            all_skills = {s for j in abertas + job_archive.load() for s in
                          ((j.get("requisitos") or {}).get("obrigatorios", []) +
                           (j.get("requisitos") or {}).get("desejaveis", []))}
            requirements.ensure(abertas)  # vaga antiga sem requisitos (IA falhou no dia) recebe estimativa
            cache = compat.classify_skills(all_skills, cfg)
            for j in abertas:
                try:
                    compat.score(j, cfg, cache)
                except Exception as e:
                    log.warning("compatibilidade falhou em '%s': %s", j.get("titulo", "")[:60], e)
            abertas.sort(key=lambda j: j.get("encaixe", 0), reverse=True)
            open_jobs.save(abertas)
            market.sample_broad_market(raw_jobs, cfg, day)
        except Exception as e:
            log.warning("mercado: atualização falhou (%s)", e)
    else:
        abertas = open_jobs.load()
    report["vagas_abertas_total"] = len(abertas)
    if use_llm:
        archive = safe("arquivo de vagas", lambda: job_archive.update(approved_all.get("vagas", []), abertas, day),
                       [])
        report["vagas_arquivadas_total"] = len(archive)

    if use_llm:
        judge_net = lambda items: llm_judge.judge(
            [it for it in unique(items) if seen.is_new(it) and keywords.passes(it)], cfg)
        report["rede"] = safe("pessoas e empresas", lambda: network.update(
            cfg, day, approved_all.get("linkedin", []), approved_all.get("vagas", []), judge_net))
        pilula = safe("pílula de mercado", lambda: career.market_lesson(cfg, day))
        report["pilula_mercado"] = pilula["habilidade"] if pilula else None
        safe("análise de perfil", lambda: career.profile_tips(cfg, day))

    # aba "Brasil": vagas no Brasil com entity resolution e variações (roda isolada)
    report["brasil"] = safe("aba Brasil", lambda: brasil.run(cfg, day, raw_jobs, use_llm))
    report["aula"] = safe("aula", lambda: lesson.for_date(cfg, edition.date()))
    report["estatisticas"] = stats
    try:
        report["saude"] = health.check(cfg, day, report)["status"]
    except Exception as e:  # o monitor nunca pode derrubar a coleta
        log.warning("saúde: verificação falhou (%s)", e)

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
    ap.add_argument("--se-ainda-nao-coletou", action="store_true", help="usado pelo agendamento (evita coletar 2x)")
    ap.add_argument("--rejulgar-vagas", action="store_true", help="julga de novo vagas já vistas (após mudar o juiz)")
    args = ap.parse_args()
    from common import save_log

    try:
        run(use_llm=not args.no_llm, full_scan=args.varredura_completa, only_if_missing=args.se_ainda_nao_coletou,
            rejudge=args.rejulgar_vagas)
    except Exception:
        log.exception("coleta caiu")
        raise
    finally:
        save_log(today(load_config()).strftime("%Y-%m-%d"))
