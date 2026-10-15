"""Eventos e comunidades no Brasil (Sympla, Even3, Doity, Meetup...)."""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit

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


# ---------- validação: só passa o que é realmente um EVENTO futuro ----------
EVENT_HOSTS = ("sympla.com.br", "even3.com.br", "doity.com.br", "meetup.com", "eventbrite.com",
               "eventbrite.com.br", "lu.ma", "conference", "congresso", "sbbd", "bracis", "geoinfo", "pydata",
               "pythonbrasil", "sbc.org.br")
NOT_EVENT_HOSTS = ("learn.microsoft.com", "docs.", "github.com", "wikipedia.org", "medium.com", "youtube.com",
                   "stackoverflow.com", "linkedin.com/pulse", "amazon.com", "scielo", "arxiv.org", "/blog")
EVENT_WORDS = re.compile(r"\b(evento|workshop|meetup|webinar|webin[aá]rio|confer[eê]ncia|congresso|simp[oó]sio|"
                         r"semin[aá]rio|palestra|minicurso|hackathon|summit|encontro|inscri[cç][oõ]es|"
                         r"inscreva|ingressos?|event|conference|symposium)\b", re.I)
MONTHS = {"jan": 1, "fev": 2, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "mai": 5, "may": 5, "jun": 6, "jul": 7,
          "ago": 8, "aug": 8, "set": 9, "sep": 9, "out": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12}


def _dates(text: str) -> list[date]:
    out = []
    for d, m, y in re.findall(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b", text):
        out.append((int(y), int(m), int(d)))
    for y, m, d in re.findall(r"\b(20\d\d)-(\d\d)-(\d\d)\b", text):
        out.append((int(y), int(m), int(d)))
    for d, mon, y in re.findall(r"\b(\d{1,2}) (?:de )?([a-zç]{3})[a-zç]*\.?,? (?:de )?(20\d\d)\b", text.lower()):
        if mon in MONTHS:
            out.append((int(y), MONTHS[mon], int(d)))
    res = []
    for y, m, d in out:
        try:
            res.append(date(y, m, d))
        except ValueError:
            pass
    return res


def is_real_event(it: dict, ref: date) -> tuple[bool, str]:
    """Regras: não pode ser página de documentação/artigo; precisa ser página de evento (Sympla, Even3...)
    ou ter cara de evento (inscrição, workshop, meetup...); e não pode ter só datas passadas."""
    url = it.get("url", "").lower()
    host = urlsplit(url).netloc
    text = f"{it.get('titulo', '')} {it.get('texto', '')}"
    if any(b in url for b in NOT_EVENT_HOSTS):
        return False, f"página de conteúdo, não de evento ({host})"
    event_page = any(h in host for h in EVENT_HOSTS)
    if not event_page and not EVENT_WORDS.search(text):
        return False, "sem sinais de evento (inscrição, data, workshop, meetup...)"
    dates = _dates(text)  # o campo 'data' do Google é a data da PÁGINA, não do evento: não serve
    if dates and max(dates) < ref:
        return False, f"evento já aconteceu ({max(dates).strftime('%d/%m/%Y')})"
    if not dates and not event_page:
        return False, "sem data de evento"
    return True, ""


def validate(items: list[dict], ref: date) -> list[dict]:
    keep = []
    for it in items:
        ok, why = is_real_event(it, ref)
        if ok:
            keep.append(it)
        else:
            log.info("events: descartado '%s': %s", it.get("titulo", "")[:60], why)
    return keep
