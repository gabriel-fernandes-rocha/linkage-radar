"""Fontes de vagas NO BRASIL para a aba "Brasil" (src/brasil.py).

A vaga ideal costuma ter título genérico ("Cientista de Dados Pleno") e o tema só na descrição
("resolução de identidade", "matching determinístico ou probabilístico", "golden record"). Por isso
todas as fontes aqui trazem a DESCRIÇÃO INTEIRA e o filtro lê o texto todo.

- InHire (BRQ, Neoway, Semantix, Dataside, XP, Cielo, Deloitte, KPMG...): API pública por empresa.
  A lista de empresas cresce sozinha: todo link *.inhire.app visto em qualquer fonte vira empresa monitorada.
- Gupy: busca por vários cargos de dados (a busca da Gupy é só no título) com paginação.
- Google Jobs no Brasil (SerpAPI, location=Brazil) com termos em português.
- Vagas do LinkedIn (br.linkedin.com/jobs/view) via DuckDuckGo/Google (SerpAPI), sem login.
"""
from __future__ import annotations

import html
import json
import os
import re
from datetime import date

from common import DATA, clean, get, item, log
from sources.jobs import _job

TENANTS_FILE = DATA / "brasil" / "inhire_tenants.json"
DATA_TITLE = re.compile(
    r"(dados|data|analytics|\bbi\b|mdm|cadastr|machine learning|\bml\b|\bia\b|\bai\b|cientista|engenheir|"
    r"governan|qualidade|matching|linkage|estat[ií]stic|intelig[eê]ncia|python|spark|big ?data|arquitet)", re.I)


def _html_text(s: str | None) -> str:
    return clean(re.sub(r"<[^>]+>", " ", html.unescape(s or "")), 8000)


# ---------------------------------------------------------------- InHire
def tenants(cfg: dict) -> list[str]:
    found = []
    try:
        found = json.loads(TENANTS_FILE.read_text("utf-8")) if TENANTS_FILE.exists() else []
    except Exception:
        pass
    return list(dict.fromkeys(cfg.get("brasil", {}).get("inhire", []) + found))


def discover_tenants(items: list[dict], cfg_tenants: list[str] = ()) -> list[str]:
    """Todo link xxx.inhire.app que aparecer (Google Jobs, LinkedIn, posts) vira empresa monitorada."""
    new = set()
    for it in items:
        for m in re.finditer(r"https?://([a-z0-9-]+)\.inhire\.app", f"{it.get('url', '')} {it.get('texto', '')}"):
            if m[1] not in ("api", "auth", "files", "www", "app", "data-viz", "status", "mcp"):
                new.add(m[1])
    if new:
        TENANTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        known = json.loads(TENANTS_FILE.read_text("utf-8")) if TENANTS_FILE.exists() else []
        added = sorted(new - set(known) - set(cfg_tenants))
        if added:
            TENANTS_FILE.write_text(json.dumps(sorted(set(known) | set(added)), indent=1), "utf-8")
            log.info("brasil/inhire: novas empresas descobertas: %s", ", ".join(added))
    return sorted(new)


def inhire(cfg: dict) -> list[dict]:
    out = []
    for t in tenants(cfg):
        h = {"X-Tenant": t, "User-Agent": "Mozilla/5.0"}
        try:
            page = get("https://api.inhire.app/job-posts/public/pages", headers=h, retries=1).json()
        except Exception as e:
            log.info("brasil/inhire '%s' indisponível (%s)", t, str(e)[:60])
            continue
        company = (page.get("tenantName") or t).strip()
        for j in page.get("jobsPage") or []:
            title = (j.get("displayName") or "").strip()
            if j.get("status") != "published" or not DATA_TITLE.search(title):
                continue  # só abre a descrição de vagas de dados (economiza chamadas)
            try:
                d = get(f"https://api.inhire.app/job-posts/public/pages/{j['jobId']}", headers=h, retries=1).json()
            except Exception:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            mode = {"Remote": "Remoto", "Hybrid": "Híbrido", "OnSite": "Presencial"}.get(j.get("workplaceType"), "")
            local = " · ".join(x for x in (mode, d.get("locationComplement") or "", "Brasil" if j.get("location") == "BR"
                                           else j.get("location") or "") if x)
            out.append(_job(title, f"https://{t}.inhire.app/vagas/{j['jobId']}/{slug}", company, local,
                            _html_text(d.get("description")), "InHire", d.get("lastPublishedAt") or d.get("publishedAt")))
    return out


