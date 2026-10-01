"""Posts recentes no LinkedIn sobre Record Linkage / ER / geocodificação.

O LinkedIn não tem API pública de busca e proíbe scraping; por isso buscamos posts
públicos indexados por buscadores (site:linkedin.com/posts e /pulse).
"""
from __future__ import annotations

from common import item, log, today
from sources import websearch


def collect(cfg: dict) -> list[dict]:
    ws = cfg.get("web_search", {})
    if today(cfg).weekday() not in ws.get("linkedin_weekdays", list(range(7))):
        return []
    terms = cfg["queries"]["linkedin"]
    raw: list[dict] = []

    q = "(" + " OR ".join(f'"{t}"' for t in terms) + ") (site:linkedin.com/posts/ OR site:linkedin.com/pulse/ OR site:linkedin.com/jobs/view/)"
    try:
        raw = websearch.serpapi(q, recency="qdr:w")
    except Exception as e:
        log.warning("linkedin/serpapi falhou: %s", e)

    if not raw and not websearch.has_serpapi():  # SerpAPI vazio = nada novo (não gasta à toa)
        try:
            raw = websearch.claude_search(
                cfg,
                "Busque posts e artigos PUBLICADOS NOS ÚLTIMOS 7 DIAS no LinkedIn (linkedin.com/posts ou "
                "linkedin.com/pulse) sobre record linkage, entity resolution, entity matching, deduplicação de "
                "registros, address matching ou geocodificação, em português ou inglês. "
                f"Termos úteis: {', '.join(terms)}. Ignore posts antigos, vagas genéricas e propaganda.",
                allowed_domains=["linkedin.com"],
                max_uses=ws.get("linkedin_max_uses", 2),
            )
        except Exception as e:
            log.warning("linkedin/claude_search falhou: %s", e)

    log.info("linkedin: %d candidatos", len(raw))
    return [item("linkedin", r.get("titulo", ""), r["url"], texto=r.get("texto", ""),
                 data=r.get("data", ""), fonte="LinkedIn")
            for r in raw if "linkedin.com" in r.get("url", "")]
