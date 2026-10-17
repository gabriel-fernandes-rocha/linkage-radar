"""LinkedIn SEM LOGIN: busca pública de vagas (a mesma de quem abre o LinkedIn deslogado) e posts públicos.

- Vagas: /jobs-guest/jobs/api/seeMoreJobPostings/search devolve os cartões; /jobs-guest/jobs/api/jobPosting/{id}
  devolve a DESCRIÇÃO inteira. Só abrimos a descrição de vagas com título de dados (o LinkedIn mistura muita
  coisa sem relação) e que ainda não vimos.
- Posts: a página pública de um post (/posts/... ou /feed/update/...) traz o texto completo e o link de
  candidatura (lnkd.in), que resolvemos para chegar na vaga real (InHire, Gupy...).

Riscos (aceitos por você em out/2026): os termos de uso do LinkedIn não permitem coleta automatizada. Não usamos
sua conta nem cookies, então sua conta não corre risco; o pior caso é o LinkedIn bloquear o IP do GitHub Actions
(429/999) por um tempo. Por isso: poucas consultas por dia, pausa entre elas, novas tentativas com espera e,
se bloquear, a fonte para no dia e o radar segue com as outras.
"""
from __future__ import annotations

import html
import random
import re
import time

import requests

from common import clean, log

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}
SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"
GEO = {"brasil": "106057199"}
STATE = {"bloqueado": False, "consultas": 0}
CARD = re.compile(r'urn:li:jobPosting:(\d+)".*?base-search-card__title">\s*(.*?)\s*</h3>.*?'
                  r'base-search-card__subtitle">(.*?)</h4>.*?job-search-card__location">\s*(.*?)\s*</span>'
                  r'(?:.*?datetime="([\d-]+)")?', re.S)


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(s or ""))).strip()


def _get(url: str, params: dict | None = None, max_calls: int = 200) -> requests.Response | None:
    """GET educado: pausa de 2 a 4 s, até 3 tentativas com espera crescente em 429; 999/403 = bloqueado no dia."""
    if STATE["bloqueado"] or STATE["consultas"] >= max_calls:
        return None
    for attempt in range(3):
        time.sleep(random.uniform(2.0, 4.0))
        STATE["consultas"] += 1
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30, allow_redirects=True)
        except requests.RequestException as e:
            log.info("linkedin_guest: erro de rede (%s)", str(e)[:80])
            continue
        if r.status_code == 200:
            return r
        if r.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code in (403, 999):
            STATE["bloqueado"] = True
            log.warning("linkedin_guest: o LinkedIn bloqueou as consultas hoje (%s); seguindo com as outras fontes",
                        r.status_code)
            return None
        return None
    return None


def search_jobs(terms: list[str], *, geo: str | None = None, remote: bool = False, days: int = 7, pages: int = 1,
                want_title=None, seen=None, max_details: int = 40, source: str = "LinkedIn (sem login)") -> list[dict]:
    """Busca cada termo e abre a descrição das vagas cujo título passa em want_title (regex) e que não estão
    em `seen` (função url -> bool). Vaga sem descrição (bloqueio no meio) ainda volta com título/empresa/local."""
    from sources.jobs import _job

    out, details, ids = [], 0, set()
    for term in terms:
        for page in range(pages):
            params = {"keywords": term, "start": 25 * page, "f_TPR": f"r{days * 86400}"}
            if geo:
                params["geoId"] = GEO.get(geo, geo)
            if remote:
                params["f_WT"] = "2"
            r = _get(SEARCH, params)
            if r is None:
                break
            cards = CARD.findall(r.text)
            for jid, title, company, loc, posted in cards:
                if jid in ids:
                    continue
                ids.add(jid)
                title, company, loc = _text(title), _text(company), _text(loc)
                url = f"https://www.linkedin.com/jobs/view/{jid}"
                if want_title is not None and not want_title.search(title):
                    continue
                if seen and seen(url):
                    continue
                text = ""
                if details < max_details:
                    d = _get(DETAIL.format(jid))
                    details += 1
                    if d is not None:
                        m = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', d.text, re.S)
                        text = _text(m.group(1)) if m else ""
                out.append(_job(title, url, company, loc, text, source, posted or None))
            if len(cards) < 10:
                break
    log.info("linkedin_guest: %d vagas, %d descrições abertas, %d consultas no total%s", len(out), details,
             STATE["consultas"], " (bloqueado)" if STATE["bloqueado"] else "")
    return out


def enrich_post(it: dict) -> dict:
    """Post público: troca o trecho da busca pelo texto inteiro e resolve os links lnkd.in da candidatura."""
    r = _get(it["url"])
    if r is None:
        return it
    m = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', r.text)
    if m:
        it["texto"] = clean(html.unescape(m.group(1)), 4000)
    links = []
    for short in list(dict.fromkeys(re.findall(r"https?://lnkd\.in/[A-Za-z0-9_-]+", r.text)))[:3]:
        lr = _get(short)
        if lr is None:
            continue
        real = re.findall(r'https?://[^"\'<>\s]+', lr.text)
        target = next((u for u in real if not re.search(r"(linkedin\.com|lnkd\.in|licdn\.com|w3\.org)", u)), None)
        if target:
            links.append(html.unescape(target))
    if links:
        it["links_candidatura"] = links
        it["texto"] += " " + " ".join(links)  # deixa a descoberta de empresas (InHire) achar o link
    return it
