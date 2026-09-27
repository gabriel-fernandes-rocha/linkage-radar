"""Eventos e comunidades no Brasil (Sympla, Even3, Doity, Meetup...)."""
from __future__ import annotations

from common import item, log, today
from sources import websearch


def collect(cfg: dict) -> list[dict]:
    ws = cfg.get("web_search", {})
    if today(cfg).weekday() not in ws.get("events_weekdays", [0, 3]):
        log.info("events: hoje não é dia de buscar eventos (config web_search.events_weekdays)")
        return []
    terms = cfg["queries"]["events_br"]
    sites = cfg.get("event_sites", [])
    raw: list[dict] = []

    q = "(" + " OR ".join(f'"{t}"' for t in terms) + ") (" + " OR ".join(f"site:{s}" for s in sites) + ")"
    try:
        raw = websearch.serpapi(q, recency="qdr:y")
    except Exception as e:
        log.warning("events/serpapi falhou: %s", e)

    if not raw and not websearch.has_serpapi():  # SerpAPI vazio = nada novo (não gasta à toa)
        try:
            raw = websearch.claude_search(
                cfg,
                "Encontre eventos, meetups, cursos, workshops ou webinars que acontecerão nos próximos 90 dias "
                "NO BRASIL (presenciais ou online com organização brasileira) cujo tema central seja "
                f"record linkage, resolução de entidades, pareamento de bases, deduplicação ou geocodificação. "
                f"Termos úteis: {', '.join(terms)}. Priorize: {', '.join(sites)}, SBBD, BRACIS, GEOINFO, "
                "Fiocruz/CIDACS, PyData Brasil, Python Brasil. No campo 'data' coloque a data do evento.",
                allowed_domains=None,
                max_uses=ws.get("events_max_uses", 3),
            )
        except Exception as e:
            log.warning("events/claude_search falhou: %s", e)

    log.info("events: %d candidatos", len(raw))
    return [item("evento", r.get("titulo", ""), r["url"], texto=r.get("texto", ""),
                 data=r.get("data", ""), fonte="web") for r in raw if r.get("url")]
