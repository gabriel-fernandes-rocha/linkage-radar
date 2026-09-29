"""Rede: pessoas e empresas do nicho para seguir no LinkedIn (data/people.json, data/companies.json).

Fontes (sem login, sem scraping do LinkedIn):
  - Google via SerpAPI: perfis públicos (linkedin.com/in) e páginas de empresa (linkedin.com/company),
    com rodízio diário de termos;
  - autores dos posts do LinkedIn aprovados pelo juiz (quem posta sobre o tema é ótimo para seguir);
  - empresas que abriram vagas do nicho (link de busca da empresa no LinkedIn).
Tudo passa pelo juiz LLM; entram no máximo `network.max_people` e `network.max_companies` novos por dia.
"""
from __future__ import annotations

import json
import re
from datetime import date
from urllib.parse import quote_plus

from common import DATA, item, log
from dedup import _norm_url
from sources import websearch

PEOPLE = DATA / "people.json"
COMPANIES = DATA / "companies.json"


def load(path) -> list[dict]:
    return json.loads(path.read_text("utf-8")) if path.exists() else []


def _term_of_day(terms: list[str], offset: int = 0) -> str:
    return terms[(date.today().toordinal() + offset) % len(terms)]


def _clean_name(title: str) -> str:
    return re.split(r"\s[-|–—]\s", title)[0].strip()


def search_people(cfg: dict) -> list[dict]:
    term = _term_of_day(cfg["queries"]["network"])
    out = []
    # a barra final em /in/ é obrigatória: sem ela o Google ignora o filtro de site
    for r in websearch.serpapi(f'"{term}" site:linkedin.com/in/', recency=None):
        if "linkedin.com/in/" in r["url"]:
            out.append(item("pessoa", r["titulo"], r["url"].split("?")[0], nome=_clean_name(r["titulo"]),
                            texto=f"{r['titulo']}. {r['texto']}", fonte="Perfil público no LinkedIn"))
    return out


def search_companies(cfg: dict) -> list[dict]:
    terms = cfg["queries"]["network"]
    q = " OR ".join(f'"{t}"' for t in (_term_of_day(terms, 3), _term_of_day(terms, 5)))
    out = []
    for r in websearch.serpapi(f"({q}) site:linkedin.com/company/", recency=None):
        if "linkedin.com/company/" in r["url"]:
            out.append(item("empresa", r["titulo"], r["url"].split("?")[0], nome=_clean_name(r["titulo"]),
                            texto=f"{r['titulo']}. {r['texto']}", fonte="Página no LinkedIn"))
    return out


def _author_name(post_title: str, slug: str) -> str:
    """'Maria Silva's Post' / 'Publicação de Maria Silva' / 'Maria Silva on LinkedIn: ...' -> nome."""
    for pat in (r"^(.+?)['’]s Post", r"^Publicação de (.+?)(,|$)", r"^(.+?) on LinkedIn", r"^(.+?) no LinkedIn"):
        m = re.search(pat, post_title)
        if m:
            return m.group(1).strip()
    words = [w for w in slug.split("-") if not re.search(r"\d", w)]  # tira sufixos numéricos do link
    return " ".join(words).title() or slug


def authors_from_posts(posts: list[dict]) -> list[dict]:
    """linkedin.com/posts/<perfil>_<slug>-activity-... -> linkedin.com/in/<perfil>"""
    out = []
    for p in posts:
        m = re.search(r"linkedin\.com/posts/([^_/?]+)_", p["url"])
        if m:
            out.append(item("pessoa", p["titulo"], f"https://www.linkedin.com/in/{m.group(1)}/",
                            nome=_author_name(p["titulo"], m.group(1)), fonte="Autor de post",
                            resumo=f"Publicou: {p.get('resumo') or p['titulo']}"))
    return out


def companies_from_jobs(jobs: list[dict]) -> list[dict]:
    out = []
    for j in jobs:
        name = (j.get("empresa") or "").strip()
        if name and name.lower() not in ("upwork", "anywhere", "confidential", "confidencial"):
            url = f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(name)}"
            out.append(item("empresa", name, url, nome=name, fonte="Contratando no nicho",
                            resumo=f"Tem vaga aberta: {j['titulo']}"))
    return out


def _merge(path, new: list[dict], day: str, limit: int) -> list[dict]:
    current = load(path)
    for c in current:
        c["novo"] = c.get("desde") == day
    known = {_norm_url(c["url"]) for c in current} | {c.get("nome", "").lower() for c in current}
    added = 0
    for n in new:
        if added >= limit:
            break
        if _norm_url(n["url"]) in known or n.get("nome", "").lower() in known:
            continue
        entry = {k: n.get(k) for k in ("nome", "titulo", "url", "resumo", "motivo", "fonte") if n.get(k)}
        entry.update(desde=day, novo=True)
        current.insert(0, entry)
        known |= {_norm_url(n["url"]), n.get("nome", "").lower()}
        added += 1
    path.write_text(json.dumps(current, ensure_ascii=False, indent=1), "utf-8")
    return current


def update(cfg: dict, day: str, approved_posts: list[dict], new_jobs: list[dict], judge) -> dict:
    net = cfg.get("network", {})
    people, companies = [], []
    try:
        people = judge(search_people(cfg))
    except Exception as e:
        log.warning("network/pessoas falhou: %s", e)
    try:
        companies = judge(search_companies(cfg))
    except Exception as e:
        log.warning("network/empresas falhou: %s", e)
    # autores de posts aprovados e empresas contratando já são relevantes por construção
    people = authors_from_posts(approved_posts) + people
    companies = companies + companies_from_jobs(new_jobs)
    p = _merge(PEOPLE, people, day, net.get("max_people", 5))
    c = _merge(COMPANIES, companies, day, net.get("max_companies", 3))
    log.info("network: %d pessoas (%d novas), %d empresas (%d novas)",
             len(p), sum(x["novo"] for x in p), len(c), sum(x["novo"] for x in c))
    return {"pessoas_novas": sum(x["novo"] for x in p), "empresas_novas": sum(x["novo"] for x in c)}
