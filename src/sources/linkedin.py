"""Posts recentes no LinkedIn sobre Record Linkage / ER / geocodificação.

O LinkedIn não tem API pública de busca e proíbe scraping; por isso buscamos posts
públicos indexados por buscadores (site:linkedin.com/posts e /pulse).
"""
from __future__ import annotations

import re

from common import item, log, today
from sources import websearch


def collect(cfg: dict) -> list[dict]:
    ws = cfg.get("web_search", {})
    if today(cfg).weekday() not in ws.get("linkedin_weekdays", list(range(7))):
        return []
    terms = cfg["queries"]["linkedin"]
    raw: list[dict] = []

    q = "(" + " OR ".join(f'"{t}"' for t in terms) + ") (site:linkedin.com/posts/ OR site:linkedin.com/pulse/ OR site:linkedin.com/jobs/view/)"
    # O Google às vezes ignora o filtro site: com caminho e devolve outros sites. Se vierem poucos posts
    # do LinkedIn, tentamos o formato alternativo (domínio + inurl). Só gasta a 2ª busca quando precisa.
    is_li = lambda r: re.search(r"linkedin\.com/(posts|pulse|jobs/view)/", r.get("url", ""))
    terms_q = "(" + " OR ".join(f'"{t}"' for t in terms) + ")"
    for query in (q, f"site:linkedin.com inurl:posts {terms_q}"):
        try:
            got = [r for r in websearch.serpapi(query, recency="qdr:w") if is_li(r)]
        except Exception as e:
            log.warning("linkedin/serpapi falhou: %s", e)
            got = []
        known = {r["url"] for r in raw}
        raw += [r for r in got if r["url"] not in known]
        log.info("linkedin: consulta trouxe %d posts", len(got))
        if len(raw) >= 3:
            break

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
