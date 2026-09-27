"""Vagas no mundo todo: Adzuna, RemoteOK, Remotive, Greenhouse/Lever/Ashby, HN Who is hiring, SerpAPI."""
from __future__ import annotations

import os
import re
from datetime import date

from common import clean, get, item, log


def _job(title, url, company, location, text, source):
    return item("vaga", title, url, empresa=company or "", local=location or "", fonte=source, texto=clean(text))


def adzuna(cfg):
    app_id, key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (app_id and key):
        log.info("jobs/adzuna: sem chave, pulando")
        return []
    out = []
    for country in cfg.get("adzuna_countries", ["us"]):
        for q in cfg["queries"]["jobs"]:
            r = get(
                f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
                params={"app_id": app_id, "app_key": key, "what_phrase": q,
                        "max_days_old": 30, "results_per_page": 20},
            )
            for j in r.json().get("results", []):
                out.append(_job(j.get("title"), j.get("redirect_url"),
                                (j.get("company") or {}).get("display_name"),
                                (j.get("location") or {}).get("display_name"),
                                j.get("description"), f"Adzuna/{country}"))
    return out


def remoteok(cfg):
    data = get("https://remoteok.com/api").json()[1:]
    return [_job(j.get("position"), j.get("url"), j.get("company"), j.get("location") or "Remoto",
                 f"{' '.join(j.get('tags', []))} {j.get('description', '')}", "RemoteOK") for j in data]


def remotive(cfg):
    out = []
    for q in cfg["queries"]["jobs"]:
        for j in get("https://remotive.com/api/remote-jobs", params={"search": q}).json().get("jobs", []):
            out.append(_job(j.get("title"), j.get("url"), j.get("company_name"),
                            j.get("candidate_required_location") or "Remoto", j.get("description"), "Remotive"))
    return out


def greenhouse(cfg):
    out = []
    for slug in cfg.get("companies", {}).get("greenhouse", []):
        try:
            data = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"}).json()
        except Exception:
            continue
        for j in data.get("jobs", []):
            out.append(_job(j.get("title"), j.get("absolute_url"), slug,
                            (j.get("location") or {}).get("name"), j.get("content"), f"Greenhouse/{slug}"))
    return out


def lever(cfg):
    out = []
    for slug in cfg.get("companies", {}).get("lever", []):
        try:
            data = get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}).json()
        except Exception:
            continue
        for j in data:
            out.append(_job(j.get("text"), j.get("hostedUrl"), slug,
                            (j.get("categories") or {}).get("location"), j.get("descriptionPlain"), f"Lever/{slug}"))
    return out


def ashby(cfg):
    out = []
    for slug in cfg.get("companies", {}).get("ashby", []):
        try:
            data = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}").json()
        except Exception:
            continue
        for j in data.get("jobs", []):
            out.append(_job(j.get("title"), j.get("jobUrl"), slug, j.get("location"),
                            j.get("descriptionPlain"), f"Ashby/{slug}"))
    return out


def hn_who_is_hiring(cfg):
    """Comentários do post 'Ask HN: Who is hiring?' do mês que citam os termos."""
    hits = get("https://hn.algolia.com/api/v1/search_by_date",
               params={"query": "Ask HN: Who is hiring", "tags": "story,author_whoishiring", "hitsPerPage": 1}).json()["hits"]
    if not hits:
        return []
    story = hits[0]["objectID"]
    out = []  # thread inteira do mês: vagas ainda abertas, o dedup evita repetição
    for q in cfg["queries"]["jobs"]:
        res = get("https://hn.algolia.com/api/v1/search",
                  params={"query": f'"{q}"', "tags": f"comment,story_{story}",
                          "hitsPerPage": 20}).json()
        for c in res["hits"]:
            text = clean(c.get("comment_text"), 2000)
            first = re.split(r"\|| - ", text)[0][:80]
            out.append(_job(f"HN: {first}", f"https://news.ycombinator.com/item?id={c['objectID']}",
                            first, "", text, "HN Who is hiring"))
    return out


def serpapi_google_jobs(cfg):
    """Google Jobs (agrega LinkedIn, Indeed, Glassdoor, sites de empresas...). Sem filtro de data:
    traz as vagas ABERTAS; o dedup garante que só as novas vão para o juiz.

    Rodízio de termos (sem aspas — o Google Jobs não aceita frase exata) e paginação,
    limitado por `serpapi.jobs_searches_per_day` para caber no plano grátis.
    """
    key = os.getenv("SERPAPI_KEY")
    if not key:
        return []
    per_day = cfg.get("serpapi", {}).get("jobs_searches_per_day", 4)
    pages = cfg.get("serpapi", {}).get("jobs_pages_per_term", 2)
    terms = cfg["queries"]["jobs"]
    start = (date.today().toordinal() * max(per_day // pages, 1)) % len(terms)
    out, used, i = [], 0, 0
    while used < per_day and i < len(terms):
        q = terms[(start + i) % len(terms)].replace('"', "")
        i += 1
        token = None
        for _ in range(pages):
            if used >= per_day:
                break
            params = {"engine": "google_jobs", "q": q, "api_key": key}
            if token:
                params["next_page_token"] = token
            used += 1
            try:
                data = get("https://serpapi.com/search.json", params=params, timeout=60).json()
            except Exception as e:  # uma busca falhar não descarta as outras
                log.warning("jobs/google '%s' falhou: %s", q, e)
                break
            for j in data.get("jobs_results", []):
                link = (j.get("apply_options") or [{}])[0].get("link") or j.get("share_link", "")
                out.append(_job(j.get("title"), link, j.get("company_name"), j.get("location"),
                                j.get("description"), "Google Jobs"))
            token = (data.get("serpapi_pagination") or {}).get("next_page_token")
            if not token:
                break
    log.info("jobs/google: %d buscas SerpAPI", used)
    return out


SOURCES = [adzuna, remoteok, remotive, greenhouse, lever, ashby, hn_who_is_hiring, serpapi_google_jobs]


def collect(cfg: dict) -> list[dict]:
    results = []
    for fn in SOURCES:
        try:
            got = fn(cfg)
            log.info("jobs/%s: %d", fn.__name__, len(got))
            results += got
        except Exception as e:
            log.warning("jobs/%s falhou: %s", fn.__name__, e)
    return [r for r in results if r["titulo"] and r["url"]]
