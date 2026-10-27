"""Busca na web para fontes sem API (LinkedIn, Sympla, Even3...).

Ordem de preferência:
  1. SerpAPI (Google), se SERPAPI_KEY existir — 100 buscas grátis/mês.
  2. Ferramenta web_search do Claude (US$ 10 / 1000 buscas + tokens), limitada por `max_uses`.

Para evitar alucinação, só aceitamos URLs que realmente vieram dos resultados da busca.
"""
from __future__ import annotations

import json
import os
import re

from common import clean, get, log

WEB_SEARCH_TOOL = "web_search_20250305"  # variante suportada pelo Claude Haiku 4.5


# ---- orçamento diário da SerpAPI (plano grátis: 250/mês) ----
# Calculado no início da coleta: restantes ÷ dias até o fim do mês. Prioridade "alta" (LinkedIn, pessoas)
# pode usar tudo; "baixa" (Google Jobs, empresas) só usa se sobrar acima da reserva.
BUDGET = {"hoje": None, "usadas": 0}
RESERVA_ALTA = 4


def set_daily_budget() -> int | None:
    key = os.getenv("SERPAPI_KEY")
    if not key:
        return None
    try:
        from datetime import date

        acc = get("https://serpapi.com/account.json", params={"api_key": key}, timeout=30).json()
        left = int(acc.get("plan_searches_left", 0))
        today = date.today()
        nxt = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
        # o plano renova na data de assinatura (ex.: dia 26), não no dia 1: dividir pelos dias até o fim do
        # mês queimava a cota em 5 dias. Teto = 1,5x a média diária do plano (250/30 -> 12).
        plan = int(acc.get("searches_per_month") or 250)
        teto = max(int(plan / 30 * 1.5), 3)
        BUDGET["hoje"] = min(max(left // max((nxt - today).days, 1), min(left, 3)), teto, left)
        log.info("serpapi: %d restantes no mês; orçamento de hoje = %d buscas", left, BUDGET["hoje"])
    except Exception as e:
        log.warning("serpapi: não consegui ler a cota (%s)", e)
    return BUDGET["hoje"]


def take(priority: str = "alta") -> bool:
    """Reserva 1 busca do orçamento do dia. Retorna False se não houver saldo para essa prioridade."""
    if BUDGET["hoje"] is None:
        return True
    free = BUDGET["hoje"] - BUDGET["usadas"]
    if free <= 0 or (priority == "baixa" and free <= RESERVA_ALTA):
        log.info("serpapi: busca de prioridade %s pulada (orçamento do dia: %d/%d)", priority,
                 BUDGET["usadas"], BUDGET["hoje"])
        return False
    BUDGET["usadas"] += 1
    return True


def has_serpapi() -> bool:
    return bool(os.getenv("SERPAPI_KEY"))


def serpapi(query: str, recency: str = "qdr:w", priority: str = "alta") -> list[dict]:
    key = os.getenv("SERPAPI_KEY")
    if not key or not take(priority):
        return []
    params = {"engine": "google", "q": query, "api_key": key, "hl": "pt-BR"}  # o Google ignorou "num" desde 2025
    if recency:
        params["tbs"] = recency
    data = get("https://serpapi.com/search.json", params=params, timeout=60).json()
    return [{"titulo": r.get("title", ""), "url": r.get("link", ""), "texto": clean(r.get("snippet")),
             "data": r.get("date", "")} for r in data.get("organic_results", [])]


DDG_RECENCY = {"qdr:d": "d", "qdr:w": "w", "qdr:m": "m", "qdr:y": "y"}


def duckduckgo(query: str, recency: str | None = "qdr:w", priority: str = "alta") -> list[dict]:
    """DuckDuckGo via SerpAPI: respeita site:dominio melhor que o Google para posts do LinkedIn."""
    key = os.getenv("SERPAPI_KEY")
    if not key or not take(priority):
        return []
    params = {"engine": "duckduckgo", "q": query, "api_key": key, "kl": "wt-wt"}
    if recency in DDG_RECENCY:
        params["df"] = DDG_RECENCY[recency]
    data = get("https://serpapi.com/search.json", params=params, timeout=60).json()
    return [{"titulo": r.get("title", ""), "url": r.get("link", ""), "texto": clean(r.get("snippet")),
             "data": r.get("date", "")} for r in data.get("organic_results", [])]


def cascade(steps: list[tuple[str, str, str | None]], accept, want: int, label: str,
            first: str = "alta") -> list[dict]:
    """Tenta motores/consultas em ordem e para quando juntar `want` resultados aceitos.
    steps = [(motor, consulta, recência)]; motor = "ddg" | "google". Cada passo é 1 busca da cota."""
    out: list[dict] = []
    for i, (engine, query, recency) in enumerate(steps):
        # 1º passo de cada cascata é prioritário; os de reserva só rodam se sobrar orçamento no dia
        prio = first if i == 0 else "baixa"  # first="baixa": trilha extra (fraude) não disputa a cota principal
        try:
            got = (duckduckgo if engine == "ddg" else serpapi)(query, recency, prio)
        except Exception as e:
            log.warning("%s/%s falhou: %s", label, engine, e)
            continue
        new = [r for r in got if accept(r) and r["url"] not in {o["url"] for o in out}]
        out += new
        log.info("%s/%s: %d aceitos de %d", label, engine, len(new), len(got))
        if len(out) >= want:
            break
    return out


def claude_search(cfg: dict, instructions: str, allowed_domains: list[str] | None, max_uses: int) -> list[dict]:
    if not os.getenv("ANTHROPIC_API_KEY"):
        log.info("websearch: sem ANTHROPIC_API_KEY, pulando")
        return []
    import anthropic

    client = anthropic.Anthropic()
    tool = {"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": max_uses}
    if allowed_domains:
        tool["allowed_domains"] = allowed_domains
    prompt = (
        f"{instructions}\n\n"
        "Responda SOMENTE com um array JSON (sem texto antes ou depois), no formato:\n"
        '[{"titulo": "...", "url": "...", "texto": "resumo fiel de 1-2 frases do conteúdo", "data": "YYYY-MM-DD ou vazio"}]\n'
        "Use apenas URLs que apareceram nos resultados da busca. Se não achar nada relevante, responda []."
    )
    resp = client.messages.create(
        model=cfg["llm"]["model"],
        max_tokens=2000,
        tools=[tool],
        messages=[{"role": "user", "content": prompt}],
    )
    seen_urls = set()
    text = ""
    for block in resp.content:
        if block.type == "web_search_tool_result" and isinstance(block.content, list):
            seen_urls |= {r.url.split("?")[0].rstrip("/") for r in block.content}
        elif block.type == "text":
            text += block.text
    usage = resp.usage
    log.info("websearch: tokens in=%s out=%s", usage.input_tokens, usage.output_tokens)
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        results = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    # anti-alucinação: só URLs presentes nos resultados reais
    return [r for r in results
            if isinstance(r, dict) and r.get("url", "").split("?")[0].rstrip("/") in seen_urls]
