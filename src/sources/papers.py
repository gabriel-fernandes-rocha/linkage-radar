"""Publicações recentes: arXiv, OpenAlex, Semantic Scholar e Crossref (fallback)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import timedelta

from common import clean, get, item, log, today

ARXIV_CATS = ["cs.DB", "cs.IR", "cs.LG", "stat.ME", "cs.CL", "cs.AI"]
LOOKBACK_DAYS = 7  # janela ampla; o dedup (data/seen.json) garante que nada se repete


def _authors(names: list[str]) -> str:
    names = [n for n in names if n]
    if not names:
        return ""
    return names[0] + (" et al." if len(names) > 1 else "")


def arxiv(queries: list[str], since) -> list[dict]:
    terms = " OR ".join(f'abs:"{q}"' for q in queries)
    cats = " OR ".join(f"cat:{c}" for c in ARXIV_CATS)
    r = get(
        "http://export.arxiv.org/api/query",
        params={
            "search_query": f"({terms}) AND ({cats})",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": 60,
        },
    )
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in ET.fromstring(r.content).findall("a:entry", ns):
        published = e.findtext("a:published", "", ns)[:10]
        if published < since:
            continue
        out.append(item(
            "paper",
            e.findtext("a:title", "", ns),
            e.findtext("a:id", "", ns),
            autores=_authors([a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)]),
            data=published,
            fonte="arXiv",
            texto=clean(e.findtext("a:summary", "", ns)),
        ))
    return out


def _openalex_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = {p: w for w, ps in inv.items() for p in ps}
    return " ".join(pos[i] for i in sorted(pos))


def openalex(queries: list[str], since) -> list[dict]:
    out = []
    for q in queries:
        r = get(
            "https://api.openalex.org/works",
            params={
                "search": q,
                "filter": f"from_publication_date:{since},type:article|preprint",
                "per-page": 25,
                "mailto": "linkage-radar@example.com",
            },
        )
        for w in r.json().get("results", []):
            url = (w.get("primary_location") or {}).get("landing_page_url") or w.get("doi") or w.get("id")
            out.append(item(
                "paper",
                w.get("title") or "",
                url,
                autores=_authors([a["author"]["display_name"] for a in w.get("authorships", [])]),
                data=w.get("publication_date", ""),
                fonte="OpenAlex",
                texto=clean(_openalex_abstract(w.get("abstract_inverted_index"))),
            ))
    return out


def semantic_scholar(queries: list[str], since) -> list[dict]:
    out = []
    for q in queries:
        r = get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": q,
                "publicationDateOrYear": f"{since}:",
                "fields": "title,url,abstract,authors,publicationDate",
                "limit": 20,
            },
        )
        for p in r.json().get("data", []) or []:
            out.append(item(
                "paper",
                p.get("title") or "",
                p.get("url") or "",
                autores=_authors([a.get("name", "") for a in p.get("authors", [])]),
                data=p.get("publicationDate") or "",
                fonte="Semantic Scholar",
                texto=clean(p.get("abstract")),
            ))
    return out


def crossref(queries: list[str], since) -> list[dict]:
    out = []
    for q in queries[:3]:
        r = get(
            "https://api.crossref.org/works",
            params={"query": q, "filter": f"from-pub-date:{since}", "rows": 15,
                    "select": "title,URL,author,abstract,issued"},
        )
        for w in r.json()["message"]["items"]:
            authors = [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in w.get("author", [])]
            out.append(item(
                "paper",
                (w.get("title") or [""])[0],
                w.get("URL", ""),
                autores=_authors(authors),
                fonte="Crossref",
                texto=clean(w.get("abstract")),
            ))
    return out


def collect(cfg: dict) -> list[dict]:
    queries = cfg["queries"]["papers"]
    since = (today(cfg) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    results: list[dict] = []
    for fn in (arxiv, openalex, semantic_scholar):
        try:
            got = fn(queries, since)
            log.info("papers/%s: %d", fn.__name__, len(got))
            results += got
        except Exception as e:  # uma fonte falhar não derruba as outras
            log.warning("papers/%s falhou: %s", fn.__name__, e)
    if not results:
        try:
            results = crossref(queries, since)
        except Exception as e:
            log.warning("papers/crossref falhou: %s", e)
    return [r for r in results if r["titulo"] and r["url"]]