# ---------------------------------------------------------------- Gupy (vários cargos, com paginação)
def gupy(cfg: dict) -> list[dict]:
    out, seen = [], set()
    for q in cfg.get("brasil", {}).get("gupy_titles", []):
        for offset in (0, 100, 200):
            try:
                data = get("https://portal.gupy.io/api/job-search/jobs",
                           params={"jobName": q, "limit": 100, "offset": offset}).json()
            except Exception as e:
                log.warning("brasil/gupy '%s' falhou: %s", q, str(e)[:100])
                break
            rows = data.get("data", [])
            for j in rows:
                if j.get("jobUrl") in seen:
                    continue
                seen.add(j.get("jobUrl"))
                remote = j.get("isRemoteWork") or j.get("workplaceType") == "remote"
                local = "Remoto (Brasil)" if remote else ", ".join(x for x in (j.get("city"), j.get("state")) if x)
                out.append(_job(j.get("name"), j.get("jobUrl"), (j.get("careerPageName") or "").strip(), local,
                                j.get("description"), "Gupy", j.get("publishedDate")))
            if len(rows) < 100:
                break
    return out


# ---------------------------------------------------------------- Google Jobs no Brasil
def google_jobs_br(cfg: dict) -> list[dict]:
    from sources import websearch

    key = os.getenv("SERPAPI_KEY")
    if not key:
        return []
    terms = cfg.get("brasil", {}).get("google_jobs", [])
    per_day = cfg.get("brasil", {}).get("google_jobs_por_dia", 2)
    out = []
    for i in range(per_day):
        q = terms[(date.today().toordinal() * per_day + i) % len(terms)]
        if not websearch.take("alta"):
            break
        try:
            data = get("https://serpapi.com/search.json", timeout=60, params={
                "engine": "google_jobs", "q": q, "location": "Brazil", "gl": "br", "hl": "pt", "api_key": key}).json()
        except Exception as e:
            log.warning("brasil/google_jobs '%s' falhou: %s", q, e)
            continue
        for j in data.get("jobs_results", []):
            links = [o.get("link", "") for o in (j.get("apply_options") or [])]
            link = next((u for u in links if "inhire.app" in u or "gupy.io" in u), links[0] if links else
                        j.get("share_link", ""))
            it = _job(j.get("title"), link, j.get("company_name"), j.get("location") or "Brasil",
                      j.get("description"), "Google Jobs (Brasil)", (j.get("detected_extensions") or {}).get("posted_at"))
            it["texto"] += " " + " ".join(links)  # para descobrir empresas na InHire
            out.append(it)
    return out


# ---------------------------------------------------------------- vagas do LinkedIn (sem login)
def linkedin_jobs_br(cfg: dict) -> list[dict]:
    """Dias pares: vagas (br.linkedin.com/jobs/view). Dias ímpares: POSTS de vaga no feed
    (é onde recrutadores e times anunciam, ex.: "vaga de estágio no time de Importação... integração de dados")."""
    from sources import websearch

    terms = cfg.get("brasil", {}).get("linkedin_termos", [])
    if not terms:
        return []
    day = date.today().toordinal()
    term = terms[(day // 2) % len(terms)]
    if day % 2 == 0:
        found = websearch.cascade([
            ("ddg", f'"{term}" site:br.linkedin.com/jobs/view', None),
            ("google", f'"{term}" site:br.linkedin.com/jobs/view/', "qdr:m"),
        ], lambda r: "linkedin.com/jobs/view" in r["url"], want=5, label="brasil/linkedin")
        return [item("vaga", re.sub(r"\s*\|\s*LinkedIn.*$", "", r["titulo"]), r["url"].split("?")[0], empresa="",
                     local="Brasil", fonte="LinkedIn Jobs (Brasil)", texto=r["texto"]) for r in found]
    hiring = '("vaga" OR "estamos contratando" OR "oportunidade" OR "contratando")'
    found = websearch.cascade([
        ("ddg", f'"{term}" vaga site:linkedin.com/posts', "qdr:m"),
        ("google", f'"{term}" {hiring} site:linkedin.com/posts/', "qdr:w"),
    ], lambda r: "linkedin.com/posts/" in r["url"] or "/feed/update/" in r["url"], want=5,
        label="brasil/linkedin_posts")
    return [item("vaga", r["titulo"], r["url"].split("?")[0], empresa="", local="Brasil",
                 fonte="Post · LinkedIn (Brasil)", texto=r["texto"], social=True) for r in found]


SOURCES = [inhire, gupy, google_jobs_br, linkedin_jobs_br]
